"""Lightweight unit tests; no models, dataset downloads or inference."""
import importlib.util
import math
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import experiment as ex


class CoreTests(unittest.TestCase):
    def test_help_no_dependencies(self):
        completed = subprocess.run([sys.executable, str(ROOT / 'experiment.py'), '--help'], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('--full', completed.stdout)

    def test_softmax_stable_and_normalized(self):
        p = ex.softmax([10000, 10001, 9999])
        self.assertAlmostEqual(sum(p), 1)
        self.assertEqual(ex.argmax(p), 1)
        self.assertEqual(p, ex.softmax([0, 1, -1]))

    def test_js_symmetry_bounds(self):
        p, q = [1., 0.], [0., 1.]
        self.assertAlmostEqual(ex.js_divergence(p, p), 0)
        self.assertAlmostEqual(ex.js_divergence(p, q), math.log(2))
        self.assertAlmostEqual(ex.js_divergence(p, q), ex.js_divergence(q, p))

    def test_fusion_endpoints(self):
        p, q = [.7, .3], [.2, .8]
        self.assertEqual(ex.fuse(p, q, 0), p)
        self.assertEqual(ex.fuse(p, q, 1), q)
        self.assertAlmostEqual(sum(ex.fuse(p, q, .5)), 1)

    def test_balanced_split_and_stable_smoke_membership(self):
        labels = [i for i in range(10) for _ in range(100)]
        full = ex.select_balanced(labels)
        smoke = ex.select_balanced(labels, 2)
        self.assertEqual(len(full), 500)
        self.assertEqual(full, ex.select_balanced(labels))
        membership = {r['sample_id']: r['split'] for r in full}
        self.assertEqual(len(membership), 500)
        for label in range(10):
            self.assertEqual(sum(r['label'] == label and r['split'] == 'dev' for r in full), 10)
            self.assertEqual(sum(r['label'] == label and r['split'] == 'test' for r in full), 40)
        for row in smoke:
            self.assertEqual(membership[row['sample_id']], row['split'])

    def test_wrong_targets_are_not_labels(self):
        for label in range(10):
            target = ex.wrong_target(label, 45, 2026)
            self.assertNotEqual(label, target)
            self.assertTrue(0 <= target < 10)
            self.assertEqual(target, ex.wrong_target(label, 45, 2026))

    def test_clip_invalid_and_boundary_boxes(self):
        self.assertEqual(ex.clipped_box((-5, -8, 20, 30), 224, 224), (0, 0, 22, 32))
        self.assertEqual(ex.clipped_box((220, 220, 300, 300), 224, 224), (218, 218, 224, 224))
        self.assertIsNone(ex.clipped_box((240, 240, 300, 300), 224, 224))
        self.assertIsNone(ex.clipped_box((20, 20, 10, 30), 224, 224))

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Pillow not installed')
    def test_overlay_reproducible_positions(self):
        from PIL import Image
        image = Image.new('RGB', (224, 224), (30, 70, 110))
        font, _ = ex.load_font(32)
        a, box = ex.text_patch(image, 'cat', font)
        b, same_box = ex.text_patch(image, 'cat', font)
        self.assertEqual(a.tobytes(), b.tobytes())
        self.assertEqual(box, same_box)
        self.assertEqual(a.size, (224, 224))
        top, topbox = ex.text_patch(image, 'cat', font, position='top')
        center, centerbox = ex.text_patch(image, 'cat', font, position='center')
        self.assertLess(topbox[1], centerbox[1])
        self.assertLess(centerbox[1], box[1])

    def test_tuning_rejects_test_data(self):
        with self.assertRaises(ValueError):
            ex.tune_gate([{'split': 'test'}])
        with self.assertRaises(ValueError):
            ex.tune_gate([])

    def test_tuning_selects_useful_repair(self):
        p, q = [.1, .9], [.9, .1]
        rows = [{'split': 'dev', 'label': 0, 'p': p, 'q': q, 'js': ex.js_divergence(p, q)}]
        best, trials = ex.tune_gate(rows)
        self.assertEqual(best['accuracy'], 1)
        self.assertEqual(len(trials), 36)

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'numpy not yet installed')
    def test_paired_bootstrap_constant(self):
        self.assertEqual(ex.bootstrap_ci([1, 1, 1], n_boot=20), [1., 1.])
        self.assertEqual(ex.bootstrap_ci([0, 0, 0], n_boot=20), [0., 0.])
        self.assertIsNone(ex.bootstrap_ci([]))

    @unittest.skipUnless(importlib.util.find_spec('PIL') and importlib.util.find_spec('cv2'), 'image dependencies not yet installed')
    def test_inpaint_no_box_is_identity(self):
        from PIL import Image
        image = Image.new('RGB', (224, 224), (24, 60, 90))
        repaired, boxes = ex.inpaint_boxes(image, [])
        self.assertEqual(image.tobytes(), repaired.tobytes())
        self.assertEqual(boxes, [])

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'numpy not yet installed')
    def test_asr_denominator_excludes_clean_errors(self):
        rows = []
        for method in ex.METHODS:
            for sid, clean_correct in [(0, True), (1, False)]:
                rows.append({'sample_id': sid, 'condition': 'wrong', 'split': 'test', 'method': method,
                             'correct': False, 'pred': 1, 'label': 0, 'target': 1,
                             'clean_correct': clean_correct, 'clean_pred': 0 if clean_correct else 2})
        summary = ex.summarize(rows, 20, 2026)
        self.assertEqual(summary[0]['targeted_clean_correct_n'], 1)
        self.assertEqual(summary[0]['targeted_asr'], 1)
        self.assertEqual(summary[0]['paired_accuracy_delta_ci95'], [0., 0.])


if __name__ == '__main__':
    unittest.main()
