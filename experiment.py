"""Reproducible CLIP text-overlay / OCR-inpainting experiment (no import-time ML dependencies)."""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import sys
import time

CLASSES = ['airplane', 'automobile', 'bird', 'cat', 'deer', 'dog', 'frog', 'horse', 'ship', 'truck']
CONDITIONS = ['clean', 'correct', 'wrong', 'neutral', 'block']
METHODS = ['original', 'repair', 'fixed_fusion', 'js_gate', 'oracle']
VERSION = 'ocr-clip-v1'


def softmax(logits):
    m = max(logits)
    exps = [math.exp(float(x) - m) for x in logits]
    total = sum(exps)
    return [x / total for x in exps]


def js_divergence(p, q):
    """Jensen-Shannon divergence in nats, bounded by log(2)."""
    m = [(a + b) / 2 for a, b in zip(p, q)]
    return sum((a * math.log(a / c) if a else 0) + (b * math.log(b / c) if b else 0)
               for a, b, c in zip(p, q, m)) / 2


def fuse(p, q, alpha):
    return [(1 - alpha) * a + alpha * b for a, b in zip(p, q)]


def argmax(p):
    return max(range(len(p)), key=p.__getitem__)


def wrong_target(label, sample_id, seed):
    return (label + 1 + random.Random(f'{seed}:{sample_id}:target').randrange(9)) % 10


def select_balanced(labels, per_class=50, seed=2026):
    """Fixed permutation per class; full dev/test membership persists in smoke subsets."""
    if not 2 <= per_class <= 50:
        raise ValueError('per_class must be between 2 and 50')
    selected = []
    ndev = min(10, max(1, per_class // 5))
    for label in range(10):
        ids = [i for i, y in enumerate(labels) if int(y) == label]
        random.Random(seed + label).shuffle(ids)
        if len(ids) < 50:
            raise ValueError('Each class must contain at least 50 samples')
        for split, chosen in [('dev', ids[:ndev]), ('test', ids[10:10 + per_class - ndev])]:
            selected.extend({'sample_id': i, 'label': label, 'split': split} for i in chosen)
    return selected


def clipped_box(box, width, height, pad=2):
    """Clip xyxy to valid exclusive crop bounds; reject empty/off-image boxes."""
    x0, y0, x1, y1 = box
    if x1 <= 0 or y1 <= 0 or x0 >= width or y0 >= height or x1 <= x0 or y1 <= y0:
        return None
    result = (max(0, int(math.floor(x0)) - pad), max(0, int(math.floor(y0)) - pad),
              min(width, int(math.ceil(x1)) + pad), min(height, int(math.ceil(y1)) + pad))
    return result if result[2] > result[0] and result[3] > result[1] else None


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def tune_gate(rows):
    """Only development rows can enter tuning. Tie-break toward less intervention."""
    if not rows or any(r['split'] != 'dev' for r in rows):
        raise ValueError('Gate tuning requires nonempty, exclusively development data')
    trials = []
    for threshold in [0.0, .005, .01, .02, .05, .1, .2, .4, .7]:
        for alpha in [.25, .5, .75, 1.0]:
            preds = [argmax(fuse(r['p'], r['q'], alpha)) if r['js'] > threshold else argmax(r['p']) for r in rows]
            accuracy = sum(p == r['label'] for p, r in zip(preds, rows)) / len(rows)
            interventions = sum(r['js'] > threshold for r in rows)
            trials.append({'threshold': threshold, 'alpha': alpha, 'accuracy': accuracy, 'interventions': interventions})
    best = max(trials, key=lambda t: (t['accuracy'], -t['interventions'], -t['alpha'], t['threshold']))
    return best, trials


def bootstrap_ci(values, seed=2026, n_boot=2000):
    """Percentile CI for a sample mean; pass paired differences for paired CI."""
    if not values:
        return None
    import numpy as np
    x = np.asarray(values, dtype=float)
    rng = np.random.default_rng(seed)
    means = []
    for start in range(0, n_boot, 128):
        indexes = rng.integers(0, len(x), size=(min(128, n_boot - start), len(x)))
        means.extend(x[indexes].mean(axis=1).tolist())
    return [float(v) for v in np.percentile(means, [2.5, 97.5])]


def load_font(size, explicit=None):
    from PIL import ImageFont
    candidates = [explicit] if explicit else ['C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf']
    for name in candidates:
        try:
            return ImageFont.truetype(name, size), str(name)
        except OSError:
            pass
    raise RuntimeError('A scalable English font is required; specify --font PATH')


def text_patch(image, text, font, position='bottom'):
    from PIL import ImageDraw
    result = image.copy()
    draw = ImageDraw.Draw(result)
    bbox = draw.textbbox((0, 0), text, font=font)
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Text is clipped at image boundaries, and the exact visible rectangle is recorded.
    if position not in ['top', 'center', 'bottom']:
        raise ValueError('position must be top, center or bottom')
    x = max(0, (224 - width - 8) // 2)
    y = {'top': 8, 'center': (224 - height - 8) // 2, 'bottom': 224 - height - 16}[position]
    box = clipped_box((x, y, x + width + 8, y + height + 8), 224, 224, pad=0)
    draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill='white')
    draw.text((x + 4 - bbox[0], y + 4 - bbox[1]), text, font=font, fill='black')
    return result, box


def inpaint_boxes(image, boxes):
    import cv2
    import numpy as np
    from PIL import Image
    rgb = np.asarray(image.convert('RGB')).copy()
    mask = np.zeros(rgb.shape[:2], dtype=np.uint8)
    clipped = []
    for box in boxes:
        box = clipped_box(box, rgb.shape[1], rgb.shape[0])
        if box:
            x0, y0, x1, y1 = box
            mask[y0:y1, x0:x1] = 255
            clipped.append(box)
    if clipped:
        # Work on the union crop plus real surrounding pixels rather than whole-image inpaint.
        x0 = max(0, min(b[0] for b in clipped) - 12)
        y0 = max(0, min(b[1] for b in clipped) - 12)
        x1 = min(rgb.shape[1], max(b[2] for b in clipped) + 12)
        y1 = min(rgb.shape[0], max(b[3] for b in clipped) + 12)
        patch, local_mask = rgb[y0:y1, x0:x1], mask[y0:y1, x0:x1]
        if bool((local_mask == 0).any()):
            rgb[y0:y1, x0:x1] = cv2.inpaint(patch, local_mask, 3, cv2.INPAINT_TELEA)
    return Image.fromarray(rgb), clipped


class OCRCache:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.engine = None
        self.hits = 0
        self.misses = 0
        self.compute_seconds = 0.0

    def repair(self, image, key):
        from PIL import Image
        import numpy as np
        record_path, image_path = self.root / f'{key}.json', self.root / f'{key}.png'
        if record_path.exists() and image_path.exists():
            self.hits += 1
            return Image.open(image_path).convert('RGB'), json.loads(record_path.read_text(encoding='utf-8'))
        if self.engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.engine = RapidOCR(intra_op_num_threads=4, inter_op_num_threads=1)
        self.misses += 1
        start = time.perf_counter()
        # RapidOCR's numpy interface expects BGR, unlike Pillow's RGB.
        detections, elapsed = self.engine(np.asarray(image)[:, :, ::-1].copy())
        boxes, texts = [], []
        for polygon, text, confidence in detections or []:
            points = np.asarray(polygon, dtype=float)
            boxes.append([float(points[:, 0].min()), float(points[:, 1].min()),
                          float(points[:, 0].max()), float(points[:, 1].max())])
            texts.append({'polygon': points.tolist(), 'text': str(text), 'confidence': float(confidence)})
        repaired, clipped = inpaint_boxes(image, boxes)
        record = {'detections': texts, 'boxes': clipped, 'seconds': time.perf_counter() - start,
                  'source': 'rapidocr_only', 'version': VERSION}
        self.compute_seconds += record['seconds']
        repaired.save(image_path)
        atomic_json(record_path, record)
        return repaired, record


class CLIPCache:
    def __init__(self, root, model_name, device, batch_size):
        import torch
        from transformers import CLIPModel, CLIPProcessor
        self.torch, self.device, self.batch_size = torch, device, batch_size
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        start = time.perf_counter()
        self.processor = CLIPProcessor.from_pretrained(model_name)
        self.model = CLIPModel.from_pretrained(model_name).eval().to(device)
        self.text = self.processor(text=[f'a photo of a {c}.' for c in CLASSES], return_tensors='pt', padding=True)
        self.text = {k: v.to(device) for k, v in self.text.items()}
        self.load_seconds = time.perf_counter() - start
        self.hits, self.misses, self.inference_seconds = 0, 0, 0.0
        self.fingerprint = hashlib.sha256((VERSION + model_name + str(getattr(self.model.config, '_commit_hash', None)) + '|'.join(CLASSES)).encode()).hexdigest()[:20]

    def infer(self, images):
        results, missing = {}, {}
        for key, image in images.items():
            path = self.root / f'{self.fingerprint}-{key}.json'
            if path.exists():
                results[key] = json.loads(path.read_text(encoding='utf-8'))['logits']
                self.hits += 1
            else:
                missing[key] = image
        keys = list(missing)
        for offset in range(0, len(keys), self.batch_size):
            batch_keys = keys[offset:offset + self.batch_size]
            if self.device.startswith('cuda'):
                self.torch.cuda.synchronize()
            start = time.perf_counter()
            inp = self.processor(images=[missing[k] for k in batch_keys], return_tensors='pt')
            pixels = inp['pixel_values'].to(self.device)
            with self.torch.inference_mode():
                output = self.model(pixel_values=pixels, **self.text).logits_per_image.float().cpu().tolist()
            duration = time.perf_counter() - start
            self.inference_seconds += duration
            for key, logits in zip(batch_keys, output):
                results[key] = logits
                atomic_json(self.root / f'{self.fingerprint}-{key}.json', {'logits': logits, 'seconds_per_image': duration / len(batch_keys)})
                self.misses += 1
        return results


def image_key(image, namespace=''):
    return hashlib.sha256(VERSION.encode() + namespace.encode() + image.tobytes()).hexdigest()[:32]


def summarize(rows, n_boot, seed):
    test = [r for r in rows if r['split'] == 'test']
    output = []
    for condition in dict.fromkeys(r['condition'] for r in test):
        original = {r['sample_id']: r for r in test if r['condition'] == condition and r['method'] == 'original'}
        for method in METHODS:
            subset = [r for r in test if r['condition'] == condition and r['method'] == method]
            if not subset:
                continue
            acc = [int(r['correct']) for r in subset]
            differences = [int(r['correct']) - int(original[r['sample_id']]['correct']) for r in subset]
            flips = [int(r['pred'] != original[r['sample_id']]['pred']) for r in subset]
            # A targeted attack is defined only for wrong-label overlays, not correct/neutral/block.
            targeted = [r for r in subset if r['clean_correct'] and condition.startswith('wrong')]
            asr = [int(r['pred'] == r['target']) for r in targeted]
            base_asr = [int(original[r['sample_id']]['pred'] == r['target']) for r in targeted]
            record = {'condition': condition, 'method': method, 'n': len(subset),
                      'accuracy': sum(acc) / len(acc), 'accuracy_ci95': bootstrap_ci(acc, seed, n_boot),
                      'accuracy_delta_vs_original': sum(differences) / len(differences),
                      'paired_accuracy_delta_ci95': bootstrap_ci(differences, seed, n_boot),
                      'flip_vs_original': sum(flips) / len(flips), 'flip_ci95': bootstrap_ci(flips, seed, n_boot),
                      'flip_vs_clean': sum(r['pred'] != r['clean_pred'] for r in subset) / len(subset),
                      'targeted_clean_correct_n': len(asr), 'targeted_asr': sum(asr) / len(asr) if asr else None,
                      'targeted_asr_ci95': bootstrap_ci(asr, seed, n_boot),
                      'paired_asr_delta_ci95': bootstrap_ci([a-b for a,b in zip(asr, base_asr)], seed, n_boot)}
            output.append(record)
    return output


def make_plots(rows, metrics, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    output = Path(output)
    conditions = list(dict.fromkeys(m['condition'] for m in metrics))
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    x = np.arange(len(conditions))
    for i, method in enumerate(METHODS):
        values = [next(m['accuracy'] for m in metrics if m['condition'] == c and m['method'] == method) for c in conditions]
        axes[0].bar(x + (i - 2) * .15, values, .15, label=method)
        attack = [m for m in metrics if m['method'] == method and m['targeted_asr'] is not None]
        axes[1].plot([m['condition'] for m in attack], [m['targeted_asr'] for m in attack], marker='o', label=method)
    axes[0].set_xticks(x, conditions, rotation=25)
    axes[0].set_title('Test accuracy'); axes[1].set_title('Targeted ASR | clean originally correct')
    for ax in axes:
        ax.set_ylim(0, 1); ax.legend(fontsize=7); ax.grid(axis='y', alpha=.2)
    fig.tight_layout(); fig.savefig(output / 'accuracy_asr.png', dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5))
    for split in ['dev', 'test']:
        ax.hist([r['js'] for r in rows if r['method'] == 'original' and r['split'] == split], bins=30, alpha=.5, label=split)
    ax.set_xlabel('JS divergence (nats)'); ax.set_ylabel('Sample-condition count'); ax.legend()
    fig.tight_layout(); fig.savefig(output / 'js_distribution.png', dpi=160); plt.close(fig)
    # Select actual targeted successes and failures; never manufacture examples if empty.
    indexes = {(r['sample_id'], r['condition'], r['method']): r for r in rows}
    candidates = [r for r in rows if r['split'] == 'test' and r['condition'] == 'wrong' and r['method'] == 'original' and r['clean_correct'] and r['pred'] == r['target']]
    manifest = {}
    from PIL import Image
    for category, success in [('success', True), ('failure', False)]:
        chosen = [r for r in candidates if bool(indexes[(r['sample_id'], 'wrong', 'js_gate')]['correct']) == success][:4]
        manifest[category] = [r['sample_id'] for r in chosen]
        if not chosen:
            continue
        fig, axes = plt.subplots(len(chosen), 3, figsize=(10, 3.5 * len(chosen)), squeeze=False)
        for i, row in enumerate(chosen):
            gated = indexes[(row['sample_id'], 'wrong', 'js_gate')]
            for j, (name, path) in enumerate([('clean', row['clean_path']), ('attacked', row['image_path']), ('OCR repair', row['repair_path'])]):
                axes[i, j].imshow(Image.open(path)); axes[i, j].axis('off')
                axes[i, j].set_title(f'{name} | true={CLASSES[row["label"]]}')
            axes[i, 1].set_xlabel(f'Original: {CLASSES[row["pred"]]}')
            axes[i, 2].set_title(f'OCR repair | gated: {CLASSES[gated["pred"]]}')
        fig.suptitle(f'Actual attack cases: defense {category}')
        fig.tight_layout(); fig.savefig(output / f'cases_{category}.png', dpi=150); plt.close(fig)
    atomic_json(output / 'case_manifest.json', {'definition': 'Originally clean-correct and wrong-overlay target hit; success means gated prediction recovers true class.', 'examples': manifest, 'note': 'Empty groups have no figure; no examples are fabricated.'})


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--limit', type=int, default=2, metavar='PER_CLASS', help='Smoke subset per class (2..50); default 2 = 20 source images')
    mode.add_argument('--full', action='store_true', help='500 sources: per class 10 development + 40 held-out test')
    p.add_argument('--output', type=Path, default=Path('outputs'))
    p.add_argument('--data-dir', type=Path, default=Path('cache/data'))
    p.add_argument('--cache-dir', type=Path, default=Path('cache'), help='Persistent model, OCR and logits cache')
    p.add_argument('--model', default='openai/clip-vit-base-patch32')
    p.add_argument('--device', default='cpu')
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--threads', type=int, default=4)
    p.add_argument('--seed', type=int, default=2026)
    p.add_argument('--font', type=str)
    p.add_argument('--bootstrap', type=int, default=2000)
    p.add_argument('--sensitivity', action='store_true', help='Wrong-label font sizes 20/32/44 on fixed first 5 test images/class; uses frozen gate')
    p.add_argument('--position-sensitivity', action='store_true', help='Wrong-label top/center/bottom overlays, font 32, fixed first 5 test images/class; frozen gate')
    p.add_argument('--no-download', action='store_true', help='Require CIFAR10 already downloaded; set HF_HUB_OFFLINE=1 separately for CLIP')
    return p


def run(args):
    started = time.perf_counter()
    n = 50 if args.full else args.limit
    if not 2 <= n <= 50 or args.batch_size < 1 or args.threads < 1 or args.bootstrap < 1:
        raise ValueError('limit 2..50; batch-size, threads and bootstrap must be positive')
    if args.device == 'cpu' and args.batch_size > 8:
        raise ValueError('CPU batch size is capped at 8')
    for key in ['OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS']:
        os.environ[key] = str(args.threads)
    os.environ.setdefault('HF_HOME', str((args.cache_dir / 'huggingface').resolve()))
    # HF_ENDPOINT, if supplied by the caller, is respected by huggingface_hub.
    import torch
    import numpy as np
    from torchvision.datasets import CIFAR10
    from PIL import Image, ImageDraw
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(max(1, min(2, args.threads)))
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    params = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    environment = {'python': sys.version, 'platform': platform.platform(), 'torch_threads': torch.get_num_threads(), 'packages': {}}
    for package in ['torch', 'torchvision', 'transformers', 'Pillow', 'numpy', 'pandas', 'matplotlib', 'scipy', 'opencv-python-headless', 'rapidocr_onnxruntime', 'onnxruntime']:
        try:
            environment['packages'][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            environment['packages'][package] = None
    atomic_json(args.output / 'environment.json', environment)
    font, font_path = load_font(32, args.font)
    params.update({'font_resolved': font_path, 'conditions': CONDITIONS, 'version': VERSION,
                   'condition_note': 'Five controlled conditions; neutral object is weakly semantic but not a CIFAR10 class name.',
                   'fixed_fusion_alpha': .5})
    atomic_json(args.output / 'parameters.json', params)
    dataset = CIFAR10(str(args.data_dir), train=False, download=not args.no_download)
    selection = select_balanced(dataset.targets, n, args.seed)
    atomic_json(args.output / 'selection.json', selection)
    ocr = OCRCache(args.cache_dir / 'ocr')
    clip = CLIPCache(args.cache_dir / 'clip', args.model, args.device, args.batch_size)
    artifact_dir = args.output / 'images'; artifact_dir.mkdir(exist_ok=True)
    base_rows = []
    sens_counts = {i: 0 for i in range(10)}
    for count, sample in enumerate(selection):
        sid, label = sample['sample_id'], sample['label']
        clean = dataset[sid][0].convert('RGB').resize((224, 224), Image.Resampling.BICUBIC)
        target = wrong_target(label, sid, args.seed)
        wrong, wrong_box = text_patch(clean, CLASSES[target], font)
        correct, correct_box = text_patch(clean, CLASSES[label], font)
        neutral, neutral_box = text_patch(clean, 'object', font)
        block = clean.copy()
        ImageDraw.Draw(block).rectangle((wrong_box[0], wrong_box[1], wrong_box[2]-1, wrong_box[3]-1), fill='white')
        variants = [('clean', clean, None, ''), ('correct', correct, correct_box, CLASSES[label]),
                    ('wrong', wrong, wrong_box, CLASSES[target]), ('neutral', neutral, neutral_box, 'object'),
                    ('block', block, wrong_box, '')]
        if (args.sensitivity or args.position_sensitivity) and sample['split'] == 'test' and sens_counts[label] < 5:
            sens_counts[label] += 1
            if args.sensitivity:
                for size in [20, 32, 44]:
                    size_font, _ = load_font(size, args.font)
                    variant, box = text_patch(clean, CLASSES[target], size_font)
                    variants.append((f'wrong_font{size}', variant, box, CLASSES[target]))
            if args.position_sensitivity:
                for position in ['top', 'center', 'bottom']:
                    variant, box = text_patch(clean, CLASSES[target], font, position)
                    variants.append((f'wrong_position_{position}', variant, box, CLASSES[target]))
        images, pending = {}, []
        clean_path = artifact_dir / f'{image_key(clean)}.png'
        if not clean_path.exists(): clean.save(clean_path)
        for condition, image, box, text in variants:
            key = image_key(image)
            image_path = artifact_dir / f'{key}.png'
            if not image_path.exists(): image.save(image_path)
            # Oracle rectangle is deliberately never passed to OCRCache.
            repaired, ocr_record = ocr.repair(image, key)
            oracle_image, _ = inpaint_boxes(image, [box] if box else [])
            keys = [key, image_key(repaired), image_key(oracle_image)]
            images.update(zip(keys, [image, repaired, oracle_image]))
            pending.append({**sample, 'condition': condition, 'target': target, 'overlay_text': text,
                            'overlay_box': list(box) if box else None, 'keys': keys,
                            'ocr_boxes': ocr_record['boxes'], 'ocr_detections': ocr_record['detections'],
                            'ocr_seconds': ocr_record['seconds'], 'image_path': str(image_path),
                            'clean_path': str(clean_path),
                            'repair_path': str(ocr.root / f'{key}.png')})
        logits = clip.infer(images)
        for row in pending:
            row['logits_original'], row['logits_repair'], row['logits_oracle'] = [logits[k] for k in row.pop('keys')]
            row['p'], row['q'], row['o'] = [softmax(row[k]) for k in ['logits_original', 'logits_repair', 'logits_oracle']]
            row['js'] = js_divergence(row['p'], row['q'])
            base_rows.append(row)
        print(f'[{count+1}/{len(selection)}] sample={sid} {sample["split"]}; CLIP misses={clip.misses}, OCR misses={ocr.misses}', flush=True)
    gate, trials = tune_gate([r for r in base_rows if r['split'] == 'dev' and r['condition'] in CONDITIONS])
    atomic_json(args.output / 'gate_tuning.json', {'selected': gate, 'trials': trials, 'objective': 'Mean development accuracy across five equally weighted conditions; test labels never used.', 'development_sample_ids': [r['sample_id'] for r in selection if r['split'] == 'dev']})
    clean_preds = {r['sample_id']: argmax(r['p']) for r in base_rows if r['condition'] == 'clean'}
    rows = []
    for base in base_rows:
        p, q, o = base['p'], base['q'], base['o']
        active = base['js'] > gate['threshold']
        probs = [p, q, fuse(p, q, .5), fuse(p, q, gate['alpha']) if active else p, o]
        for method, prob in zip(METHODS, probs):
            row = {k: v for k, v in base.items() if k not in ['p', 'q', 'o']}
            row.update({'method': method, 'pred': argmax(prob), 'probabilities': prob,
                        'correct': argmax(prob) == base['label'], 'clean_pred': clean_preds[base['sample_id']],
                        'clean_correct': clean_preds[base['sample_id']] == base['label'], 'gate_active': active})
            rows.append(row)
    with (args.output / 'samples.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) or v is None else v for k, v in row.items()})
    metrics = summarize(rows, args.bootstrap, args.seed)
    make_plots(rows, metrics, args.output)
    timing = {'wall_seconds': time.perf_counter() - started, 'clip_load_seconds': clip.load_seconds,
              'clip_uncached_inference_seconds': clip.inference_seconds, 'clip_cache_hits': clip.hits,
              'clip_cache_misses': clip.misses, 'ocr_cache_hits': ocr.hits, 'ocr_cache_misses': ocr.misses,
              'ocr_uncached_compute_seconds': ocr.compute_seconds,
              'note': 'Per-row OCR seconds are original cached compute duration, not current-run latency. Wall time includes setup, downloads, plots and statistics. Shared inference means method-specific end-to-end timing is not estimated.'}
    atomic_json(args.output / 'summary.json', {'status': 'complete', 'parameters': params, 'gate': gate, 'timing': timing,
                    'metrics': metrics, 'statistical_notes': 'Test only. Bootstrap resamples source images within each condition, paired across methods, percentile 95% CI; no multiplicity correction. ASR denominator is clean-original-correct sources; null for non-targeted conditions or empty denominator. Oracle uses supplied overlay rectangles and is diagnostic only.'})
    print(f'Complete. Results: {args.output.resolve()}', flush=True)


def main():
    args = parser().parse_args()
    try:
        run(args)
    except Exception as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        atomic_json(args.output / 'last_error.json', {'type': type(exc).__name__, 'message': str(exc), 'time': time.strftime('%Y-%m-%dT%H:%M:%S')})
        raise


if __name__ == '__main__':
    main()
