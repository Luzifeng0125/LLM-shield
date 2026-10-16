"""Create an offline viewer with a few examples; training files remain separate."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def read(p): return [json.loads(s) for s in p.read_text(encoding='utf-8').splitlines() if s.strip()]
examples=[]
ner=read(ROOT/'ner/train.jsonl')
for cat in json.loads((ROOT/'stats.json').read_text(encoding='utf-8'))['categories']:
    row=next(r for r in ner if r['kind']=='single_entity' and r['entities'][0]['category']==cat)
    examples.append({**row,'kind':'实体识别','title':cat})
for kind in ('hard_negative','table','mixed_prose'):
    examples.append({**next(r for r in ner if r['kind']==kind),'kind':'实体识别','title':kind})
policy=read(ROOT/'policy/train.jsonl')
for action in ('DELETE','LOCAL_AGGREGATE','GENERALIZE','PSEUDONYMIZE','RETAIN','PAUSE'):
    examples.append({'kind':'动作决策','title':action,**next(r for r in policy if r['target']['preferred_action']==action)})
dialogs=read(ROOT/'dialogues/train.jsonl')
for scenario in dict.fromkeys(r['scenario'] for r in dialogs):
    examples.append({'kind':'多轮对话','title':scenario,**next(r for r in dialogs if r['scenario']==scenario)})
public=read(ROOT/'public/pii-bench-zh/external_test.jsonl')
for r in public[:2]+public[5000:5002]:
    examples.append({'kind':'公开数据','title':r['source_subset'],**r})

template='''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>隐盾数据集 · 离线预览</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f6f8f9;color:#192d3b;font-family:"Microsoft YaHei",sans-serif;line-height:1.7}
main{max-width:1100px;margin:auto;padding:36px 24px}h1{font-size:28px;margin:0}h2{font-size:20px}p{margin:10px 0}.muted{color:#5d6b73}
nav{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}button,select{font:inherit;border:1px solid #b8c9ce;border-radius:5px;padding:9px 14px;background:white;color:inherit;cursor:pointer}
button.active{background:#155f66;color:white;border-color:#155f66}.count{font-size:14px;color:#5d6b73}
section{border-top:1px solid #c9d6da;padding-top:18px;margin-top:20px}.text{white-space:pre-wrap;background:white;padding:18px;border-left:3px solid #155f66;overflow-wrap:anywhere}
mark{background:#d4efeb;color:inherit;padding:0 2px}mark small{font-size:10px;color:#245e61;margin-left:4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eaf0f2;padding:14px;font-size:13px}
details{margin-top:14px}summary{cursor:pointer}a{color:#155f66}.notice{background:#eaf0f2;padding:12px 16px;margin:18px 0}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
</style><main>
<h1>隐盾数据集 v1</h1><p class="muted">本地离线预览 · 2026-10-14 · 这里展示少量样本，完整数据在同目录 JSONL 文件中。</p>
<p>8,000 条公开中文样本 · 5,100 条专项实体样本 · 1,440 条动作样本 · 360 组三轮对话</p>
<div class="notice">全部来自公开合成数据或本项目程序构造；人工 gold 为 0。建议答案尚待复核。预览不会联网，也不会修改训练文件。</div>
<nav id="tabs"></nav><div class="toolbar"><select id="choose" aria-label="选择样本"></select><span class="count" id="position"></span></div>
<article id="content"></article>
<section><h2>从哪里开始</h2><p><a href="README.md">完整使用说明</a> · <a href="stats.json">数量与类别分布</a> · <a href="validation_report.json">数据完整性检查</a> · <a href="review/人工复核怎么做.md">两人复核计划</a></p><p class="muted">SFT 训练文件是原数据的格式转换，不应重复计算样本总量。多轮标注描述目标能力，不代表当前程序已全部实现。</p></section>
</main><script id="data" type="application/json">__DATA__</script><script>
const data=JSON.parse(document.querySelector('#data').textContent),types=[...new Set(data.map(x=>x.kind))];
let active=types[0];const choose=document.querySelector('#choose'),content=document.querySelector('#content');
function el(tag,text,parent){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(parent)parent.appendChild(e);return e;}
function marked(text,entities,parent){const box=el('div',undefined,parent);box.className='text';const chars=Array.from(text);let cursor=0;
for(const e of [...entities].sort((a,b)=>a.start-b.start)){box.appendChild(document.createTextNode(chars.slice(cursor,e.start).join('')));const m=el('mark',chars.slice(e.start,e.end).join(''),box);el('small',e.category,m);cursor=e.end;}box.appendChild(document.createTextNode(chars.slice(cursor).join('')));}
function details(title,obj,parent){const d=el('details',undefined,parent);el('summary',title,d);el('pre',JSON.stringify(obj,null,2),d);}
function show(){content.replaceChildren();const filtered=data.filter(x=>x.kind===active),r=filtered[Number(choose.value)];document.querySelector('#position').textContent=`此类预览 ${filtered.length} 个样本`;
el('h2',r.title,content);el('p',`${r.id} · ${r.source} · 待人工复核`,content).className='muted';
if(r.turns){for(const t of r.turns){const s=el('section',undefined,content);el('h2','第 '+t.turn_id+' 轮',s);marked(t.text,t.entities,s);details('展开本轮建议处理结果',t.target,s);details('展开此前实际发送的脱敏内容',t.prior_outbound,s);}}
else {if(r.task_description)el('p','任务：'+r.task_description,content);marked(r.text,r.entities,content);details('查看字符级实体标注',r.entities,content);if(r.target)details('查看建议动作与处理结果',r.target,content);}}
function load(){choose.replaceChildren();data.filter(x=>x.kind===active).forEach((r,i)=>{const o=el('option',r.title+' · '+r.id,choose);o.value=i;});document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.textContent===active));show();}
for(const type of types){const b=el('button',type,document.querySelector('#tabs'));b.onclick=()=>{active=type;load();};}choose.onchange=show;load();
</script></html>'''
(ROOT/'预览数据.html').write_text(template.replace('__DATA__',json.dumps(examples,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
print('Offline preview examples:',len(examples))
