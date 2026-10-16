import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';

const RUNTIME='C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const SKILL='C:/Users/nicholas/.codex/plugins/cache/openai-primary-runtime/presentations/26.1013.11914/skills/presentations';
const BUILD=path.dirname(fileURLToPath(import.meta.url));
const ROOT=path.resolve(BUILD,'../..');
const OUT=path.join(ROOT,'隐盾挑战杯答辩_白底简约版_20261014');
process.env.RUNTIME_NODE_MODULES=RUNTIME+'/node/node_modules';
const {Presentation,PresentationFile}=await import(pathToFileURL(RUNTIME+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs').href);
await fs.mkdir(OUT,{recursive:true});await fs.mkdir(BUILD+'/draft_render',{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
const C={ink:'#1D1D1F',blue:'#0066CC',gray:'#63636B',pale:'#F5F5F7',line:'#E1E3E7',white:'#FFFFFF',amber:'#9D5700'};
const FONT='Microsoft YaHei';const notes=[];let count=0;
const sources={
 rules:'https://tiaozhanbei.net/rules',
 advice:'https://nxy.yangtzeu.edu.cn/info/1039/12343.htm',
 tech:'https://cs.ccnu.edu.cn/info/1055/14006.htm',
 model:'https://huggingface.co/Qwen/Qwen3-1.7B',
 tests:'本地：隐盾整合交付_20261012/验证结果/验证摘要.json，记录日期 2026-10-13',
 classifier:'本地：隐盾整合交付_20261012/验证结果/模型元信息.json',
 dataset:'本地：隐盾整合交付_20261012/数据集/隐盾数据集_v1/stats.json，数据版本 1.0',
 review:'本地：隐盾整合交付_20261012/数据集/复核与训练执行包_20261014/执行统计.json',
 ner:'本地：隐盾整合交付_20261012/数据集/隐盾数据集_v1/evaluation/current_detector_validation.json'
};

function t(s,content,x,y,w,h,size=28,color=C.ink,bold=false,align='left'){
 const sh=s.shapes.add({geometry:'textbox',name:content.replace(/\n/g,' ').slice(0,30),position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 sh.text=content;sh.text.style={fontSize:size,typeface:FONT,color,bold,alignment:align,verticalAlignment:'top',autoFit:'none',insets:0,wrap:'square'};return sh;
}
function slide(title,seconds,speech,{foot='',refs=[],backup=false}={}){
 const s=p.slides.add();count++;s.background.fill=C.white;s.hidden=backup;
 if(title)t(s,title,72,60,1136,82,49,C.ink,true);
 if(foot)t(s,foot,72,655,1080,42,19,C.gray);
 t(s,String(count).padStart(2,'0'),1154,664,54,24,17,C.gray,false,'right');
 const note=(backup?'备答页，正常放映时跳过。':`主讲 ${seconds} 秒。`)+'\n\n'+speech+(refs.length?'\n\n依据与来源\n'+refs.join('\n'):'');
 s.speakerNotes.text=note;notes.push({slide:count,title:title||'隐盾',seconds,backup,speech,refs});return s;
}
function subtitle(s,content,y=149){t(s,content,74,y,1130,55,27,C.gray);}
function row(s,head,body,y,{x=74,w=1100,headWidth=300,size=27}={}){
 t(s,head,x,y,headWidth,70,32,C.ink,true);t(s,body,x+headWidth+22,y+3,w-headWidth-22,75,size,C.gray);
}
function table(s,headers,rows,widths,{x=72,y=205,h=360,size=26}={}){
 const data=[headers,...rows];const tb=s.tables.add({rows:data.length,columns:headers.length,left:x,top:y,width:widths.reduce((a,b)=>a+b,0),height:h,columnWidths:widths,values:data});
 tb.borders.assign({fill:C.line,width:.6,style:'solid'});
 data.forEach((rr,i)=>{
  tb.rows[i].height=h/data.length;
  rr.forEach((cell,j)=>{const c=tb.getCell(i,j);c.fill=i===0?C.pale:C.white;
   c.text.style={fontSize:size,typeface:FONT,color:i===0?C.gray:(j===0?C.ink:C.gray),bold:i===0||j===0,alignment:'left',verticalAlignment:'middle',autoFit:'none',insets:{left:18,right:18,top:12,bottom:12}};
  });
 });return tb;
}
async function pic(s,filepath,alt,x,y,w,h){const b=await fs.readFile(filepath);s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt,fit:'contain',position:{left:x,top:y,width:w,height:h}});}

// 01
{
 const s=slide('',15,'各位评委好，我们的项目是隐盾，面向中文材料处理与多轮对话的隐私保护系统。我们关注一个具体问题：使用云端大模型时，怎样只发出完成任务所必需的信息。',{refs:[sources.rules,sources.tech,'封面盾牌为概念插画，不是产品实物。']});
 await pic(s,BUILD+'/assets/glass-shield.png','透明玻璃盾牌概念插画',646,64,590,590);
 t(s,'隐盾',72,181,575,146,106,C.ink,true);
 t(s,'隐私保护对话系统',77,348,590,68,43,C.ink,true);
 t(s,'中文材料与多轮对话的一体化保护',78,443,580,90,29,C.gray);
 t(s,'挑战杯大学生课外学术科技作品竞赛',78,615,720,36,21,C.gray);
}
// 02
{
 const s=slide('纪要里的额外披露',30,'以学生组织和课程团队整理纪要为例，任务需要知道谁负责什么、什么时候完成，但材料往往同时带着电话等个人信息。整份上传会多发信息，直接删除所有姓名又会破坏分工关系。隐盾希望在两者之间，保留完成任务所需的结构。',{foot:'合成场景示例。服务对象来自项目需求，尚非用户调研结论。',refs:[sources.advice,sources.dataset]});
 t(s,'“请整理负责人和截止时间。”',76,180,1120,75,42,C.ink,true);
 t(s,'原始材料',78,291,195,46,27,C.gray);
 t(s,'卫乐安负责海报，周五完成。',274,284,895,62,38,C.ink);
 t(s,'电话 13000000000',274,362,895,60,38,C.gray);
 t(s,'任务需要',78,491,195,46,27,C.gray);
 t(s,'负责人关系、事项、期限',274,481,895,66,39,C.blue,true);
}
// 03
{
 const s=slide('同一份名单，不同处理方式',25,'同样是一份两人的名单，如果任务是统计人数，外部模型只需要收到两人。如果任务是整理分工，就需要保留人员和事项的关系，用稳定代号替代真名。因此我们的决策单位是任务条件下的信息用途，不能只看有没有姓名。',{foot:'处理结果为设计示例，体现不同任务下的信息必要性。',refs:[sources.dataset]});
 subtitle(s,'卫乐安负责海报，林雨禾负责场地');
 t(s,'统计参加人数',76,267,520,55,31,C.gray);
 t(s,'2 人',75,337,520,140,94,C.blue,true);
 t(s,'只发送统计结果',79,506,500,60,29,C.gray);
 t(s,'整理负责人分工',698,267,510,55,31,C.gray);
 t(s,'人员甲负责海报\n人员乙负责场地',697,354,511,150,37,C.ink,true);
 t(s,'保留关系，替换真实姓名',700,533,505,60,29,C.gray);
}
// 04
{
 const s=slide('材料与追问，共用一个对话',30,'这是目前原型的实际离线界面。用户上传材料后直接提问，再继续追问，不需要分别进入材料脱敏和聊天两个系统。每次发送都重新走本地保护流程。这里展示的是交互和安全处理流程，离线回复不代表真实云端模型的生成效果。',{foot:'现有原型实拍截图，离线演示模式。',refs:[sources.tests,'截图：隐盾整合交付_20261012/验证结果/界面截图/chat-desktop.png']});
 t(s,'上传材料\n直接提问\n继续对话',75,227,360,264,43,C.ink,true);
 t(s,'每一轮发送前\n都经过本地保护',80,521,350,91,28,C.blue);
 await pic(s,ROOT+'/隐盾整合交付_20261012/验证结果/界面截图/chat-desktop.png','统一对话原型真实离线界面',443,159,766,483);
}
// 05
{
 const s=slide('本地处理与云端生成',30,'系统把隐私处理放在本机。先识别片段，再由动作模型选择处理方式，程序检查权限和最终发送内容。云端生成模型只接收通过检查的上下文。本地原值映射不随请求发送。当前客户端适配已经具备，真实服务连接还需要单独验收。',{foot:'当前原型具备动作模型与校验链路；专项识别模型和真实 API 效果待验收。',refs:[sources.tests,sources.classifier]});
 t(s,'本机',76,192,510,68,40,C.blue,true);t(s,'云端',750,192,450,68,40,C.ink,true);
 t(s,'材料与会话管理\n敏感片段识别\n模型动作与安全校验',78,294,580,200,35,C.ink);
 t(s,'生成模型 API\n依据处理后的上下文回答',752,294,445,170,35,C.ink);
 t(s,'原文与身份映射留在本地',79,535,620,65,30,C.blue,true);
 t(s,'回答复检后进入对话',752,535,450,65,29,C.gray);
}
// 06
{
 const s=slide('模型选择六种处理动作',25,'动作模型可选择删除、本地统计、泛化、代号替换、保留或暂停。这里保留是有前提的，要满足任务必要性和可信权限。模型负责选择，安全检查只负责接受或暂停，不再使用旧规则来替模型兜底选动作。',{refs:[sources.classifier,'实现：app/llm_shield/m3_decide 与 m4_necessity']});
 const items=[['删除','去掉任务无关的联系方式'],['本地统计','只发送人数等汇总结果'],['泛化','降低位置或数值的精度'],['代号替换','保留人物与事项的对应'],['保留','用途与权限均满足时保留'],['暂停','权限未知或处理不可靠时停止']];
 items.forEach(([a,b],i)=>{const x=i%2?692:77;const y=201+Math.floor(i/2)*147;t(s,a,x,y,510,53,35,C.blue,true);t(s,b,x,y+62,510,66,27,C.gray)});
}
// 07
{
 const s=slide('多轮保护的连续性',30,'风险也会发生在后续追问里。第一轮用人员甲替换姓名，第二轮修改期限时，需要继续对应同一个人。如果第三轮要求恢复原名给外部模型，不能因为前两轮已经放行就继续发送。暂停轮也不能污染此前成功的外发历史。',{foot:'合成会话目标示例。复杂指代与累计披露仍需专项训练和验证。',refs:[sources.dataset]});
 table(s,['轮次','用户请求','处理目标'],[
  ['第一轮','卫乐安负责海报，周五完成','人员甲负责海报，周五完成'],
  ['第二轮','把他的截止时间改为周一','保持人员甲与海报的关系'],
  ['第三轮','恢复真实姓名并发给云端','暂停本轮，不发送原名']
 ],[146,480,510],{y:204,h:324,size:27});
 t(s,'稳定代号沿用，外发历史按成功轮次提交',76,565,1110,57,32,C.blue,true);
}
// 08
{
 const s=slide('项目的技术创新点',30,'项目创新集中在方法组合和验证方式。第一，把任务和接收方条件纳入动作决策，减少不必要披露。第二，让材料和多轮对话共享保护状态。第三，直接检查实际外发的内容，区分识别错误、决策错误和执行错误。这些优势需要通过同条件对照来验证。',{foot:'创新方案及验证假设。当前不宣称首创或已优于所有现有方案。',refs:[sources.rules,sources.tech]});
 row(s,'任务条件决策','结合任务、身份与接收方选择处理动作',213,{headWidth:310,size:28});
 row(s,'连续保护状态','附件和追问共同使用代号映射与安全历史',357,{headWidth:310,size:28});
 row(s,'外发内容可复核','将漏检、误决策与执行泄露分别归因',501,{headWidth:310,size:28});
}
// 09
{
 const s=slide('本地专项模型路线',25,'本地小模型承担敏感片段识别与类别判断，通用内容生成仍交给外部服务。我们拟以 Qwen3 的一点七 B 模型为候选，采用参数高效微调，云端训练、本机推理。最终选型比较漏检、误删、定位、延迟和显存，当前还没有训练完成的专项权重。',{foot:'候选路线。当前实体检测仍为格式与上下文方法，专项模型待训练接入。',refs:[sources.model]});
 t(s,'识别片段与类别',77,203,635,69,39,C.ink,true);
 row(s,'候选基座','Qwen3-1.7B',324,{x:79,w:620,headWidth:190,size:28});
 row(s,'微调方式','LoRA 或 QLoRA',425,{x:79,w:620,headWidth:190,size:28});
 row(s,'部署方式','云端训练，本机推理',526,{x:79,w:620,headWidth:190,size:28});
 t(s,'1.7B',774,262,426,146,99,C.blue,true);
 t(s,'候选基座规模',790,421,407,55,29,C.gray);
}
// 10
{
 const s=slide('数据覆盖识别、决策与会话',25,'数据准备分成三个任务：五千一百条实体材料，一千四百四十条动作材料，以及三百六十段三轮对话。实体覆盖十四类，也包含负例和表格。数据目前主要是合成弱标签，另外保留八千条外部中文合成数据用于测试，避免把格式转换重复计数。',{foot:'自建数据为合成弱标签。8,000 条外部中文合成样本独立用于评估。',refs:[sources.dataset,'https://huggingface.co/datasets/wan9yu/pii-bench-zh']});
 t(s,'14',78,215,380,161,118,C.blue,true);t(s,'类敏感信息',85,399,385,64,35,C.ink,true);
 t(s,'姓名、联系方式、证件号\n宿舍、成绩、敏感属性等',86,494,390,113,26,C.gray);
 table(s,['训练任务','现有数据'],[['实体识别','5,100 条材料'],['动作决策','1,440 条材料'],['多轮对话','360 段三轮会话']],[245,400],{x:563,y:226,h:342,size:29});
}
// 11
{
 const s=slide('双人复核形成可追溯答案',25,'我们已选定三批复核样本：训练一百二十八个、验证九十二个、封存测试九十二个。两人独立标注，第三人裁决，并抽查一致项。工具检查格式与差异，人判断语义、任务必要性和多轮风险。目前人工标注尚待执行，不能把候选答案当成人工金标。',{foot:'312 个复核单位已选定，每段会话计一个单位。当前人工 gold 为 0。',refs:[sources.review]});
 const chart=s.charts.add('bar',{position:{left:74,top:210,width:678,height:354},categories:['封存测试','独立验证','训练试标'],series:[{name:'待复核单位',values:[92,92,128],fill:C.blue}],barOptions:{direction:'bar',grouping:'clustered',gapWidth:95},hasLegend:false,titlePlacement:'none',
 xAxis:{visible:true,textStyle:{typeface:FONT,fontSize:26,fill:C.gray},majorGridlines:null,line:{fill:'none',width:0}},yAxis:{visible:false,min:0,max:150,line:{fill:'none',width:0},majorGridlines:null},
 dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0',textStyle:{typeface:FONT,fontSize:30,bold:true,fill:C.ink}},chartFill:C.white,plotAreaFill:C.white,chartLine:{fill:'none',width:0},plotAreaLine:{fill:'none',width:0}});
 applyPresentationChartFont(chart,{fontFamily:FONT});
 t(s,'2 + 1',853,232,350,122,84,C.blue,true);
 t(s,'两人独立复核\n一人裁决分歧',863,385,335,119,30,C.ink);
 t(s,'实体、动作、完整会话',82,583,1010,50,29,C.gray);
}
// 12
{
 const s=slide('现有原型的验证记录',30,'当前记录包含八十一项回归检查、二十七项子检查和三十八项冒烟检查，它们按原始记录分别统计。原型已经具备统一对话、动作执行和失败暂停链路。这些检查证明工程流程可运行，正式识别效果、真实 API 和人工任务效果仍需独立验收。',{foot:'验证记录日期 2026-10-13。工程检查数量不代表真实隐私保护准确率。',refs:[sources.tests,sources.classifier]});
 [['81','回归检查通过'],['27','子检查通过'],['38','冒烟检查通过']].forEach(([n,l],i)=>{const x=78+i*388;t(s,n,x,211,340,153,112,C.blue,true);t(s,l,x+5,388,340,60,30,C.ink)});
 t(s,'已具备统一对话、动作执行与失败暂停链路',81,521,1115,62,32,C.ink,true);
}
// 13
{
 const s=slide('下一阶段的验证重点',30,'下一步先完成双人标注和裁决，获得可追溯答案，再训练候选模型，在独立验证集上选型，冻结后测试。最后在第二台电脑和真实服务上重跑完整链路。我们重点检查是否减少额外披露，同时保留分工、统计等任务所需的信息。',{foot:'后续验收计划。正式效果和资源开销尚待实测。',refs:[sources.review,sources.tests]});
 table(s,['阶段','交付物','验收重点'],[
  ['数据复核','人工实体与动作答案','来源、分歧与裁决可追溯'],
  ['模型验证','冻结的候选权重与测试记录','漏检、误删、泄露与任务完成'],
  ['部署验收','真实 API 与第二台电脑记录','延迟、显存、异常与暂停行为']
 ],[210,460,466],{y:208,h:342,size:27});
 t(s,'优先服务学生组织、课程项目与科研协作场景',77,587,1120,56,30,C.blue,true);
}
// 14
{
 const s=slide('',10,'隐盾希望让团队在使用大模型处理中文材料时，保留必要信息，减少额外披露。以上是我们的项目方案和阶段成果，谢谢各位评委。');
 t(s,'隐盾',73,179,1134,158,110,C.ink,true,'center');
 t(s,'面向任务必要性的本地隐私保护',73,388,1134,80,44,C.blue,true,'center');
 t(s,'感谢聆听',73,555,1134,47,27,C.gray,false,'center');
}
// 15 backup
{
 const s=slide('备答  实体输出与失败处理',0,'实体输出以原文片段、Unicode 左闭右开索引、冻结类别为核心。程序核对文本切片与实体值。模型返回格式错误、索引越界、截断或不可用时，都不能解释为没有敏感信息。当前 14 类为 PERSON_NAME、PHONE、EMAIL、ID_CARD、BANK_CARD、STUDENT_ID、API_KEY、WECHAT、BUDGET、ORG、LOCATION、DORM、GRADE、SENSITIVE_ATTR。',{backup:true,foot:'校验发现错误时暂停本轮，修正后重新处理。',refs:[sources.dataset]});
 table(s,['输出字段','校验内容'],[['text','必须是原文中实际出现的片段'],['start / end','Unicode 字符索引，切片与 text 一致'],['category','属于版本冻结的 14 类标签清单']],[300,836],{y:205,h:305,size:29});
 t(s,'格式错误、位置歧义、超长截断均应显式失败',77,566,1120,63,31,C.blue,true);
}
// 16 backup
{
 const s=slide('备答  评测口径与当前基线',0,'两个已有分数衡量不同对象，不能直接横向比较。0.9887 是动作分类器在合成弱标签分组留出中的 Macro-F1，训练 7878 条、验证 2676 条，来源组无重叠。0.5501 是现有检测器在新合成验证集上的实体严格 F1，850 条材料、1100 个标准实体，标准答案仍为构造弱标签。正式评测需独立人工标准答案，同时报告各类别召回、禁止披露事件数及分母、任务完成率、误暂停和本机 P95 延迟与显存峰值。',{backup:true,foot:'上述分数均非新本地小模型的正式验收结果。',refs:[sources.classifier,sources.ner,sources.review]});
 table(s,['对象','已有记录','解释边界'],[['动作分类器','Macro-F1  0.9887','合成弱标签分组验证'],['现有实体检测器','严格 F1  0.5501','850 条合成验证材料']],[325,352,459],{y:201,h:227,size:28});
 t(s,'正式评测',77,477,250,50,31,C.blue,true);
 t(s,'识别质量、披露事件、任务完成、误暂停\n本地保护 P95 延迟与显存峰值',77,539,1130,100,28,C.ink);
}
// 17 backup
{
 const s=slide('备答  API 与安全边界',0,'项目已有 OpenAI 兼容客户端，但现有验证记录中的真实连接仍未验收。密钥只在本机配置，不放进 PPT。发送前检查完整外发载荷，回答复检后才显示和保存。工具参数需要独立检查，真实外部工具集成另行验收。清除本地材料或对话不会撤回已经发送的内容。系统不能承诺任意输入绝对无泄露，正式演示须保持离线或真实服务模式标识。',{backup:true,foot:'本地删除不能撤回已经外发的内容。',refs:[sources.tests]});
 table(s,['边界或能力','当前状态与要求'],[['生成 API','兼容客户端已有，真实连接待验收'],['发送内容','检查当前请求与已处理历史的完整载荷'],['回答展示','复检通过后显示并写入历史'],['外部工具','参数需单独检查，真实集成待验收']],[300,836],{y:207,h:365,size:28});
}

if(p.slides.items.length!==17)throw Error('Unexpected slide count');
if(notes.filter(n=>!n.backup).reduce((sum,n)=>sum+n.seconds,0)!==360)throw Error('Talk timing must total 360s');
await fs.writeFile(BUILD+'/speaker_notes.json',JSON.stringify(notes,null,2));
await fs.writeFile(BUILD+'/research_sources.json',JSON.stringify({date:'2026-10-14',purpose:'大挑六分钟答辩的内容组织与事实依据',sources},null,2));
const draft=BUILD+'/draft.pptx';await (await PresentationFile.exportPptx(p)).save(draft);console.log('Draft exported: 14 speaking slides and 3 hidden backup slides.');
for(let i=0;i<p.slides.items.length;i++){
 const png=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(BUILD+'/draft_render/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
 console.log('Rendered '+(i+1));
}
const finalPath=OUT+'/隐盾_挑战杯大挑_6分钟答辩_白底简约版_定稿.pptx';
const tables=[7,10,13,15,16,17];
const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:draft,finalPath,
 pythonExecutable:RUNTIME+'/python/python.exe',integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tables.flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:tables,requiredNativeChartOwnerSlides:[11],materializeLiteralChartWorkbooks:true,
 fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:BUILD+'/final_validation_v2.json'});
console.log(JSON.stringify(result));
