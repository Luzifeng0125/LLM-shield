"""Freeze deterministic human review batches without modifying dataset v1."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / '隐盾数据集_v1'


def read(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f'Refusing to overwrite: {path}')
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def take(rows, count, salt):
    return sorted(rows, key=lambda r: hashlib.sha256((salt+r['id']).encode()).hexdigest())[:count]


def target_form():
    return {'preferred_action': None, 'acceptable_actions': [], 'send_allowed': None,
            'sanitized_text': None, 'reason': ''}


def blind(row, kind, batch, reviewer):
    base = {k: row[k] for k in ('id','split','text','task','task_description','identity',
            'recipient','trusted_context','trusted_policy') if k in row}
    if kind == 'dialogue':
        base['turns'] = [{'turn_id': t['turn_id'], 'text': t['text']} for t in row['turns']]
        annotation = {'turns': [{'turn_id': t['turn_id'], 'entities': [], 'target': target_form()}
                                for t in row['turns']]}
    else:
        annotation = {'entities': []}
        if kind == 'policy':
            annotation['target'] = target_form()
    # Human forms do not contain provisional target labels or generator family names.
    base.update(batch=batch, kind=kind, reviewer=reviewer, reviewed=False,
                annotation=annotation, notes='')
    return base


def build():
    if (ROOT/'批次').exists():
        raise ValueError('批次已存在。为保护人工结果，不覆盖；新版本请使用新目录。')
    stats = json.loads((DATA/'stats.json').read_text(encoding='utf-8'))
    cats = stats['categories']; actions = stats['actions']
    selected = read(DATA/'review/proposed_labels.jsonl')
    summaries = []
    for split, name in [('train','01_训练试标'),('validation','02_独立验证'),('test','03_封存测试')]:
        ner = read(DATA/'ner'/f'{split}.jsonl')
        policy = read(DATA/'policy'/f'{split}.jsonl')
        chats = read(DATA/'dialogues'/f'{split}.jsonl')
        kinds = {r['id']: 'ner' for r in ner} | {r['id']: 'policy' for r in policy} | {r['id']: 'dialogue' for r in chats}
        if split == 'train':
            batch = list(selected)
            for kind in ['hard_negative','mixed_prose','table']:
                for v in range(4):
                    batch += take([r for r in ner if r['kind']==kind and r['template_family'].endswith(f'-v{v}')], 3, name)
        else:
            batch = []
            for cat in cats:
                batch += take([r for r in ner if r['kind']=='single_entity' and r['entities'][0]['category']==cat], 2, name)
            for kind, n in [('hard_negative',12),('mixed_prose',8),('table',8)]:
                batch += take([r for r in ner if r['kind']==kind], n, name)
            for action in actions:
                batch += take([r for r in policy if r['target']['preferred_action']==action], 4, name)
            for scenario in sorted({r['scenario'] for r in chats}):
                batch += take([r for r in chats if r['scenario']==scenario], 2, name)
        assert len({r['id'] for r in batch}) == len(batch)
        assert all(r['split']==split for r in batch)
        for who in ['A','B']:
            forms = [blind(r,kinds[r['id']],name,who) for r in batch]
            dest = ROOT/'批次'/name/f'复核员{who}'
            write(dest/'空白复核表.jsonl', forms)
            payload = json.dumps(forms,ensure_ascii=False).replace('<','\\u003c')
            html = (ROOT/'scripts/reviewer.html').read_text(encoding='utf-8').replace('__PAYLOAD__',payload)
            (dest/'打开复核.html').write_text(html,encoding='utf-8')
        write(ROOT/'裁决员专用'/name/'机器建议勿提前给AB.jsonl',batch)
        manifest = [{'id':r['id'],'split':split,'kind':kinds[r['id']],
                     'stratum': r.get('scenario',r.get('kind','policy')),
                     'template_family':r['template_family'],
                     'source_sha256':hashlib.sha256(json.dumps(r,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
                    for r in batch]
        write(ROOT/'裁决员专用'/name/'批次清单.jsonl',manifest)
        counts = Counter(kinds[r['id']] for r in batch)
        summaries.append({'batch':name,'split':split,'units':len(batch),**counts,
                          'sft_rows_if_all_approved':counts['ner']+counts['policy']+counts['dialogue']*3})
        if split=='train':
            criteria = [lambda r:r.get('kind')=='single_entity' and r['entities'][0]['category']=='PERSON_NAME',
                        lambda r:r.get('kind')=='single_entity' and r['entities'][0]['category']=='DORM',
                        lambda r:r.get('kind')=='single_entity' and r['entities'][0]['category']=='GRADE',
                        lambda r:r.get('kind')=='hard_negative',
                        lambda r:r.get('target',{}).get('preferred_action')=='DELETE',
                        lambda r:r.get('target',{}).get('preferred_action')=='RETAIN',
                        lambda r:r.get('scenario')=='embedded_instruction',
                        lambda r:r.get('scenario')=='ambiguous_reference']
            calibration = [next(r['id'] for r in batch if f(r)) for f in criteria]
            (ROOT/'培训试标编号.json').write_text(json.dumps(calibration,ensure_ascii=False,indent=2),encoding='utf-8')
    summary = {'dataset':'隐盾数据集_v1','dataset_version':'1.0','seed':'sha256 stable selection',
               'created_date':'2026-10-14','human_gold_count':0,'batches':summaries,
               'source_manifest_sha256':hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest()}
    (ROOT/'执行统计.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--refresh-ui']:
        for file in (ROOT/'批次').glob('*/复核员*/空白复核表.jsonl'):
            forms=read(file)
            if any(r['reviewed'] or r['notes'] for r in forms):
                raise ValueError('空白表中发现人工工作，停止更新页面')
            payload=json.dumps(forms,ensure_ascii=False).replace('<','\\u003c')
            (file.parent/'打开复核.html').write_text((ROOT/'scripts/reviewer.html').read_text(encoding='utf-8').replace('__PAYLOAD__',payload),encoding='utf-8')
        print('Six blank review pages refreshed; JSONL forms unchanged.')
    else:
        build()
