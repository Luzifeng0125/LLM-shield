'use strict';
const el = id => document.getElementById(id);
const names = {active:'默认动作模型',campus_candidate:'早期校园候选',aligned:'对齐候选',task:'任务需求候选',context:'上下文增强候选'};
const configs = {format_regex:'格式正则（只评格式类）',rules_baseline:'正则＋词典基线（全部类别）',gliner_semantic:'官方 GLiNER（只评五类语义实体）',fused:'正则＋词典＋官方 GLiNER（全部类别）'};
const categories = {PERSON_NAME:'姓名',ORG:'组织',LOCATION:'地点',DORM:'宿舍',SENSITIVE_ATTR:'敏感属性',PHONE:'电话',EMAIL:'邮箱',STUDENT_ID:'学号',ID_CARD:'证件号',BANK_CARD:'银行卡',API_KEY:'密钥',WECHAT:'社交账号',BUDGET:'预算金额',GRADE:'成绩'};
const pct = value => `${(value*100).toFixed(1)}%`;
const count = value => `${value.passed} / ${value.total}`;
let payload;
function rows(id, values) {
  el(id).replaceChildren();
  for (const cells of values) {
    const row = document.createElement('tr');
    for (const value of cells) { const cell=document.createElement('td');cell.textContent=String(value);row.append(cell); }
    el(id).append(row);
  }
}
function showNer() {
  const config=payload.report.ner.configurations[el('nerConfig').value];
  const mode=config.modes[el('nerMode').value], total=mode.overall;
  el('nerTotals').textContent=`精确率 ${pct(total.precision)} · 召回率 ${pct(total.recall)} · 微平均 F1 ${total.f1.toFixed(4)} · P50 ${config.latency.p50_ms} ms / P95 ${config.latency.p95_ms} ms`;
  rows('nerRows',Object.entries(mode.per_category).map(([cat,value])=>[categories[cat]||cat,pct(value.precision),pct(value.recall),value.f1.toFixed(4),value.tp,value.fp,value.fn]));
}
function render(data) {
  payload=data;
  const current=data.runtime;
  const profile={project_gliner_v3:'项目微调配置','official_multi_v2.1':'官方 GLiNER 对照配置',custom_local_model:'自定义本地配置'}[current.gliner_profile];
  el('runtime').textContent=`当前服务：${profile} · 实体识别${current.recognizer_ready?'已就绪':'未就绪'} · 必要性模型${current.action_model_ready?'已就绪':'未就绪'}（特征 v${current.action_feature_version||'未知'}） · ${current.llm_mode==='mock'?'模拟生成':'生成服务尚需按本轮调用结果确认'}。`;
  if(!data.report_available){el('reportSource').textContent='此副本尚未生成阶段评测文件，请先运行本地分阶段评测脚本。';return;}
  const report=data.report, config=report.ner.configurations;
  const measured=report.ner.documents;
  el('reportSource').textContent=`评测时间：${new Intl.DateTimeFormat('zh-CN',{dateStyle:'medium',timeStyle:'short',timeZone:'Asia/Shanghai'}).format(new Date(report.created_utc))}（北京时间）。下方实测使用官方 GLiNER 对照权重，当前服务配置单独显示。`;
  el('report').hidden=false;
  const active=report.necessity.models.find(item=>item.id==='active');
  const highlights=[['融合识别 · 严格微 F1',config.fused.modes.strict.overall.f1.toFixed(4)],['诊断目标被识别',`${report.necessity.target_detected} / ${report.necessity.n}`],['默认必要性 · 给定实体',`${active.constrained_correct} / ${active.n}`],['硬约束合成样例',count(report.safeguards.constraints)]];
  for(const [label,value] of highlights){const item=document.createElement('div');item.className='highlight';const strong=document.createElement('strong');strong.className='value';strong.textContent=value;const small=document.createElement('span');small.className='label';small.textContent=label;item.append(strong,small);el('highlights').append(item);}
  const weak=config.fused.modes.strict.per_category;
  for(const cat of ['SENSITIVE_ATTR','DORM','LOCATION','ORG']){const value=weak[cat];if(!value)continue;const li=document.createElement('li');li.textContent=`${categories[cat]}：严格召回 ${value.tp}/${value.tp+value.fn}，误报 ${value.fp}，F1 ${value.f1.toFixed(4)}`;el('weaknesses').append(li);}
  rows('stageRows',[
    ['01 材料解析','7种格式各1份合成文件',count(report.parsing),'只验证基本文本/表格提取；不含扫描PDF/OCR'],
    ['02 格式识别','格式类实体：正则与校验位',`严格 F1 ${config.format_regex.modes.strict.overall.f1.toFixed(4)}`,'号码与金额类；不含语义类实体'],
    ['03 语义识别','官方GLiNER：姓名/组织/地点/宿舍/敏感属性',`严格 F1 ${config.gliner_semantic.modes.strict.overall.f1.toFixed(4)}`,`真实${report.environment.device==='cuda'?'GPU':'CPU'}推理；官方模型，不是原微调版本`],
    ['04 融合与分段',`${measured}篇既有开发基准`,`严格 F1 ${config.fused.modes.strict.overall.f1.toFixed(4)}；归属 ${count(report.ner.segmentation)}`,'实体边界与分段归属分别计量'],
    ['05 必要性判断','24条合成诊断；给定参考片段',`默认模型 ${active.constrained_correct} / ${active.n}`,'另列真实识别后动作匹配，漏检计失败'],
    ['06 硬约束','强制指定模型动作，检查允许或暂停',count(report.safeguards.constraints),'测试动作拒绝机制；不代表任意输入都安全'],
    ['07 脱敏转换','六类动作的受控执行样例',count(report.safeguards.transformation),'检查执行语义；动作由测试指定，不代表模型选择准确'],
    ['08 完整性自检','规则检查完整/缺项/不适用',count(report.safeguards.utility),'规则自检不能代替人工核对任务是否完成'],
    ['09 出入站边界','三类接收方的泄露及干净样例',count(report.safeguards.boundaries),'实测本地载荷复检，不进行外部发布'],
    ['10 真实云端生成','本轮未调用','未测试','不能据此宣称真实生成质量或云端整链路已验证']
  ]);
  el('nerScope').textContent=`数据：${report.ner.dataset}，${measured}篇、${report.ner.gold_entities}个参考实体。该集合已用于开发，本次结果不属于新的独立盲测。`;
  for(const [value,label] of Object.entries(configs)){const option=document.createElement('option');option.value=value;option.textContent=label;el('nerConfig').append(option);}
  el('nerConfig').value='fused';showNer();
  rows('policyRows',report.necessity.models.map(item=>[names[item.id]||item.id,item.feature_version,`${item.raw_correct}/${item.n}`,`${item.constrained_correct}/${item.n}`,item.macro_f1_six_actions.toFixed(4),`${item.detected_chain_correct}/${item.n}`,`${item.mean_decision_ms} ms`]));
  rows('historyRows',report.historical_human31.models.map(item=>[names[item.id]||item.id,`${item.correct}/${item.n}`,item.macro_f1.toFixed(4)]));
  for(const text of report.limitations){const li=document.createElement('li');li.textContent=text;el('limitations').append(li);}
  const env=report.environment;
  for(const [label,value] of [['识别模型','urchade/gliner_multi-v2.1，固定版本 443d26d654e0324125a96bebd8e796c14ff2efe6'],['权重 SHA-256',env.official_weight_sha256],['测试设备',`${env.gpu||'CPU'} / ${env.device}`],['GLiNER冷加载',`${env.gliner_load_ms} ms`],['依赖版本',Object.entries(env.packages).map(([k,v])=>`${k} ${v}`).join('；')],['识别基准 SHA-256',report.ner.sha256],['合成诊断 SHA-256',report.necessity.sha256]]){const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');dd.textContent=value;el('environment').append(dt,dd);}
}
el('nerConfig').addEventListener('change',showNer);el('nerMode').addEventListener('change',showNer);
el('download').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='LLM-Shield-stage-evaluation.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
fetch('/api/evaluation').then(response=>{if(!response.ok)throw Error('无法读取评测数据');return response.json();}).then(render).catch(error=>{el('error').hidden=false;el('error').textContent=error.message;});
