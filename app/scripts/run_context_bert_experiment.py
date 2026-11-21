"""Local target-aware chunked BERT fine-tuning; validation-only epoch selection."""
from __future__ import annotations
import argparse,copy,json,math,os,random,re,sys,time
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
os.environ.setdefault('HF_HUB_OFFLINE','1');os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from torch import nn
from transformers import AutoModel,AutoTokenizer
from safetensors.torch import save_file,load_file
from sklearn.metrics import accuracy_score,f1_score,classification_report,confusion_matrix
from llm_shield.m4_necessity.context_bert import build_chunks
from llm_shield.m4_necessity.research import validate_review_provenance
from scripts.run_context_action_experiment import load,contrast
from scripts.run_natural_action_experiment import APP,sha,write_json
from scripts.build_context_review import ACTIONS

class ChunkClassifier(nn.Module):
    def __init__(self,base,context_contrast=False):
        super().__init__()
        self.encoder=AutoModel.from_pretrained(base,local_files_only=True,add_pooling_layer=False)
        for p in self.encoder.parameters():p.requires_grad=False
        for layer in self.encoder.encoder.layer[-4:]:
            for p in layer.parameters():p.requires_grad=True
        self.context_contrast=context_contrast
        dim=self.encoder.config.hidden_size*(3 if context_contrast else 1)
        self.head=nn.Sequential(nn.LayerNorm(dim),nn.Dropout(.15),nn.Linear(dim,len(ACTIONS)))
    def forward(self,inputs):
        outputs=self.encoder(**inputs).last_hidden_state[:,0,:]
        document=outputs.mean(dim=0,keepdim=True)
        if self.context_contrast:
            # Encode request/prior/target separately so the document cannot dilute them.
            mask=(inputs['token_type_ids'][0]==0)&inputs['attention_mask'][0].bool()
            prefix={k:v[0,mask].unsqueeze(0) for k,v in inputs.items()}
            prior=self.encoder(**prefix).last_hidden_state[:,0,:]
            document=torch.cat([document,prior,document*prior],dim=-1)
        return self.head(document)

def training_pairs(cases):
    pairs=defaultdict(list)
    for c in cases:
        if c['split']!='train':raise ValueError('Contrast training must use train-only grouped pairs')
        if c.get('context_pair_id'):pairs[(c['context_pair_id'],c['target'])].append(c)
    selected=[]
    for items in pairs.values():
        if len(items)!=2:raise ValueError('Controlled context pair must contain exactly two cases')
        a,b=items
        if a['scenario_group']!=b['scenario_group']:
            raise ValueError('Contrast training must use train-only grouped pairs')
        if a['text']!=b['text'] or a['task_description']!=b['task_description']:raise ValueError('Not a controlled context pair')
        positions=lambda c: sorted(c.get('target_occurrences',[m.start() for m in re.finditer(re.escape(c['target']),c['text'])]))
        if positions(a)!=positions(b):raise ValueError('Controlled context pair must select the same target occurrences')
        if a['annotation']['action']!=b['annotation']['action']:
            if a['context']==b['context']:raise ValueError('Different actions require different context in a controlled context pair')
            selected.append((a,b))
    return selected

def old_case(c):
    validate_review_provenance(c)
    prior,sep,body=c['context'].partition('\n\n【完整原始材料】\n')
    if not sep:raise ValueError('Old case lacks full original document separator')
    return {'case_id':c['case_id'],'document_id':c['document_id'],'split':c['split'],
        'scenario_group':c['template_group'],'task_description':c['task_description'],
        'context':prior,'text':body,'target':c['text'],'annotation':c['annotation']}

def batch(chunks,tokenizer,device):
    return tokenizer.pad(chunks,padding=True,return_tensors='pt').to(device)

@torch.inference_mode()
def evaluate(model,cases,encoded,tokenizer,device):
    model.eval();rows=[]
    for case in cases:
        inputs=batch(encoded[case['case_id']],tokenizer,device)
        with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=device.type=='cuda'):
            logits=model(inputs)
        probs=logits.float().softmax(-1)[0].cpu().tolist();pred=ACTIONS[int(np.argmax(probs))];expected=case['annotation']['action']
        rows.append({'case_id':case['case_id'],'document_id':case['document_id'],'expected':expected,'predicted':pred,
            'correct':pred==expected,'scores':dict(zip(ACTIONS,probs))})
    truth=[r['expected'] for r in rows];pred=[r['predicted'] for r in rows]
    grouped={cid:[r['correct'] for r in rows if r['document_id']==cid] for cid in {r['document_id'] for r in rows}}
    return {'n':len(rows),'correct':sum(r['correct'] for r in rows),'accuracy':float(accuracy_score(truth,pred)),
        'macro_f1':float(f1_score(truth,pred,labels=ACTIONS,average='macro',zero_division=0)),
        'class_report':classification_report(truth,pred,labels=ACTIONS,output_dict=True,zero_division=0),
        'confusion':{'true_rows_predicted_columns':ACTIONS,'counts':confusion_matrix(truth,pred,labels=ACTIONS).tolist()},
        'all_targets_correct_documents':sum(all(v) for v in grouped.values()),'documents':len(grouped),'rows':rows}

def run(pack,old_path,base,out,epochs,context_contrast=False):
    if out.exists():raise ValueError('Use a new experiment directory')
    if sha(base/'model.safetensors')!='3404a1ffd8da507042e8161013ba2a4fc49858b4e3f8fbf5ce5724f94883aec3':raise ValueError('Unexpected pretrained weight fingerprint')
    new=load(pack/'cases.jsonl');old=[old_case(c) for c in load(old_path)]
    parts={s:[c for c in new if c['split']==s] for s in ['train','validation','test']}
    oldparts={s:[c for c in old if c['split']==s] for s in ['train','validation','test']}
    watched=[pack/'cases.jsonl',pack/'documents.jsonl',old_path,base/'model.safetensors',APP/'models/necessity_action.joblib',APP/'models/ACTIVE_MODELS.json']
    hashes={str(p):sha(p) for p in watched}
    tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True)
    encoded={};coverage={}
    for c in new+old:
        encoded[c['case_id']],coverage[c['case_id']]=build_chunks(c,tokenizer)
    conditions={'new_only':parts['train'],'mixed':oldparts['train']+parts['train']}
    device=torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    protocol={'schema':'context-bert-finetune-v1','at_utc':datetime.now(timezone.utc).isoformat(),
        'base_model':'google-bert/bert-base-chinese','base_weight_sha256':hashes[str(base/'model.safetensors')],
        'model_card':'https://huggingface.co/google-bert/bert-base-chinese','epochs':epochs,'learning_rate':3e-5,
        'weight_decay':.01,'gradient_accumulation':4,'seed':42,'trainable_encoder_layers':'last_four',
        'pooling':'unweighted_mean_valid_chunk_CLS_per_decision','max_tokens_per_chunk':512,'overlap':32,
        'separate_prefix_encoding':context_contrast,'context_pair_loss_weight':.5 if context_contrast else 0,
        'context_pair_loss':'softplus(1-(logit_a[ya]-logit_a[yb]+logit_b[yb]-logit_b[ya])/2)',
        'cross_chunk_token_attention':False,'class_weighting':'inverse_training_frequency',
        'loss_weighting':'one_per_annotated_decision_not_document','gold_entity_type_features':False,
        'target_positions':'provided_not_detector_evaluation','selection':'new_validation_macro_f1_then_accuracy_then_earlier_epoch',
        'development_scope':'previously_used_synthetic_development_not_independent_blind_test',
        'new_labels':'machine_draft','old_labels':'human_assisted_second_reviewed',
        'device':str(device),'device_name':torch.cuda.get_device_name(0) if device.type=='cuda' else 'CPU',
        'training_cases':{k:[c['case_id'] for c in v] for k,v in conditions.items()},
        'validation_cases':[c['case_id'] for c in parts['validation']],
        'development_cases':[c['case_id'] for c in parts['test']],
        'inputs_before':hashes,'production_promoted':False,
        'code_hashes':{str(p.relative_to(APP)):sha(p) for p in [Path(__file__),APP/'llm_shield/m4_necessity/context_bert.py']}}
    out.mkdir(parents=True);write_json(out/'protocol_before_fit.json',protocol);write_json(out/'token_coverage.json',coverage)
    selected={};histories={};started=time.perf_counter()
    for name,cases in conditions.items():
        random.seed(42);np.random.seed(42);torch.manual_seed(42)
        if device.type=='cuda':torch.cuda.manual_seed_all(42)
        model=ChunkClassifier(base,context_contrast).to(device)
        trainable=[p for p in model.parameters() if p.requires_grad]
        optimizer=torch.optim.AdamW(trainable,lr=protocol['learning_rate'],weight_decay=.01)
        counts=Counter(c['annotation']['action'] for c in cases)
        if set(counts)!=set(ACTIONS):raise ValueError('Training lacks a class')
        weights=torch.tensor([len(cases)/(len(ACTIONS)*counts[a]) for a in ACTIONS],dtype=torch.float32,device=device)
        criterion=nn.CrossEntropyLoss(weight=weights,reduction='sum')
        pairs=training_pairs(cases) if context_contrast else []
        total_steps=epochs*(math.ceil(len(cases)/4)+len(pairs));step=0;best=(-1.,-1.);history=[]
        path=out/f'{name}_trainable.safetensors'
        for epoch in range(1,epochs+1):
            model.train();order=list(cases);random.Random(42+epoch).shuffle(order)
            optimizer.zero_grad(set_to_none=True);losses=[];epoch_started=time.perf_counter()
            for i,c in enumerate(order):
                inputs=batch(encoded[c['case_id']],tokenizer,device)
                truth=torch.tensor([ACTIONS.index(c['annotation']['action'])],device=device)
                group_size=min(4,len(order)-(i//4)*4)
                with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=device.type=='cuda'):
                    logits=model(inputs);loss=criterion(logits.float(),truth)/group_size
                loss.backward();losses.append(float(loss.detach())*group_size)
                if (i+1)%4==0 or i+1==len(order):
                    torch.nn.utils.clip_grad_norm_(trainable,1.)
                    warmup=max(1,int(total_steps*.1));factor=min((step+1)/warmup,max(0.,(total_steps-step)/max(1,total_steps-warmup)))
                    for group in optimizer.param_groups:group['lr']=protocol['learning_rate']*factor
                    optimizer.step();optimizer.zero_grad(set_to_none=True);step+=1
            contrast_losses=[]
            for a,b in pairs:
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast(device_type=device.type,dtype=torch.bfloat16,enabled=device.type=='cuda'):
                    la=model(batch(encoded[a['case_id']],tokenizer,device)).float()[0]
                    lb=model(batch(encoded[b['case_id']],tokenizer,device)).float()[0]
                    ya,yb=ACTIONS.index(a['annotation']['action']),ACTIONS.index(b['annotation']['action'])
                    loss=.5*torch.nn.functional.softplus(1-(la[ya]-la[yb]+lb[yb]-lb[ya])/2)
                loss.backward();torch.nn.utils.clip_grad_norm_(trainable,1.)
                warmup=max(1,int(total_steps*.1));factor=min((step+1)/warmup,max(0.,(total_steps-step)/max(1,total_steps-warmup)))
                for group in optimizer.param_groups:group['lr']=protocol['learning_rate']*factor
                optimizer.step();optimizer.zero_grad(set_to_none=True);step+=1
                contrast_losses.append(float(loss.detach()))
            val=evaluate(model,parts['validation'],encoded,tokenizer,device)
            record={'epoch':epoch,'train_loss_mean':sum(losses)/len(losses),'contrast_pairs':[[a['case_id'],b['case_id']] for a,b in pairs],
                'contrast_loss_mean':sum(contrast_losses)/len(contrast_losses) if contrast_losses else None,
                'seconds':time.perf_counter()-epoch_started,'validation':val}
            history.append(record);key=(val['macro_f1'],val['accuracy'])
            if key>best:
                best=key;names={n for n,p in model.named_parameters() if p.requires_grad}
                save_file({k:v.detach().cpu().contiguous() for k,v in model.state_dict().items() if k in names},str(path))
                selected[name]={'epoch':epoch,'validation':val,'checkpoint':path.name,'sha256':sha(path),'trainable_parameters':sum(p.numel() for p in trainable)}
            write_json(out/f'{name}_history.json',history)
            print(json.dumps({'condition':name,'epoch':epoch,'loss':record['train_loss_mean'],'validation_correct':val['correct'],'validation_n':val['n'],'macro_f1':val['macro_f1'],'seconds':record['seconds']},ensure_ascii=False),flush=True)
        histories[name]=history;del model,optimizer
        if device.type=='cuda':torch.cuda.empty_cache()
    write_json(out/'selection_before_development.json',{'selected':selected,'at_utc':datetime.now(timezone.utc).isoformat()})
    preferred=max(selected,key=lambda n:(selected[n]['validation']['macro_f1'],selected[n]['validation']['accuracy']))
    results={}
    for name,s in selected.items():
        model=ChunkClassifier(base,context_contrast).to(device);model.load_state_dict(load_file(str(out/s['checkpoint'])),strict=False)
        full=evaluate(model,parts['test'],encoded,tokenizer,device)
        ablations={}
        for mode in ['no_prior','no_context','target_only']:
            ablated={c['case_id']:build_chunks(c,tokenizer,ablation=mode)[0] for c in parts['test']}
            ablations[mode]=evaluate(model,parts['test'],ablated,tokenizer,device)
        results[name]={'development':full,'context_pairs':contrast(parts['test'],full),
            'old_development':evaluate(model,oldparts['test'],encoded,tokenizer,device),'ablations':ablations}
        del model
        if device.type=='cuda':torch.cuda.empty_cache()
    after={p:sha(Path(p)) for p in hashes}
    if after!=hashes:raise RuntimeError('Input/active model changed')
    report={'protocol':protocol,'selected':selected,'preferred_by_validation':preferred,'results':results,
        'elapsed_seconds':time.perf_counter()-started,'inputs_after':after,'active_unchanged':True}
    write_json(out/'report.json',report)
    print(json.dumps({'finished':True,'preferred_by_validation':preferred,'results':{k:{f:v['development'][f] for f in ['n','correct','accuracy','macro_f1']} for k,v in results.items()}},ensure_ascii=False),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pack',type=Path,required=True);p.add_argument('--old-confirmed',type=Path,required=True)
    p.add_argument('--base',type=Path,default=APP.parent/'runtime/base_models/bert_base_chinese');p.add_argument('--out',type=Path,required=True);p.add_argument('--epochs',type=int,default=6)
    p.add_argument('--context-contrast',action='store_true')
    a=p.parse_args();run(a.pack,a.old_confirmed,a.base,a.out,a.epochs,a.context_contrast)
