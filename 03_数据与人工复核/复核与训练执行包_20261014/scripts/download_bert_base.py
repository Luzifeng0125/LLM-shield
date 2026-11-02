"""Download the official Chinese BERT snapshot as data, without remote code."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

REPO = 'google-bert/bert-base-chinese'
REVISION = '8f23c25b06e129b6c986331a13d8d025a92cf0ea'
MODEL_SHA256 = '3404a1ffd8da507042e8161013ba2a4fc49858b4e3f8fbf5ce5724f94883aec3'
ALLOWED = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
           'vocab.txt', 'model.safetensors', 'README.md', 'LICENSE'}


def download(out, endpoint='https://huggingface.co'):
    out = Path(out).resolve()
    if (out / 'download_manifest.json').exists():
        raise ValueError('Completed snapshot already exists; refusing overwrite')
    # Revision and file set verified against the official repository API. A
    # mirror can transport these exact files; published weight SHA256 is still
    # checked against the official source rather than a mirror-provided value.
    revision = REVISION
    files = ['README.md', 'config.json', 'tokenizer.json', 'tokenizer_config.json',
             'vocab.txt', 'model.safetensors']
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / 'download_state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    if state and state.get('revision') != revision:
        raise ValueError('Cached revision differs from the pinned official snapshot')
    records = state.get('files', {})
    for name in files:
        url = (f'{endpoint}/models/{REPO}/resolve/master/{name}' if endpoint == 'https://modelscope.cn'
               else f'{endpoint}/{REPO}/resolve/{revision}/{name}?download=true')
        target, part = out / name, out / (name + '.part')
        if target.exists():
            expected = records.get(name, {}).get('sha256')
            if expected and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
                continue
            raise ValueError('Existing file has no verified download record: ' + str(target))
        print('Downloading ' + name, flush=True)
        started = last = time.monotonic()
        for attempt in range(4):
            offset = part.stat().st_size if part.exists() else 0
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            request = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    partial = response.status == 206
                    if partial and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                        raise ValueError('Server returned the wrong byte range')
                    if not partial:
                        offset = 0
                    size = offset
                    length = response.headers.get('Content-Length')
                    expected_size = offset + int(length) if length is not None else None
                    with part.open('ab' if partial else 'wb') as stream:
                        while chunk := response.read(1024 * 1024):
                            stream.write(chunk)
                            size += len(chunk)
                            if time.monotonic() - last >= 15:
                                print(f'{name}: {size / 1048576:.1f} MiB', flush=True)
                                last = time.monotonic()
                if expected_size is not None and size != expected_size:
                    raise OSError(f'Incomplete download: {size}/{expected_size}')
                break
            except (OSError, urllib.error.URLError) as exc:
                if attempt == 3:
                    raise
                print(f'Resuming interrupted download ({type(exc).__name__})', flush=True)
        h = hashlib.sha256()
        with part.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                h.update(chunk)
        if name == 'model.safetensors' and h.hexdigest() != MODEL_SHA256:
            raise ValueError('Weight SHA256 differs from the published official model')
        part.rename(target)
        records[name] = {'sha256': h.hexdigest(), 'bytes': size, 'url': url,
                         'download_seconds': round(time.monotonic() - started, 2)}
        state_path.write_text(json.dumps({'revision': revision, 'files': records}, indent=2), encoding='utf-8')
    manifest = {'repository': REPO, 'official_reference_revision': revision,
                'transport_revision': 'master' if endpoint == 'https://modelscope.cn' else revision,
                'license': 'apache-2.0',
                'files': records, 'official_model_card': 'https://huggingface.co/' + REPO,
                'remote_code_executed': False}
    (out / 'download_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(out), 'revision': revision, 'files': list(records)}, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--endpoint', choices=['https://huggingface.co', 'https://hf-mirror.com', 'https://modelscope.cn'],
                        default='https://huggingface.co')
    args = parser.parse_args()
    download(args.out, args.endpoint)
