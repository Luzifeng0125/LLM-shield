"""Restore missing, unreviewed forms from the tracked synthetic batch sources.

Existing forms are never modified: they may contain human work. The generated
files are blank review inputs, not human annotations or gold data.
"""
import hashlib
import json

from build_batches import ROOT, blind, read


def restore() -> int:
    summary = json.loads((ROOT / '执行统计.json').read_text(encoding='utf-8'))
    pending = []
    for item in summary['batches']:
        batch = item['batch']
        source = read(ROOT / '裁决员专用' / batch / '机器建议勿提前给AB.jsonl')
        manifest = read(ROOT / '裁决员专用' / batch / '批次清单.jsonl')
        if len(source) != item['units'] or len(manifest) != len(source):
            raise ValueError(f'{batch}: source and manifest counts differ')
        for row, meta in zip(source, manifest):
            digest = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            if row['id'] != meta['id'] or digest != meta['source_sha256']:
                raise ValueError(f'{batch}: source manifest mismatch')
        for reviewer in ('A', 'B'):
            path = ROOT / '批次' / batch / f'复核员{reviewer}' / '空白复核表.jsonl'
            if path.exists():
                continue
            forms = [blind(row, meta['kind'], batch, reviewer)
                     for row, meta in zip(source, manifest)]
            pending.append((path, forms))
    for path, forms in pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            for form in forms:
                stream.write(json.dumps(form, ensure_ascii=False) + '\n')
        print(f'Restored unreviewed form: {path.relative_to(ROOT)}')
    return len(pending)


if __name__ == '__main__':
    print(f'New blank forms: {restore()}')
