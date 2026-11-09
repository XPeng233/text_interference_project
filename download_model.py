"""Prefetch fixed upstream CLIP files; no credentials or remote code."""
import os
from pathlib import Path
os.environ.setdefault('HF_HOME',str(Path('cache/huggingface').resolve()))
from huggingface_hub import snapshot_download
p=snapshot_download('openai/clip-vit-base-patch32',allow_patterns=['config.json','preprocessor_config.json','tokenizer_config.json','special_tokens_map.json','tokenizer.json','vocab.json','merges.txt','pytorch_model.bin'],max_workers=3)
print(p,flush=True)
Path('cache/model_path.txt').write_text(p,encoding='utf-8')
