"""Fetch the pinned public synthetic dataset. No authentication and no arbitrary code execution."""
from __future__ import annotations
import argparse,hashlib
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
REPO='wan9yu/pii-bench-zh'
REVISION='c350b94897af668517ff5de237d89f2ce2eaa6f0'
FILES={
 'data/pii_bench_zh.jsonl':'bcaa54909fd69c6737b8e442c4d740ce1bf5b95b7d4af70b2f2692010e1ff7a5',
 'data/pii_bench_zh_chat.jsonl':'4ddacd78dfac49b723032de5e1c29c432a44049245e03a8ea960c86bbf3b765c',
 'README.md':'2b7904843902b221ee027a61b9b868c60e468f4ac0b8aafb2c2958d9ef788de5',
}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--mirror',action='store_true',help='Use hf-mirror.com if the original host is unreachable')
    args=ap.parse_args(); host='hf-mirror.com' if args.mirror else 'huggingface.co'
    target=ROOT/'public/pii-bench-zh'; target.mkdir(parents=True,exist_ok=True)
    for source,digest in FILES.items():
        destination=target/Path(source).name
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=digest:
                raise SystemExit(f'Existing file changed; refusing to overwrite: {destination.name}')
            print('verified existing:',destination.name); continue
        request=Request(f'https://{host}/datasets/{REPO}/resolve/{REVISION}/{source}',headers={'User-Agent':'LLM-Shield-Dataset/1.0'})
        with urlopen(request,timeout=45) as response: data=response.read(10*1024*1024+1)
        if len(data)>10*1024*1024 or hashlib.sha256(data).hexdigest()!=digest:
            raise SystemExit('Download size/hash does not match the pinned release; file not written.')
        destination.write_bytes(data); print('downloaded and verified:',destination.name)

if __name__=='__main__': main()
