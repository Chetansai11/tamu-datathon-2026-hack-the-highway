"""Fetch the cited, ungated small model into this checkout, without changing packages."""
from pathlib import Path
import argparse
import json
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runs' / 'runtime'))
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
from huggingface_hub import HfApi, snapshot_download


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='Qwen/Qwen2.5-1.5B-Instruct')
    parser.add_argument('--out', default='runs/models/qwen2.5-1.5b-instruct')
    args = parser.parse_args()
    info = HfApi().model_info(args.model)
    path = snapshot_download(args.model, revision=info.sha, local_dir=args.out,
                             allow_patterns=['*.json', '*.safetensors', '*.txt', 'README.md', 'LICENSE'])
    record = {'model': args.model, 'revision': info.sha, 'path': str(Path(path).resolve())}
    Path(args.out, 'provenance.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
