"""Export only action-training records; never train or replace a production model."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_APP=ROOT.parents[1]/'app'

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--app',type=Path,default=DEFAULT_APP)
    args=ap.parse_args(); sys.path.insert(0,str(args.app.resolve()))
    from llm_shield.schema import Span,Segment,Action
    from llm_shield.m4_necessity.model import build_feature_text
    from llm_shield.m3_decide.constraints import action_applicable,check_hard
    out=ROOT/'legacy_actions'; out.mkdir(exist_ok=True)
    counts={}
    for split in ('train','validation','test'):
        rows=[]
        for line in (ROOT/'policy'/f'{split}.jsonl').read_text(encoding='utf-8').splitlines():
            r=json.loads(line)
            spans=[Span(e['start'],e['end'],e['text'],e['category'],detector='synthetic_annotation') for e in r['entities']]
            seg=Segment(r['id'],r['text'],0,len(r['text']),spans)
            action=Action(r['target']['preferred_action'])
            # Verify compatibility only. Do not derive labels from this gate or change the runtime.
            assert action_applicable(action,seg,r['task'])
            assert all(c.passed for c in check_hard(action,seg,r['task'],r['recipient'],r['identity'])),r['id']
            rows.append({'feature':build_feature_text(seg,r['task'],r['recipient'],task_description=r['task_description'],identity_key=r['identity']),
                'label':action.value,'source_case_id':r['template_family'],'document_id':r['id'],
                'source':'synthetic_construction_unreviewed','human_reviewed':False,'split':split})
        (out/f'{split}.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
        counts[split]=len(rows)
    print(json.dumps({'exported':counts,'note':'Current classifier trainer internally resplits train by source_case_id. Keep validation/test separate. Outputs are weak labels, not human gold.'},ensure_ascii=False))

if __name__=='__main__': main()
