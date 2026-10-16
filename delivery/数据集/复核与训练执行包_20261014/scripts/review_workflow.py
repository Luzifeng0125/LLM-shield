"""Validate independent annotations, prepare adjudication, export approved gold.

No machine label is automatically promoted to gold. Standard library only.
"""
import argparse
import hashlib
import json
import math
from datetime import datetime
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATS = {'PERSON_NAME','PHONE','EMAIL','ID_CARD','BANK_CARD','STUDENT_ID','API_KEY',
        'WECHAT','BUDGET','ORG','LOCATION','DORM','GRADE','SENSITIVE_ATTR'}
ACTIONS = {'DELETE','LOCAL_AGGREGATE','GENERALIZE','PSEUDONYMIZE','RETAIN','PAUSE'}


def read(path):
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8-sig').splitlines() if s.strip()]


def write(path, rows):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        raise ValueError(f'不覆盖已有结果：{path}')
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')


def ensure(ok, message):
    if not ok:
        raise ValueError(message)


def entities(text, items):
    ensure(isinstance(items,list),'entities 必须为列表')
    seen=set()
    for e in items:
        ensure(set(e)=={'start','end','text','category'},'实体字段须为 start/end/text/category')
        a,b=e['start'],e['end']
        ensure(type(a) is int and type(b) is int and 0<=a<b<=len(text),'实体索引越界或非整数')
        ensure(text[a:b]==e['text'],'实体 text 与 Unicode 索引不一致')
        ensure(e['category'] in CATS,'未知实体类别')
        key=(a,b,e['category']);ensure(key not in seen,'重复实体');seen.add(key)
    spans=sorted((e['start'],e['end']) for e in items)
    ensure(all(a[1]<=b[0] for a,b in zip(spans,spans[1:])),'当前规范不允许嵌套或重叠实体，请裁决边界')


def target(t):
    ensure(set(t)=={'preferred_action','acceptable_actions','send_allowed','sanitized_text','reason'},'动作字段不完整')
    ensure(t['preferred_action'] in ACTIONS,'首选动作未填写或不合法')
    aa=t['acceptable_actions']
    ensure(isinstance(aa,list) and aa and len(set(aa))==len(aa) and set(aa)<=ACTIONS,'可接受动作不合法')
    ensure(t['preferred_action'] in aa,'首选动作必须在可接受动作内')
    pause=t['preferred_action']=='PAUSE'
    ensure(type(t['send_allowed']) is bool and t['send_allowed']==(not pause),'暂停与外发标志冲突')
    ensure(('PAUSE' not in aa) if not pause else aa==['PAUSE'],'暂停与允许外发不能混作可接受答案')
    ensure(t['sanitized_text'] is None if pause else isinstance(t['sanitized_text'],str) and bool(t['sanitized_text'].strip()),'暂停应无外发文本；允许外发应有非空文本')
    ensure(isinstance(t['reason'],str) and bool(t['reason'].strip()),'动作判断须有理由')


def validate_annotation(row, ann):
    if row['kind']=='dialogue':
        ensure(set(ann)=={'turns'},'对话标注字段错误')
        ensure(isinstance(ann['turns'],list) and len(ann['turns'])==len(row['turns']),'对话轮次不完整')
        for source,a in zip(row['turns'],ann['turns']):
            ensure(set(a)=={'turn_id','entities','target'} and a['turn_id']==source['turn_id'],'对话轮次或字段错误')
            entities(source['text'],a['entities']);target(a['target'])
    else:
        ensure(set(ann)==({'entities'} if row['kind']=='ner' else {'entities','target'}),'标注字段错误')
        entities(row['text'],ann['entities'])
        if row['kind']=='policy':target(ann['target'])


def index(rows):
    ids=[r['id'] for r in rows];ensure(len(ids)==len(set(ids)),'重复 ID')
    return {r['id']:r for r in rows}


def validate_review_audit(row):
    # Optional for progress files created before bulk approval was introduced.
    if 'review_audit' not in row:
        return
    audit=row['review_audit'];ensure(isinstance(audit,list),'操作记录必须为列表')
    for event in audit:
        ensure(isinstance(event,dict),'操作记录格式错误')
        method=event.get('method')
        keys={'action','method','reviewer','at'} | ({'batch_id'} if method=='batch' else set())
        ensure(set(event)==keys,'操作记录字段错误')
        ensure(event['action'] in {'approve','reopen'} and method in {'single','batch','edit'},'操作记录类型错误')
        ensure(method!='edit' or event['action']=='reopen','修改标注只能撤销完成状态')
        ensure(event['reviewer']==row['reviewer'],'操作记录与复核员不匹配')
        stamp=event['at']
        ensure(isinstance(stamp,str) and len(stamp)==24 and stamp.endswith('Z'),'操作记录时间格式错误')
        try:
            parsed=datetime.strptime(stamp,'%Y-%m-%dT%H:%M:%S.%fZ')
            ensure(parsed.isoformat(timespec='milliseconds')+'Z'==stamp,'操作记录时间格式错误')
        except ValueError as exc:
            raise ValueError('操作记录时间格式错误') from exc
        if method=='batch':
            ensure(isinstance(event['batch_id'],str) and bool(event['batch_id'].strip()),'缺少批量操作编号')
    if audit:
        ensure(row['reviewed']==(audit[-1]['action']=='approve'),'完成状态与最后一次操作记录不一致')


def validate_forms(path, batch, reviewer, require_complete=True):
    rows=read(path); expected=read(ROOT/'批次'/batch/f'复核员{reviewer}'/'空白复核表.jsonl')
    idx=index(rows);ensure(set(idx)==set(index(expected)),'批次 ID 缺失、多余或不匹配')
    for orig in expected:
        row=idx[orig['id']]
        for k,v in orig.items():
            if k not in {'reviewed','annotation','notes','review_audit'}:
                ensure(row.get(k)==v,f'{row["id"]} 的原文、上下文或复核员被修改')
        ensure(type(row.get('reviewed')) is bool,'reviewed 必须是布尔值')
        validate_review_audit(row)
        if require_complete:ensure(row['reviewed'],f'{row["id"]} 未完成')
        if row['reviewed']:
            try:validate_annotation(row,row['annotation'])
            except (ValueError,KeyError,TypeError) as e:raise ValueError(f'{row["id"]}: {e}') from e
    return rows


def canonical(ann):
    # Prose reasons are retained but not scored as substantive disagreement.
    if isinstance(ann,dict):return {k:canonical(v) for k,v in sorted(ann.items()) if k!='reason'}
    if isinstance(ann,list):
        values=[canonical(v) for v in ann]
        if values and isinstance(values[0],dict) and 'start' in values[0]:return sorted(values,key=lambda e:(e['start'],e['end'],e['category']))
        if all(isinstance(v,str) for v in values):return sorted(values)
        return values
    return ann


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(a,b,batch,out):
    aa=validate_forms(a,batch,'A');bb=index(validate_forms(b,batch,'B'))
    calibration=set(json.loads((ROOT/'培训试标编号.json').read_text(encoding='utf-8')))
    queue=[]
    for r in aa:
        other=bb[r['id']];same=canonical(r['annotation'])==canonical(other['annotation'])
        queue.append({'id':r['id'],'kind':r['kind'],'split':r['split'],'agreement':same,
                      'calibration':r['id'] in calibration,'must_inspect':not same or r['id'] in calibration,
                      'approved':False,'adjudicator':'','adjudicated_date':'','adjudication_reason':'',
                      'final_annotation':r['annotation'] if same else None,
                      'annotation_A':r['annotation'],'annotation_B':other['annotation']})
    for kind in ['ner','policy','dialogue']:
        pool=sorted([x for x in queue if x['kind']==kind and x['agreement'] and not x['calibration']],key=lambda x:hashlib.sha256(x['id'].encode()).hexdigest())
        for r in pool[:math.ceil(len(pool)*.2)]:r['must_inspect']=True
    scored=[r for r in queue if not r['calibration']]
    stats={'batch':batch,'total':len(queue),'not_complete':0,'scored_excluding_calibration':len(scored),
           'exact_agreement_rate':sum(r['agreement'] for r in scored)/len(scored) if scored else None,
           'disagreements':sum(not r['agreement'] for r in queue),
           'must_inspect':sum(r['must_inspect'] for r in queue),
           'source_A_sha256':digest(a),'source_B_sha256':digest(b),
           'warning':'严格一致率包含脱敏文本；措辞差异也会列入裁决，不等于模型错误率。'}
    out=Path(out);ensure(not out.exists(),'输出目录已存在，请指定新目录')
    write(out/'裁决表.jsonl',queue)
    (out/'比较统计.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2))


def export_gold(a,b,batch,decisions,out):
    aa=validate_forms(a,batch,'A');bb=index(validate_forms(b,batch,'B'));dd=index(read(decisions))
    ensure(set(dd)==set(index(aa)),'裁决表 ID 不完整')
    gold=[]
    for r in aa:
        d=dd[r['id']]
        ensure(d.get('approved') is True,f'{r["id"]} 尚未批准，不导出部分批次')
        ensure(d.get('annotation_A')==r['annotation'] and d.get('annotation_B')==bb[r['id']]['annotation'],'裁决输入与当前 A/B 结果不一致')
        for key in ['adjudicator','adjudicated_date','adjudication_reason']:
            ensure(isinstance(d.get(key),str) and bool(d[key].strip()),f'{r["id"]} 缺少裁决签署字段 {key}')
        validate_annotation(r,d['final_annotation'])
        record={k:v for k,v in r.items() if k not in {'annotation','reviewer','reviewed','notes','review_audit'}}
        if 'review_audit' in r or 'review_audit' in bb[r['id']]:
            record['review_audit']={'A':r.get('review_audit',[]),'B':bb[r['id']].get('review_audit',[])}
        record.update(annotation=d['final_annotation'],label_origin='human_dual_review_adjudicated',
                      human_reviewed=True,adjudicator=d['adjudicator'],adjudicated_date=d['adjudicated_date'],
                      adjudication_reason=d['adjudication_reason'],review_sha256={'A':digest(a),'B':digest(b)},
                      gold_schema_version='review-1.0',annotation_guideline_version='1.0',source_kind='synthetic')
        gold.append(record)
    splits={r['split'] for r in gold};ensure(len(splits)==1,'禁止混合 split 导出')
    write(out,gold);print(json.dumps({'gold_units':len(gold),'split':next(iter(splits)),'out':str(out)},ensure_ascii=False))


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='command',required=True)
    check=sub.add_parser('validate');check.add_argument('file',type=Path);check.add_argument('--batch',required=True);check.add_argument('--reviewer',choices=['A','B'],required=True)
    for command in ['compare','export']:
        p=sub.add_parser(command);p.add_argument('--a',required=True,type=Path);p.add_argument('--b',required=True,type=Path);p.add_argument('--batch',required=True);p.add_argument('--out',required=True,type=Path)
        if command=='export':p.add_argument('--decisions',required=True,type=Path)
    args=ap.parse_args()
    try:
        if args.command=='validate':
            rows=validate_forms(args.file,args.batch,args.reviewer,require_complete=False)
            print(json.dumps({'total':len(rows),'completed':sum(r['reviewed'] for r in rows)},ensure_ascii=False))
        elif args.command=='compare':compare(args.a,args.b,args.batch,args.out)
        else:export_gold(args.a,args.b,args.batch,args.decisions,args.out)
    except (ValueError,KeyError,TypeError) as exc:
        ap.exit(2,f'拒绝处理：{exc}\n')


if __name__=='__main__':main()
