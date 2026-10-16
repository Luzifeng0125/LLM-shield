"""Strict (start,end,category) entity scoring. No training and no automatic correction."""
from __future__ import annotations
import argparse,json,sys,time
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def read(p): return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--data',type=Path,default=ROOT/'ner/validation.jsonl')
    ap.add_argument('--out',type=Path,default=ROOT/'evaluation/current_detector_validation.json')
    ap.add_argument('--app',type=Path,default=ROOT.parents[1]/'app')
    ap.add_argument('--predictions',type=Path,help='Optional JSONL: id plus entities[{start,end,category}]')
    args=ap.parse_args(); data=read(args.data); preds=None
    if args.predictions:
        rows=read(args.predictions); preds={r['id']:r['entities'] for r in rows}
        assert len(preds)==len(rows), 'Duplicate prediction IDs'
        assert set(preds)=={r['id'] for r in data}, 'Prediction IDs must match the full evaluation set'
    else:
        sys.path.insert(0,str(args.app.resolve()))
        from llm_shield.m2_detect.pipeline import detect_and_segment
    tp=Counter(); fp=Counter(); fn=Counter(); exact=0; started=time.perf_counter()
    for r in data:
        predicted=preds[r['id']] if preds is not None else [s.to_dict() for s in detect_and_segment(r['text'])[0]]
        for e in predicted: assert 0<=e['start']<e['end']<=len(r['text']), f'Invalid predicted span: {r["id"]}'
        p={(e['start'],e['end'],e['category']) for e in predicted}
        g={(e['start'],e['end'],e['category']) for e in r['entities']}
        tp.update(e[2] for e in p&g); fp.update(e[2] for e in p-g); fn.update(e[2] for e in g-p)
        exact+=int(p==g)
    def metric(t,f,n):
        precision=t/(t+f) if t+f else 0.0; recall=t/(t+n) if t+n else 0.0
        return {'tp':t,'fp':f,'fn':n,'precision':round(precision,6),'recall':round(recall,6),
                'f1':round(2*t/(2*t+f+n),6) if 2*t+f+n else 0.0}
    labels=sorted(tp.keys()|fp.keys()|fn.keys())
    report={'model':'provided_predictions' if preds is not None else 'current_rule_context_detector',
        'data_file':args.data.name,'source_folder':args.data.parent.name,'documents':len(data),
        'matching':'exact character offsets and category; no partial-match credit',
        'micro':metric(sum(tp.values()),sum(fp.values()),sum(fn.values())),
        'per_category':{c:metric(tp[c],fp[c],fn[c]) for c in labels},
        'exact_document_matches':exact,'elapsed_seconds':round(time.perf_counter()-started,3),
        'note':'Synthetic weak/upstream labels; measures entity detection only, not task decision quality or end-to-end privacy.'}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('model','documents','micro','exact_document_matches','elapsed_seconds')},ensure_ascii=False))

if __name__=='__main__': main()
