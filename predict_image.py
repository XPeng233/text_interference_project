"""Apply frozen experimental defense to a user image without any attack metadata."""
import argparse,json,os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('image',type=Path);p.add_argument('--parameters',type=Path,default=Path('outputs/full/gate_tuning.json'));p.add_argument('--output',type=Path,default=Path('outputs/prediction'));a=p.parse_args()
os.environ.setdefault('HF_HOME',str(Path('cache/huggingface').resolve()))
import torch
from PIL import Image
from experiment import CLIPCache,OCRCache,image_key,softmax,js_divergence,fuse,argmax,CLASSES,atomic_json
torch.set_num_threads(4);torch.set_num_interop_threads(2)
gate=json.loads(a.parameters.read_text(encoding='utf-8'))['selected']
image=Image.open(a.image).convert('RGB').resize((224,224),Image.Resampling.BICUBIC)
ocr=OCRCache('cache/ocr');key=image_key(image);repair,record=ocr.repair(image,key);rkey=image_key(repair)
clip=CLIPCache('cache/clip','openai/clip-vit-base-patch32','cpu',2)
scores=clip.infer({key:image,rkey:repair});raw=softmax(scores[key]);fixed=softmax(scores[rkey]);js=js_divergence(raw,fixed)
final=fuse(raw,fixed,gate['alpha']) if js>gate['threshold'] else raw
a.output.mkdir(parents=True,exist_ok=True);repair.save(a.output/'repaired.png')
result={'classes':CLASSES,'original':CLASSES[argmax(raw)],'repaired':CLASSES[argmax(fixed)],'defended':CLASSES[argmax(final)],'js':js,'gate':gate,'gate_active':js>gate['threshold'],'ocr_boxes':record['boxes'],'probabilities':final,'warning':'Closed-set CIFAR10 categories only; probabilities are not calibrated confidence.'}
atomic_json(a.output/'prediction.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
