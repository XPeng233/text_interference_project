"""Read-only smoke validation plus corrupt temporary copies (no inference)."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from verify_results import INPUT_FILES, verify

ROOT = Path(__file__).resolve().parents[1]


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='verify-', dir=ROOT/'tests')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in INPUT_FILES:
            shutil.copyfile(ROOT/'outputs/smoke'/name, self.root/name)

    def change_rows(self, fn):
        path = self.root/'samples.csv'
        with path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            rows, fields = list(reader), reader.fieldnames
        fn(rows)
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_valid_smoke_and_hashes(self):
        report = verify(self.root)
        self.assertTrue(report['verified'])
        self.assertEqual(len(report['checks']), 25)
        for name, digest in report['input_sha256'].items():
            self.assertEqual(digest, hashlib.sha256((self.root/name).read_bytes()).hexdigest())
        self.assertTrue((self.root/'verification.json').is_file())

    def test_missing_prediction_rejected(self):
        self.change_rows(lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, 'coverage'):
            verify(self.root, write=False)

    def test_wrong_split_rejected(self):
        self.change_rows(lambda rows: rows[0].update(split='test'))
        with self.assertRaisesRegex(ValueError, 'split mismatch'):
            verify(self.root, write=False)

    def test_missing_metric_rejected(self):
        path = self.root/'summary.json'
        summary = json.loads(path.read_text(encoding='utf-8'))
        summary['metrics'].pop()
        path.write_text(json.dumps(summary), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Metric coverage'):
            verify(self.root, write=False)

    def test_false_clean_eligibility_rejected(self):
        self.change_rows(lambda rows: rows[0].update(clean_correct='False' if rows[0]['clean_correct']=='True' else 'True'))
        with self.assertRaisesRegex(ValueError, 'Clean eligibility'):
            verify(self.root, write=False)

    def test_wrong_ci_rejected(self):
        path = self.root/'summary.json'
        summary = json.loads(path.read_text(encoding='utf-8'))
        summary['metrics'][0]['accuracy_ci95'] = [0, 0]
        path.write_text(json.dumps(summary), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'accuracy_ci95'):
            verify(self.root, write=False)


if __name__ == '__main__':
    unittest.main()
