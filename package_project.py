"""Package verified deliverables, code, results and actually used image assets."""
from pathlib import Path
import json,zipfile,hashlib,csv
root=Path(__file__).resolve().parent
out=root/'deliverables'; summary=json.loads((root/'outputs/full/summary.json').read_text(encoding='utf-8'))
from verify_results import verify
verification=verify(root/'outputs/full', write=True)
assert summary['status']=='complete' and verification['verified']
assert (out/'paper.docx').is_file() and (out/'paper_final.pdf').is_file()
validation=json.loads((out/'document_validation.json').read_text(encoding='utf-8'))
assert validation['pdf_pages']==4
assert validation['pdf_sha256']==hashlib.sha256((out/'paper_final.pdf').read_bytes()).hexdigest()
assert validation['docx_sha256']==hashlib.sha256((out/'paper.docx').read_bytes()).hexdigest()
files=set()
for pattern in ['*.py','*.md','*.ps1','requirements-lock.txt','tests/*.py','outputs/full/*.json','outputs/full/*.csv','outputs/full/*.png','outputs/smoke/*.json','outputs/smoke/*.csv','deliverables/*.docx','deliverables/*.pdf','deliverables/*.md','deliverables/*.json','deliverables/*.png','logs/*.txt','logs/*.json']:
    files.update(p for p in root.glob(pattern) if p.is_file())
# Include all evaluated input and repaired image assets, without model weights or source dataset.
with (root/'outputs/full/samples.csv').open(encoding='utf-8-sig',newline='') as f:
    for r in csv.DictReader(f):
        for k in ['image_path','clean_path','repair_path']:
            p=Path(r[k].replace('\\','/'));p=p if p.is_absolute() else root/p
            if not p.is_file():raise FileNotFoundError(p)
            p.relative_to(root);files.add(p)
files.discard(out/'checksums.json')
files.discard(out/'paper.pdf')  # superseded pre-analysis draft, not a deliverable
files={p for p in files if p.name not in ['PROJECT_STATUS.md','last_error.json'] and not p.name.startswith('model_download')}
manifest={str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
(out/'checksums.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8');files.add(out/'checksums.json')
archive=out/'text_interference_project.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(files):z.write(p,str(p.relative_to(root)))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert 'deliverables/paper_final.pdf' in z.namelist()
print(f'Packaged {len(files)} files, {archive.stat().st_size/1024/1024:.2f} MiB: {archive}')
