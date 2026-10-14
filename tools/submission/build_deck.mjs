import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';

const RUNTIME=process.env.CODEX_ARTIFACT_RUNTIME || 'C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=RUNTIME+'/node/node_modules';
const SKILL=process.env.CODEX_PRESENTATIONS_SKILL || 'C:/Users/nicholas/.codex/plugins/cache/openai-primary-runtime/presentations/26.1011.11113/skills/presentations';
const BUILD=path.dirname(fileURLToPath(import.meta.url));
const ROOT=path.resolve(BUILD,'../..');
const OUT=ROOT+'/隐盾提交材料_20261014';
const {Presentation, PresentationFile}=await import(pathToFileURL(RUNTIME+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const {finalizePresentation}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs').href);
await fs.mkdir(BUILD+'/slides_qa',{recursive:true});
await fs.mkdir(OUT,{recursive:true});
const ppt=Presentation.create({slideSize:{width:1280,height:720}});
const C={navy:'#102C42',ink:'#183B4E',teal:'#087D83',mint:'#71D8C9',gray:'#526974',pale:'#F2F6F7',white:'#FFFFFF',amber:'#A96510'};
const FONT='Microsoft YaHei';
let num=0;
const notes=[];

function text(sl,txt,x,y,w,h,size=26,color=C.ink,bold=false,align='left'){
 const sh=sl.shapes.add({geometry:'textbox',name:txt.slice(0,22),position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 sh.text=txt;
 sh.text.style={fontSize:size,typeface:FONT,color,bold,alignment:align,verticalAlignment:'top',autoFit:'none',insets:0,wrap:'square'};
 return sh;
}
function slide(title,note,{dark=false,foot=''}={}){
 const sl=ppt.slides.add(); num++;
 sl.background.fill=dark?C.navy:C.white;
 text(sl,title,70,55,1120,76,44,dark?C.white:C.ink,true);
 text(sl,String(num).padStart(2,'0'),1160,665,52,28,17,dark?'#ADC4CE':C.gray,false,'right');
 if(foot) text(sl,foot,70,648,1060,45,18,dark?'#ADC4CE':C.gray);
 sl.speakerNotes.text=note;
 notes.push({slide:num,title,note}); return sl;
}
function rows(sl,items,{x=70,y=180,w=1130,gap=112,dark=false}={}){
 items.forEach(([head,body],i)=>{
  text(sl,head,x,y+i*gap,w,42,29,dark?C.mint:C.teal,true);
  text(sl,body,x,y+i*gap+46,w,70,25,dark?'#E1EDF0':C.gray);
 });
}
function table(sl,headers,values,widths,{y=182,h=400,size=24}={}){
 const all=[headers,...values];
 const t=sl.tables.add({rows:all.length,columns:headers.length,left:70,top:y,width:1140,height:h,columnWidths:widths,values:all});
 t.borders.assign({fill:'#D2DEE4',width:.7,style:'solid'});
 for(let r=0;r<all.length;r++){
  t.rows[r].height=h/all.length;
  for(let c=0;c<headers.length;c++){
   const cell=t.getCell(r,c); cell.fill=r===0?C.navy:(r%2===0?C.pale:C.white);
   cell.text.style={fontSize:size,typeface:FONT,color:r===0?C.white:(String(all[r][c]).includes('待补')?C.amber:C.ink),bold:r===0,verticalAlignment:'middle',insets:{top:10,bottom:9,left:14,right:12},autoFit:'none'};
  }
 }
 return t;
}
const sourceLocal='来源：隐盾整合交付_20261012/验证结果/验证摘要.json、模型元信息.json及现有代码。记录日期2026年10月13日。';
const assumed='方案假设：本地小型大模型尚待训练与接入验证。本页说明目标设计，不表示已有训练成果。';

// 01  Cover. All visible copy remains editable.
{
 const s=slide('隐盾',
 '建议讲解30秒。隐盾服务于使用大模型处理中文材料的团队，把敏感信息识别与处理放在本地，在同一个窗口完成材料上传和连续追问。本次汇报说明完整系统方案及已有原型证据。本地专项模型和正式人工效果尚待补齐，不能把方案页当作已完成的实验。',{dark:true,foot:'项目方案与阶段证据   2026 年 10 月 14 日'});
 text(s,'本地模型支持的\n隐私保护对话系统',70,184,1125,196,64,C.white,true);
 text(s,'中文材料处理与多轮对话，共用一个保护流程',74,414,1080,58,29,C.mint);
 text(s,'【待补 学校与团队】     【待补 汇报人】',74,536,1040,40,24,'#D0E1E6');
}
// 02
{
 const s=slide('服务对象与具体问题','建议讲解35秒。主要对象是学生组织、课程项目和科研团队。以纪要为例，任务需要负责人和事项对应，却通常不需要私人电话。我们的目标是尽量保留任务结构，同时减少无必要外发。以下场景来自项目需求，不是已经完成的用户调研统计。');
 text(s,'材料包含的个人信息，常常超过任务实际需要',70,166,1100,70,34,C.teal,true);
 rows(s,[['学生组织','活动名单与人数统计，避免名单随问题一起外发'],['课程与项目团队','整理纪要和分工，保留人物与事项的对应'],['后续使用对象','教师、科研团队与类似组织，迁移前重新确认权限'] ],{y:280,gap:108});
}
// 03 Screenshot authentic existing app.
{
 const s=slide('一个对话入口',sourceLocal+'\n建议讲解35秒。左侧是现有原型的真实离线界面截图：材料管理、任务设置和消息都在同一页。材料脱敏发生在每一轮发送内部。此截图证明交互形态，不证明新本地大模型效果，也不是云端生成质量证据。',{foot:'现有原型截图，离线演示模式'});
 const b=await fs.readFile(ROOT+'/隐盾整合交付_20261012/验证结果/界面截图/chat-desktop.png');
 s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt:'隐盾统一对话原型离线演示截图',fit:'contain',position:{left:70,top:160,width:650,height:484}});
 rows(s,[['上传材料并直接提问','文字与附件进入同一条处理链路'],['继续追问','沿用已处理历史和本地代号映射'],['检查失败则暂停','本轮停止，不覆盖此前成功历史']],{x:766,y:184,w:435,gap:140});
}
// 04
{
 const s=slide('系统分工',assumed+'\n建议讲解40秒。本地小型模型识别片段，已有动作分类器决定如何处理。权限和发送前校验由程序执行。外部生成服务只看通过检查的载荷，不接收本地原值映射。当前实体检测还是规则与启发式，新识别模块接入后需要重跑全链路。');
 table(s,['位置','组件','主要职责'],[
  ['本机','材料解析与会话管理','统一输入，保留任务和历史'],
  ['本机','小型识别模型〔方案〕','识别敏感片段、类别及位置'],
  ['本机','动作模型与安全检查','选择动作，校验并执行转换'],
  ['外部服务','生成模型 API','依据检查后的上下文作答']
 ],[165,405,570],{h:358});
 text(s,'原文映射留在本机，回答通过复检后才进入对话',70,578,1120,45,28,C.teal,true);
}
// 05
{
 const s=slide('本地小型模型方案',assumed+'\n建议讲解40秒。本地模型用于敏感信息识别和类别判定，不承担通用问答。以Qwen3-1.7B微调作为报告中的示例路线，实际选型仍需与UIE和GLiNER比较。训练在云端GPU，本机做推理。来源：https://huggingface.co/Qwen/Qwen3-1.7B；https://github.com/hiyouga/LlamaFactory',{dark:true,foot:'方案假设   实际基座、训练记录及权重待补'});
 text(s,'专门识别敏感片段与类别',70,172,1120,65,38,C.mint,true);
 rows(s,[['基座与微调','Qwen3-1.7B 示例路线，LoRA 或 QLoRA 领域微调'],['训练与运行','云端 GPU 训练，本机推理，冻结提示与输出格式'],['选型依据','比较中文漏检、误删、原文定位、延迟及资源占用']],{y:280,gap:112,dark:true});
}
// 06
{
 const s=slide('识别结果必须能回到原文',assumed+'\n建议讲解30秒。模型输出只有通过程序核对才能使用。start/end采用Unicode字符串下标，左闭右开。模型给错坐标、生成不存在的词、输出截断，都不能当成没有敏感信息。自报置信度不能作为经过校准的概率。');
 table(s,['字段','说明','校验要求'],[
 ['text','原文中的敏感片段','必须能在原文中定位'],
 ['start / end','片段起止位置','原文切片与 text 一致'],
 ['category','经确认的敏感类别','必须属于冻结类别清单'],
 ['evidence','局部依据或来源位置','可追溯，不包含虚构事实']
 ],[245,405,490],{h:350});
 text(s,'格式错误、位置歧义或超长截断时暂停本轮',70,586,1120,42,29,C.teal,true);
}
// 07
{
 const s=slide('模型选择六类处理动作',sourceLocal+'\n建议讲解40秒。识别到一个名字不意味着一定删除，模型根据任务和接收方选择动作。现有动作分类器是TF-IDF加逻辑回归。程序校验只能放行或暂停，不按旧规则改选另一个动作。模型缺失、概率异常、最高分并列时暂停。',{foot:'模型负责选动作，安全检查负责放行或暂停'});
 table(s,['动作','用途'],[
 ['删除 DELETE','去掉与任务无关的敏感片段'],
 ['本地聚合 LOCAL_AGGREGATE','只提供检查通过的统计信息'],
 ['泛化 GENERALIZE','降低位置或其他信息的精度'],
 ['代号替换 PSEUDONYMIZE','保持人物和事项之间的关系'],
 ['保留 RETAIN','仅在用途、身份和接收方允许时使用'],
 ['暂停 PAUSE','模型异常、权限冲突或转换不可靠时停止']
 ],[470,670],{y:168,h:455,size:23});
}
// 08
{
 const s=slide('多轮对话中的保护',sourceLocal+'\n建议讲解40秒。每轮处理新输入，合并历史后再检查实际完整载荷。同一个已确认人物在一个会话中用同一代号。第三轮要求还原私人信息时仍需权限校验。现有记录是20轮上限、闲置30分钟过期；同名歧义和语义重识别仍需专项测试。');
 rows(s,[['每轮输入都检查','新文字、新附件以及合并后的历史都进入检查范围'],['同一实体保持代号','保留负责人关系，本地映射不进入外部提示'],['成功后才提交历史','回答通过复检再显示，失败轮不污染已有对话'],['清除对话与删除材料分开','删除本机文件不会撤回已经发送的内容']],{y:165,gap:114});
}
// 09
{
 const s=slide('安全边界与外部 API',sourceLocal+'\n建议讲解35秒。已有兼容聊天接口客户端，服务地址和模型通过本机配置。当前记录尚未完成真实连接验收。不要把网关配置当作验证了某个供应商的实际模型，也不要在截图中显示密钥。B3工具边界有代码设计，真实工具集成尚需验收。');
 rows(s,[['输入边界','检查真正发送的完整请求，包含处理后历史'],['展示边界','回答复检通过后再显示和保存'],['工具边界','工具参数另行检查，真实外部工具集成待验收']],{x:70,y:185,w:625,gap:136});
 text(s,'API 接入状态',780,185,420,50,32,C.teal,true);
 text(s,'兼容客户端已有\n真实连接验收待补\n\n密钥仅在本机配置\n演示回复保留离线标识',780,260,420,290,27,C.ink);
}
// 10
{
 const s=slide('数据与人工复核','建议讲解35秒。团队已确认两名独立复核者和一名裁决者。A/B先判断原文与任务，再看系统结果，减少系统答案造成的影响。C解决分歧。现有9个合成单元是试标准备，正式42个单元仍是计划，不能写为已完成标注。来源：https://github.com/doccano/doccano；随包人工复核方案。');
 text(s,'2 人独立复核 + 1 人裁决',70,170,1130,88,50,C.teal,true);
 rows(s,[['标注实体与处理必要性','先确认敏感片段，再判断当前任务允许如何处理'],['保留原始意见与裁决依据','实体位置、任务质量、漏检误删和外发记录分别检查'],['按源材料划分数据','训练、验证和测试隔离，近似改写不跨集合']],{y:305,gap:103});
}
// 11
{
 const s=slide('实验比较与评价方法','建议讲解40秒。比较时固定材料、任务、生成模型与设置。统一遮盖、固定类别和现有模型策略作为对照，目标识别模块替换后测量变化。无保护基线只使用虚构或允许的材料。漏检、任务完成和误拦分别统计，暂停不能计作完成，零次观测泄露也不能证明零风险。');
 table(s,['评价维度','需要回答的问题'],[
 ['实体识别','类别和原文位置是否同时正确，哪些类别容易漏检'],
 ['信息暴露','不允许披露的信息是否到达输入、展示或工具边界'],
 ['任务可用性','纪要、统计与对外介绍能否满足预设完成标准'],
 ['运行成本','本地保护延迟、端到端延迟、显存与冷启动']
 ],[295,845],{h:365,size:25});
 text(s,'同一批案例进行配对比较，报告分母与失败案例',70,593,1140,40,27,C.teal,true);
}
// 12
{
 const s=slide('现有原型的验证记录',sourceLocal+'\n建议讲解40秒。三项计数分别按记录展示，不相加为总测试数。动作模型Accuracy0.9922、Macro-F1 0.9887只衡量合成弱标签的复现情况，不是目标小型大模型的识别效果。90例离线代理结果中固定类别基线同样100%，不能据此宣称本方案优于对照。',{foot:'已有记录截至 2026 年 10 月 13 日，尚非目标识别模型的验收结果'});
 [['81','回归检查'],['27','子检查'],['38','冒烟检查']].forEach(([n,l],i)=>{text(s,n,70+i*388,168,350,120,84,C.teal,true); text(s,l,75+i*388,302,355,50,28,C.ink);});
 text(s,'动作分类器 Macro-F1   0.9887',70,430,1120,52,34,C.ink,true);
 text(s,'来自合成弱标签分组验证，不能视为真实材料准确率',70,504,1120,68,28,C.gray);
}
// 13
{
 const s=slide('目标版本正式评测结果',assumed+'\n此页是结果填写模板，建议真实评测完成后再据数据讲解。所有待补字段必须由实验记录支持。至少提供测试材料数、实体数、模型版本、测试设备和生成服务设置。不得把上一页的动作分类器分数复制到这里作为识别指标。',{foot:'填写条件：冻结模型版本、独立测试集与 A/B/C 复核记录'});
 table(s,['指标','完整方案','对照方案'],[
 ['实体严格匹配 F1','【待补】','【待补】'],
 ['高风险类别召回率','【待补】','【待补】'],
 ['不允许披露事件 / 适用案例','【待补】','【待补】'],
 ['人工任务完成率 / 误拦率','【待补】','【待补】'],
 ['本地保护 P95 / 显存峰值','【待补】','【待补】']
 ],[600,270,270],{y:168,h:443,size:24});
}
// 14
{
 const s=slide('项目贡献与验证重点','建议讲解35秒。创新落在具体的方法组合、中文任务适配和可复核实验。开源基础模型、本地运行、代号替换均有先例，不写首创。只有完成同条件对照后，才能报告任务完成提升或者泄露降低。');
 rows(s,[['任务条件下的模型动作','将任务、身份与接收方纳入决策，再由程序约束执行'],['材料与对话共享保护状态','处理附件和连续追问，保持代号关系与实际外发一致'],['边界可观察的复核流程','分别检查请求、展示和工具参数，保存独立判断证据']],{y:180,gap:145});
}
// 15
{
 const s=slide('产品演示与截图替换页','建议用于1分20秒实机演示。录屏先上传虚构纪要，再要求按负责人列待办，最后尝试索要私人电话。展示稳定代号和暂停行为。此页预留给运行截图，不要使用合成界面冒充真实运行。若仍是mock，讲清楚这是流程演示。可复制此页用于补充其他真实截图。',{foot:'【待补】接入后的真实运行截图；保留模式、模型版本与必要的处理详情'});
 const sh=s.shapes.add({geometry:'textbox',placeholderType:'picture',name:'真实截图替换位置',position:{left:70,top:178,width:766,height:430},fill:C.pale,line:{fill:'#B8CAD2',width:1,style:'dashed'}});
 sh.text='【待补 真实运行截图】\n\n上传材料   连续追问   查看处理结果';
 sh.text.style={fontSize:27,typeface:FONT,color:C.gray,alignment:'center',verticalAlignment:'middle',insets:20};
 rows(s,[['第一轮','上传纪要并整理'],['第二轮','按负责人列出待办'],['第三轮','检查越权请求暂停']],{x:888,y:195,w:320,gap:130});
}
// 16
{
 const s=slide('交付与后续验收','建议讲解35秒。项目已有统一流程和检查工具，完整方案包含本地识别、模型动作、会话保护与外部生成服务。近期补齐模型权重、训练记录、真实API、多轮录像和独立人工评测，再完成第二台电脑部署验收。当前不宣称生产级安全、零泄露、专利或真实用户规模。',{dark:true,foot:'团队信息、实际权重、训练日志、正式评测与视频链接待补'});
 text(s,'统一对话与安全执行链路已有原型',70,178,1110,78,38,C.mint,true);
 rows(s,[['本地识别模块','冻结权重、提示、类别与量化方式，重跑完整回归'],['真实服务与人工效果','确认 API 连通，完成双人复核与分歧裁决'],['第二台电脑部署','记录依赖、资源占用、启动与失败行为']],{y:306,gap:105,dark:true});
}

await fs.writeFile(BUILD+'/slides_notes.json',JSON.stringify(notes,null,2));
const draft=BUILD+'/draft.pptx';
await (await PresentationFile.exportPptx(ppt)).save(draft);
console.log('Draft exported: '+ppt.slides.items.length+' slides');
for (let i=0;i<ppt.slides.items.length;i++){
 const sl=ppt.slides.items[i];
 const png=await ppt.export({slide:sl,format:'png',scale:1});
 await fs.writeFile(BUILD+'/slides_qa/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));
 console.log('Rendered slide '+(i+1));
}
const finalPath=OUT+'/隐盾项目答辩PPT模板.pptx';
const res=await finalizePresentation({
 workspaceDir:ROOT,candidatePath:draft,finalPath,
 pythonExecutable:RUNTIME+'/python/python.exe',
 integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',
 layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[4,6,7,11,13].flatMap(n=>['--require-native-table-slide',String(n)])],
 requiredNativeTableOwnerSlides:[4,6,7,11,13],
 fontPolicy:{basis:'design',families:[FONT]},
 verifyArtifactToolImport:true,
 receiptPath:BUILD+'/deck_validation.json'
});
console.log(JSON.stringify(res));
