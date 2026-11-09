"""Validate completed prediction artifacts without inference; import verify(root, write=True)."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from experiment import CONDITIONS, METHODS, argmax, bootstrap_ci, fuse, softmax, js_divergence, wrong_target, tune_gate

INPUT_FILES = ('summary.json', 'samples.csv', 'selection.json', 'gate_tuning.json', 'parameters.json')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def boolean(value):
    require(value in ('True', 'False'), f'Invalid boolean: {value!r}')
    return value == 'True'


def equal(actual, expected, context):
    if expected is None:
        require(actual is None, f'{context}: expected null')
    elif isinstance(expected, (list, tuple)):
        require(isinstance(actual, (list, tuple)) and len(actual) == len(expected), f'{context}: shape mismatch')
        for a, b in zip(actual, expected):
            equal(a, b, context)
    else:
        require(isinstance(actual, (int, float)) and math.isfinite(actual) and abs(actual-expected) <= 1e-10,
                f'{context}: {actual!r} != {expected!r}')


def verify(root, write=True):
    root = Path(root)
    # Capture a single input snapshot; detect changes before publishing verification.
    payload = {name: (root/name).read_bytes() for name in INPUT_FILES}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    summary = json.loads(payload['summary.json'])
    selection = json.loads(payload['selection.json'])
    tuning = json.loads(payload['gate_tuning.json'])
    params = json.loads(payload['parameters.json'])
    require(summary.get('status') == 'complete', 'Require complete summary')
    require(summary['parameters'] == params, 'Parameters disagree with summary')
    rows = list(csv.DictReader(payload['samples.csv'].decode('utf-8-sig').splitlines()))
    require(bool(rows), 'Empty predictions')
    seed, boots = int(params['seed']), int(params['bootstrap'])
    per_class = 50 if params['full'] else int(params['limit'])
    ndev = min(10, max(1, per_class//5))
    selected = {}
    for sample in selection:
        sid = sample['sample_id']
        require(sid not in selected, f'Duplicate selection ID {sid}')
        require(sample['split'] in ('dev', 'test') and sample['label'] in range(10), 'Invalid selection')
        selected[sid] = sample
    for label in range(10):
        for split, count in [('dev', ndev), ('test', per_class-ndev)]:
            require(sum(s['label'] == label and s['split'] == split for s in selection) == count,
                    f'Selection count mismatch: {label}/{split}')
    sensitive = set()
    for label in range(10):
        sensitive.update(s['sample_id'] for s in [s for s in selection if s['label'] == label and s['split'] == 'test'][:5])
    extra = []
    if params.get('sensitivity'):
        extra += ['wrong_font20', 'wrong_font32', 'wrong_font44']
    if params.get('position_sensitivity'):
        extra += ['wrong_position_top', 'wrong_position_center', 'wrong_position_bottom']
    expected = {(sid, c, m) for sid in selected for c in CONDITIONS + (extra if sid in sensitive else []) for m in METHODS}
    index = {}
    for r in rows:
        for key in ('sample_id', 'label', 'pred', 'target', 'clean_pred'):
            r[key] = int(r[key])
        sid = r['sample_id']
        require(sid in selected, f'Unknown source {sid}')
        require(r['split'] == selected[sid]['split'] and r['label'] == selected[sid]['label'], f'Selection/split mismatch: {sid}')
        key = (sid, r['condition'], r['method'])
        require(key not in index, f'Duplicate prediction {key}')
        index[key] = r
        for name in ('correct', 'clean_correct', 'gate_active'):
            r[name] = boolean(r[name])
        r['probabilities'] = json.loads(r['probabilities'])
        probs = r['probabilities']
        require(len(probs) == 10 and all(math.isfinite(v) and 0 <= v <= 1 for v in probs), f'Invalid probabilities {key}')
        equal(sum(probs), 1, f'Probability sum {key}')
        require(r['pred'] == argmax(probs), f'Argmax mismatch {key}')
        require(r['correct'] == (r['pred'] == r['label']), f'Correct flag mismatch {key}')
        require(r['target'] == wrong_target(r['label'], sid, seed), f'Target mismatch {key}')
    require(set(index) == expected, f'Prediction coverage mismatch: missing={len(expected-set(index))}, unexpected={len(set(index)-expected)}')
    dev_rows = []
    gate = summary['gate']
    for r in rows:
        sid, condition, method = r['sample_id'], r['condition'], r['method']
        clean = index[(sid, 'clean', 'original')]
        original = index[(sid, condition, 'original')]
        require(all(r[k] == original[k] for k in ('logits_original', 'logits_repair', 'logits_oracle')),
                f'Cross-method logits disagree {sid}/{condition}/{method}')
        require(r['clean_pred'] == clean['pred'] and r['clean_correct'] == clean['correct'], f'Clean eligibility mismatch {sid}')
        p, q, o = [softmax(json.loads(r[k])) for k in ('logits_original', 'logits_repair', 'logits_oracle')]
        js = js_divergence(p, q)
        equal(float(r['js']), js, 'JS')
        active = js > gate['threshold']
        require(r['gate_active'] == active, 'Gate flag mismatch')
        expected_prob = {'original': p, 'repair': q, 'oracle': o, 'fixed_fusion': fuse(p,q,.5),
                         'js_gate': fuse(p,q,gate['alpha']) if active else p}[method]
        equal(r['probabilities'], expected_prob, f'Method probabilities {sid}/{condition}/{method}')
        if r['split'] == 'dev' and method == 'original':
            dev_rows.append(dict(r, p=p, q=q, js=js))
    best, trials = tune_gate(dev_rows)
    require(best == gate == tuning['selected'], 'Gate selection differs from development-only recomputation')
    require(trials == tuning['trials'], 'Gate trials mismatch')
    require(tuning['development_sample_ids'] == [s['sample_id'] for s in selection if s['split'] == 'dev'], 'Tuning IDs mismatch')
    metrics = {}
    for m in summary['metrics']:
        key = (m['condition'], m['method'])
        require(key not in metrics, f'Duplicate metric {key}')
        metrics[key] = m
    require(set(metrics) == {(c,m) for c in CONDITIONS+extra for m in METHODS}, 'Metric coverage mismatch')
    checks = []
    for (condition, method), m in metrics.items():
        rs = [r for r in rows if r['split'] == 'test' and r['condition'] == condition and r['method'] == method]
        require(len(rs) == m['n'] and rs, f'Metric count mismatch {condition}/{method}')
        orig = [index[(r['sample_id'],condition,'original')] for r in rs]
        acc = [int(r['correct']) for r in rs]
        delta = [a-int(b['correct']) for a,b in zip(acc,orig)]
        flips = [int(a['pred'] != b['pred']) for a,b in zip(rs,orig)]
        eligible = [r for r in rs if r['clean_correct'] and condition.startswith('wrong')]
        asr = [int(r['pred'] == r['target']) for r in eligible]
        asr_delta = [a-int(index[(r['sample_id'],condition,'original')]['pred'] == r['target']) for a,r in zip(asr,eligible)]
        mean = lambda values: sum(values)/len(values) if values else None
        computed = {'accuracy': mean(acc), 'accuracy_delta_vs_original': mean(delta), 'flip_vs_original': mean(flips),
                    'flip_vs_clean': mean([int(r['pred'] != r['clean_pred']) for r in rs]),
                    'targeted_clean_correct_n': len(asr), 'targeted_asr': mean(asr)}
        for name, values in [('accuracy_ci95',acc), ('paired_accuracy_delta_ci95',delta), ('flip_ci95',flips),
                             ('targeted_asr_ci95',asr), ('paired_asr_delta_ci95',asr_delta)]:
            computed[name] = bootstrap_ci(values,seed,boots)
        for name, value in computed.items():
            equal(m[name], value, f'{condition}/{method}/{name}')
        checks.append({'condition': condition, 'method': method, 'n':len(rs), **computed})
    require(all((root/name).read_bytes() == data for name,data in payload.items()), 'Inputs changed during verification')
    report = {'verified': True, 'verification_schema': 2, 'input_sha256': hashes,
              'development_sources': sum(s['split']=='dev' for s in selection),
              'test_sources': sum(s['split']=='test' for s in selection), 'prediction_rows':len(rows), 'checks':checks}
    if write:
        tmp = root/'verification.json.tmp'
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        tmp.replace(root/'verification.json')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', default='outputs/full')
    args = parser.parse_args()
    report = verify(args.directory)
    print(json.dumps({k:v for k,v in report.items() if k != 'checks'},indent=2))
