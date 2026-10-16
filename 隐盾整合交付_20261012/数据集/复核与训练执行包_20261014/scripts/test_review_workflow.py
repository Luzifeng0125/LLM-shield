"""Software fixtures only; no output is a real human annotation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import review_workflow as rw


class WorkflowTests(unittest.TestCase):
    def test_bulk_audit_and_legacy_progress(self):
        batch='01_训练试标'
        rows=rw.read(rw.ROOT/'批次'/batch/'复核员A/空白复核表.jsonl')
        with tempfile.TemporaryDirectory(prefix='review_audit_fixture_') as tmp:
            path=Path(tmp)/'progress.jsonl'
            rw.write(path,rows)
            rw.validate_forms(path,batch,'A',require_complete=False)
            rows[0]['reviewed']=True
            event={'action':'approve','method':'batch','reviewer':'A',
                   'at':'2026-10-15T03:04:05.123Z','batch_id':'SOFTWARE_TEST_BATCH'}
            rows[0]['review_audit']=[event]
            approved=Path(tmp)/'approved.jsonl';rw.write(approved,rows)
            rw.validate_forms(approved,batch,'A',require_complete=False)
            for key,value in [('reviewer','B'),('at','2026-02-30T03:04:05.123Z'),
                              ('batch_id',''),('action','reopen'),('method','edit')]:
                with self.subTest(key=key):
                    bad=copy.deepcopy(rows);bad[0]['review_audit'][0][key]=value
                    invalid=Path(tmp)/f'bad_{key}.jsonl';rw.write(invalid,bad)
                    with self.assertRaises(ValueError):rw.validate_forms(invalid,batch,'A',require_complete=False)
            rows[0]['reviewed']=False
            rows[0]['review_audit'].append({**event,'action':'reopen'})
            rw.validate_review_audit(rows[0])

    def test_unicode_and_bounds(self):
        rw.entities('😀小王', [{'start':1,'end':3,'text':'小王','category':'PERSON_NAME'}])
        with self.assertRaises(ValueError):rw.entities('😀小王',[{'start':2,'end':4,'text':'小王','category':'PERSON_NAME'}])
        with self.assertRaises(ValueError):rw.entities('小王',[{'start':0,'end':2,'text':'小王','category':'PHONE'},{'start':1,'end':2,'text':'王','category':'PERSON_NAME'}])

    def test_pause_contract(self):
        t={'preferred_action':'PAUSE','acceptable_actions':['PAUSE'],'send_allowed':False,'sanitized_text':None,'reason':'fixture'}
        rw.target(t)
        for key,value in [('send_allowed',True),('sanitized_text','private'),('acceptable_actions',['PAUSE','RETAIN'])]:
            bad=dict(t);bad[key]=value
            with self.assertRaises(ValueError):rw.target(bad)

    def test_batches_are_separate_and_blind(self):
        all_ids=set();counts=[]
        for batch in sorted((rw.ROOT/'批次').iterdir()):
            a=rw.read(batch/'复核员A/空白复核表.jsonl');b=rw.read(batch/'复核员B/空白复核表.jsonl')
            self.assertEqual([r['id'] for r in a],[r['id'] for r in b]);counts.append(len(a))
            ids={r['id'] for r in a};self.assertFalse(ids & all_ids);all_ids |= ids
            for r in a:
                self.assertFalse(r['reviewed']);self.assertNotIn('template_family',r);self.assertNotIn('target',r)
                self.assertNotIn('prior_outbound',r)
        self.assertEqual(counts,[128,92,92])

    def test_complete_comparison_and_export_gate(self):
        batch='01_训练试标';base=rw.read(rw.ROOT/'批次'/batch/'复核员A/空白复核表.jsonl')
        source=rw.index(rw.read(rw.ROOT/'裁决员专用'/batch/'机器建议勿提前给AB.jsonl'))
        def clean_entities(es):return [{k:e[k] for k in ['start','end','text','category']} for e in es]
        def make_target(t):return {**t,'acceptable_actions':t.get('acceptable_actions',[t['preferred_action']])}
        for r in base:
            s=source[r['id']];r['reviewed']=True
            r['review_audit']=[{'action':'approve','method':'batch','reviewer':'A',
                                'at':'2026-10-15T03:04:05.123Z','batch_id':'TEST_A'}]
            if r['kind']=='dialogue':
                r['annotation']={'turns':[{'turn_id':t['turn_id'],'entities':clean_entities(t['entities']),'target':make_target(t['target'])} for t in s['turns']]}
            else:
                r['annotation']={'entities':clean_entities(s['entities'])}
                if r['kind']=='policy':r['annotation']['target']=make_target(s['target'])
        with tempfile.TemporaryDirectory(prefix='review_software_fixture_') as tmp:
            root=Path(tmp);a=root/'a.jsonl';b=root/'b.jsonl';rw.write(a,base)
            other=copy.deepcopy(base)
            for r in other:
                r['reviewer']='B'
                r['review_audit'][0].update(reviewer='B',batch_id='TEST_B')
            other[0]['annotation']['entities']=[];rw.write(b,other)
            rw.compare(a,b,batch,root/'comparison')
            stats=json.loads((root/'comparison/比较统计.json').read_text(encoding='utf-8'))
            self.assertEqual(stats['disagreements'],1);self.assertEqual(stats['scored_excluding_calibration'],120)
            decisions=root/'comparison/裁决表.jsonl'
            with self.assertRaises(ValueError):rw.export_gold(a,b,batch,decisions,root/'gold.jsonl')
            ds=rw.read(decisions)
            for d in ds:
                d.update(approved=True,adjudicator='SOFTWARE_TEST_NOT_HUMAN',adjudicated_date='2026-10-14',adjudication_reason='SOFTWARE FIXTURE ONLY',final_annotation=d['annotation_A'])
            approved=root/'approved_fixture.jsonl';rw.write(approved,ds)
            rw.export_gold(a,b,batch,approved,root/'gold.jsonl')
            exported=rw.read(root/'gold.jsonl')
            self.assertEqual(len(exported),128)
            self.assertEqual(exported[0]['review_audit'],{'A':base[0]['review_audit'],'B':other[0]['review_audit']})
            tampered=copy.deepcopy(base);tampered[0]['text']='modified';rw.write(root/'tampered.jsonl',tampered)
            with self.assertRaises(ValueError):rw.validate_forms(root/'tampered.jsonl',batch,'A')
            incomplete=copy.deepcopy(base);incomplete[0]['reviewed']=False;rw.write(root/'incomplete.jsonl',incomplete)
            with self.assertRaises(ValueError):rw.compare(root/'incomplete.jsonl',b,batch,root/'should_not_exist')


if __name__=='__main__':unittest.main()
