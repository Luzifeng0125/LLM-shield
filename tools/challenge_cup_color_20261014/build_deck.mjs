import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';

const RUNTIME='C:/Users/nicholas/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const SKILL='C:/Users/nicholas/.codex/plugins/cache/openai-primary-runtime/presentations/26.1013.11914/skills/presentations';
const BUILD=path.dirname(fileURLToPath(import.meta.url));
const ROOT=path.resolve(BUILD,'../..');
const OUT=ROOT+'/隐盾挑战杯答辩_蓝绿正式版_20261015';
process.env.RUNTIME_NODE_MODULES=RUNTIME+'/node/node_modules';
const {Presentation,PresentationFile}=await import(pathToFileURL(RUNTIME+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs').href);
await fs.mkdir(OUT,{recursive:true});await fs.mkdir(BUILD+'/draft_render',{recursive:true});
const p=Presentation.create({slideSize:{width:1280,height:720}});
const notes=JSON.parse(await fs.readFile(ROOT+'/tools/challenge_cup_20261014/speaker_notes.json','utf8'));
const FONT='Microsoft YaHei';
const C={navy:'#102F46',blue:'#265EAA',teal:'#087F7D',mint:'#DDF1EE',soft:'#F3F7FA',white:'#FFFFFF',ink:'#17364A',gray:'#5D7180',line:'#D4E1E7',coral:'#B44C3C',rose:'#FFF1EA',lavender:'#6857A1',lilac:'#EEEAF7',light:'#B6CEDA'};
const tableOwners=[];const chartOwners=[];

function split(a,b,at=50){return {type:'gradient',gradientKind:'linear',angleDeg:0,offsetScale:100000,stops:[{offset:0,color:a},{offset:at*1000,color:a},{offset:at*1000+1,color:b},{offset:100000,color:b}]};}
function t(s,text,x,y,w,h,size=28,color=C.ink,bold=false,align='left'){
 const o=s.shapes.add({geometry:'textbox',name:(typeof text==='string'?text:'formatted text').replace(/\n/g,' ').slice(0,35),position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 o.text=text;o.text.style={fontSize:size,typeface:FONT,color,bold,alignment:align,verticalAlignment:'top',autoFit:'none',insets:0,wrap:'square'};return o;
}
function rich(s,runs,x,y,w,h,size=30,color=C.ink){return t(s,[runs.map(r=>typeof r==='string'?r:{run:r[0],style:{color:r[1],bold:true}})],x,y,w,h,size,color);}
function base(n,title,{bg=C.white,dark=false,foot='',manualTitle=false}={}){
 const s=p.slides.add();s.background.fill=bg;s.hidden=n>14;
 if(!manualTitle)t(s,title,62,48,1154,77,44,dark?C.white:C.navy,true);
 if(foot)t(s,foot,64,660,1095,39,17,dark?C.light:C.gray);
 t(s,String(n).padStart(2,'0'),1172,662,44,26,18,dark?C.light:C.gray,false,'right');
 const note=notes[n-1];s.speakerNotes.text=(n>14?'备答页，正常放映时跳过。':`主讲 ${note.seconds} 秒。`)+'\n\n'+note.speech+'\n\n依据与来源\n'+note.refs.join('\n');
 return s;
}
function tbl(s,headers,rows,widths,{x=64,y=190,h=370,size=26,headColor=C.navy,headerH=65,colors=null}={}){
 const values=[headers,...rows];const width=widths.reduce((a,b)=>a+b,0);
 const tb=s.tables.add({rows:values.length,columns:headers.length,left:x,top:y,width,height:h,columnWidths:widths,values});
 tb.borders.assign({fill:C.line,width:.6,style:'solid'});
 for(let i=0;i<values.length;i++){
  tb.rows[i].height=i===0?headerH:(h-headerH)/rows.length;
  for(let j=0;j<headers.length;j++){
   const cell=tb.getCell(i,j);cell.fill=i===0?headColor:(i%2?C.white:C.soft);
   cell.text.style={fontSize:size,typeface:FONT,color:i===0?C.white:(j===0?C.navy:C.gray),bold:i===0||j===0,alignment:'left',verticalAlignment:'middle',autoFit:'none',insets:{left:19,right:16,top:13,bottom:13}};
   if(colors?.[i]?.[j])cell.fill=colors[i][j];
  }
 }
 tableOwners.push(p.slides.items.length);return tb;
}
async function pic(s,file,alt,x,y,w,h){const b=await fs.readFile(file);return s.images.add({blob:b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),contentType:'image/png',alt,fit:'contain',position:{left:x,top:y,width:w,height:h}});}
function bar(s,labels,values,{x=65,y=230,w=670,h=320,max=150,colors=[C.blue,C.teal,C.lavender],bg=C.white,size=26}={}){
 const chart=s.charts.add('bar',{position:{left:x,top:y,width:w,height:h},categories:labels,series:[{name:'数量',values,fill:C.blue,points:values.map((v,i)=>({idx:i,fill:colors[i]}))}],barOptions:{direction:'bar',grouping:'clustered',gapWidth:85},hasLegend:false,titlePlacement:'none',
 xAxis:{visible:true,textStyle:{typeface:FONT,fontSize:size,fill:C.gray},majorGridlines:null,line:{fill:'none',width:0}},
 yAxis:{visible:false,min:0,max,majorGridlines:null,line:{fill:'none',width:0}},
 dataLabels:{showValue:true,position:'outEnd',numberFormatCode:'0',textStyle:{typeface:FONT,fontSize:31,bold:true,fill:C.navy}},chartFill:bg,plotAreaFill:bg,chartLine:{fill:'none',width:0},plotAreaLine:{fill:'none',width:0}});
 applyPresentationChartFont(chart,{fontFamily:FONT});chartOwners.push(p.slides.items.length);return chart;
}

// Cover. The single front-facing emblem is the only decorative object.
{
 const s=base(1,'隐盾',{bg:split(C.white,C.mint,60),manualTitle:true});
 t(s,'挑战杯大学生课外学术科技作品竞赛',65,58,710,43,23,C.teal,true);
 t(s,'隐盾',60,198,700,149,112,C.navy,true);
 t(s,'隐私保护对话系统',66,371,685,71,44,C.navy,true);
 t(s,'中文材料与多轮对话的一体化保护',67,461,670,67,28,C.gray);
 t(s,'本地识别  /  模型决策  /  安全外发',67,579,680,48,24,C.teal,true);
 await pic(s,BUILD+'/assets/front-shield.png','正面对称的深蓝盾牌概念标识',770,167,450,450);
 s.speakerNotes.text+='\n封面盾牌为品牌概念图。';
}
// Concrete user problem with highlighted information roles.
{
 const s=base(2,'材料里的额外披露',{bg:split(C.soft,C.white,38),foot:'合成场景示例。目标用户来自项目需求，尚非用户调研结论。'});
 t(s,'任务只需要',64,186,440,53,30,C.teal,true);
 t(s,'谁负责\n何时完成',62,261,430,176,57,C.navy,true);
 t(s,'会议纪要、项目材料中\n常混有任务无关的个人信息',66,489,410,96,26,C.gray);
 const tb=tbl(s,['材料字段','原始内容','任务用途'],[
  ['负责人','卫乐安','保留对应关系'],['事项','海报设计','需要'],['期限','周五完成','需要'],['电话','13000000000','无需发送']
 ],[137,254,257],{x:568,y:198,h:368,size:25,headerH:63});
 for(let j=0;j<3;j++){tb.getCell(4,j).fill=C.rose;tb.getCell(4,j).text.color=C.coral;}
 t(s,'保留任务结构，减少额外披露',571,589,620,53,29,C.teal,true);
}
// Two task conditions compared on one material.
{
 const s=base(3,'同一份名单，两种必要信息',{bg:split(C.soft,C.mint,50),foot:'设计示例。处理方式取决于任务用途及权限。'});
 t(s,'卫乐安负责海报，林雨禾负责场地',65,147,1148,54,27,C.gray);
 t(s,'统计参加人数',66,248,530,57,35,C.blue,true);
 t(s,'2 人',60,321,520,144,104,C.blue,true);
 t(s,'本地完成计数\n只发送统计结果',69,503,510,100,29,C.gray);
 t(s,'整理负责人分工',704,248,512,57,35,C.teal,true);
 t(s,'人员甲  负责海报\n人员乙  负责场地',704,346,512,130,36,C.navy,true);
 t(s,'稳定代号替换姓名\n人员与事项的关系保留',708,511,504,100,29,C.teal);
}
// Unified product view.
{
 const s=base(4,'材料与追问',{bg:split(C.navy,C.soft,34),manualTitle:true,foot:'现有原型界面，离线演示模式。'});
 t(s,'材料与追问',57,63,365,78,43,C.white,true);
 t(s,'共用一个对话',58,150,365,88,43,C.white,true);
 [['01','上传材料'],['02','直接提问'],['03','继续对话']].forEach(([n,l],i)=>{t(s,n,61,292+i*85,66,53,29,'#61CABE',true);t(s,l,144,290+i*85,270,55,31,C.white,true);});
 t(s,'每轮发送前\n重新经过本地保护',62,566,356,86,26,'#92D5CE');
 await pic(s,ROOT+'/隐盾整合交付_20261012/验证结果/界面截图/chat-desktop.png','统一对话原型真实离线界面',469,83,749,568);
 // The footer is placed on the light side for contrast.
 const footer=s.shapes.items.find(sh=>sh.name==='现有原型界面，离线演示模式。');if(footer){footer.position.left=473;footer.position.width=680;}
}
// Technical architecture. Native table maps each processing stage to responsibilities.
{
 const s=base(5,'本地保护与云端生成的分工',{bg:C.white,foot:'当前具备动作模型与校验链路；专项识别模型和真实 API 效果待验收。'});
 t(s,'本机处理',65,167,800,54,31,C.blue,true);
 t(s,'云端生成',1010,167,205,54,31,C.teal,true);
 const tb=tbl(s,['01  输入','02  识别','03  决策','04  校验','05  生成'],[
  ['材料与\n会话历史','敏感片段\n及信息类别','模型选择\n六类处理动作','检查权限\n与完整载荷','依据处理后\n上下文回答'],
  ['原文保留\n在本机','专项小模型\n待接入','动作模型\n已具备','不通过时\n暂停外发','兼容客户端\n已具备']
 ],[228,228,228,228,240],{x:64,y:233,h:282,size:25,headerH:65});
 tb.getCell(0,4).fill=C.teal;for(let i=1;i<3;i++)tb.getCell(i,4).fill=C.mint;
 t(s,'原值映射留在本机',68,558,530,54,31,C.blue,true);
 t(s,'云端回答复检后进入对话',675,558,540,54,31,C.teal,true);
}
// Decision vocabulary, sparse but chromatically grouped.
{
 const s=base(6,'六种动作，由模型选择',{bg:split(C.soft,C.white,50)});
 const actions=[['01','删除','去掉任务无关的联系方式',C.blue],['02','本地统计','只发送人数等汇总结果',C.teal],['03','泛化','降低位置或数值的精度',C.blue],['04','代号替换','保留人物与事项的对应',C.teal],['05','保留','用途与权限均满足时保留',C.blue],['06','暂停','权限未知或处理不可靠时停止',C.coral]];
 actions.forEach(([n,name,body,color],i)=>{const x=i%2?700:66;const y=186+Math.floor(i/2)*155;t(s,n,x,y,76,67,49,color,true);t(s,name,x+98,y+2,417,57,36,color,true);t(s,body,x+100,y+68,419,74,25,C.gray)});
 t(s,'安全校验决定接受或暂停，不代替模型选择动作',67,663,1090,35,18,C.gray);
}
// Multi-turn state with a highlighted blocked turn.
{
 const s=base(7,'三轮追问中的连续保护',{bg:C.white,foot:'合成会话目标。复杂指代与累计披露仍需专项训练和验证。'});
 const tb=tbl(s,['轮次','用户请求','处理结果'],[
 ['第一轮','卫乐安负责海报，周五完成','人员甲负责海报，周五完成'],
 ['第二轮','把他的截止时间改为周一','沿用人员甲与海报的对应'],
 ['第三轮','恢复真实姓名并发给云端','暂停本轮，不发送原名']
 ],[150,490,512],{y:181,h:349,size:27,headerH:65});
 for(let j=0;j<3;j++){tb.getCell(3,j).fill=C.rose;tb.getCell(3,j).text.color=C.coral;}
 t(s,'稳定代号沿用',69,574,500,58,33,C.teal,true);
 t(s,'仅提交成功外发的历史',654,574,560,58,33,C.blue,true);
}
// One saturated anchor slide for the innovation story.
{
 const s=base(8,'项目的技术创新点',{bg:C.navy,dark:true,foot:'创新方案及验证假设。尚需同条件对照验证。'});
 const rows=[['01','任务条件决策','结合任务、身份与接收方，选择信息处理动作','#7AD8CE'],['02','连续保护状态','附件与追问共享代号映射和安全历史','#A5C9F4'],['03','外发内容可复核','分别追踪漏检、误决策与执行泄露','#C5B9EC']];
 rows.forEach(([n,h,b,col],i)=>{const y=192+i*143;t(s,n,64,y,122,88,62,col,true);t(s,h,218,y+2,994,59,35,C.white,true);t(s,b,220,y+68,990,60,27,'#BFD0DB');});
}
// Candidate model and sequence of work.
{
 const s=base(9,'本地专项模型路线',{bg:split(C.navy,C.white,37),manualTitle:true,foot:'候选路线。当前实体检测仍为格式与上下文方法，专项模型待训练。'});
 t(s,'本地专项模型',59,60,390,76,42,C.white,true);t(s,'识别片段与类别',61,158,382,53,28,'#8BD8D0');
 t(s,'1.7B',55,275,412,136,94,C.white,true);t(s,'Qwen3 候选基座',62,434,375,53,29,'#BFD0DB');
 t(s,'云端训练\n本机推理',63,538,360,96,33,'#8BD8D0',true);
 [['01','复核训练材料','实体位置、类别与上下文答案'],['02','参数高效微调','LoRA 或 QLoRA，按验证集选型'],['03','本机推理验收','漏检、误删、定位、延迟和显存']].forEach(([n,h,b],i)=>{const y=191+i*143;t(s,n,529,y,72,61,37,C.teal,true);t(s,h,625,y,590,59,33,C.navy,true);t(s,b,627,y+61,582,72,25,C.gray)});
 const footer=s.shapes.items.find(sh=>sh.name.startsWith('候选路线。'));if(footer){footer.position.left=528;footer.position.width=670;footer.text='当前实体检测为格式与上下文方法，专项模型待训练。';footer.text.fontSize=16;}
}
// Dataset provenance and split, native evidence.
{
 const s=base(10,'数据覆盖识别、决策与会话',{bg:split(C.mint,C.white,28),foot:'自建数据为合成弱标签。另有 8,000 条外部中文合成样本独立用于评估。'});
 t(s,'14',62,226,270,147,111,C.teal,true);t(s,'类敏感信息',66,393,280,59,31,C.navy,true);
 t(s,'姓名、联系方式、证件号\n宿舍、成绩、敏感属性等',67,494,275,124,23,C.gray);
 tbl(s,['任务','训练','验证','测试'],[['实体识别','3,400','850','850'],['动作决策','960','240','240'],['三轮会话','240','60','60']],[250,193,193,193],{x:389,y:211,h:334,size:28,headerH:69});
 t(s,'5,100 条实体材料',391,575,455,45,25,C.blue,true);t(s,'1,440 条动作材料',833,575,390,45,25,C.teal,true);
 t(s,'360 段会话，每段作为一个数据单位',391,619,820,41,23,C.gray);
}
// Human review counts, distinct bar colors and role split.
{
 const s=base(11,'双人复核与第三人裁决',{bg:split(C.white,C.mint,64),foot:'312 个复核单位已选定，每段会话计一个单位。当前人工 gold 为 0。'});
 t(s,'待复核样本分配',67,179,690,45,27,C.gray);
 bar(s,['封存测试','独立验证','训练试标'],[92,92,128],{x:61,y:247,w:715,h:319,colors:[C.lavender,C.teal,C.blue]});
 t(s,'2 + 1',862,214,354,119,81,C.teal,true);
 t(s,'两人独立标注\n一人裁决分歧',873,366,340,109,30,C.navy,true);
 t(s,'人判断语义与任务必要性\n工具检查格式和差异',874,523,339,102,24,C.gray);
 t(s,'实体、动作、完整会话',67,601,700,43,25,C.gray);
}
// Actual engineering checks, not conflated with accuracy.
{
 const s=base(12,'现有原型的验证证据',{bg:C.soft,foot:'验证记录日期 2026-10-13。检查数量不代表真实隐私保护准确率。'});
 t(s,'工程检查通过数量',66,172,685,47,27,C.gray);
 bar(s,['冒烟检查','子检查','回归检查'],[38,27,81],{x:61,y:241,w:703,h:322,max:95,colors:[C.lavender,C.teal,C.blue],bg:C.soft});
 t(s,'原型已具备',858,178,350,52,31,C.teal,true);
 [['统一对话','材料与追问共用入口'],['动作执行','根据模型动作处理内容'],['失败暂停','校验未通过时停止外发']].forEach(([a,b],i)=>{const y=270+i*122;t(s,a,858,y,350,47,29,C.navy,true);t(s,b,860,y+52,352,59,24,C.gray)});
}
// Validation plan as a real mapping table, not a decorative roadmap.
{
 const s=base(13,'模型训练与验收安排',{bg:C.white,foot:'后续验收计划。正式效果与资源开销尚待实测。'});
 const tb=tbl(s,['验收维度','数据复核','模型验证','部署验收'],[
 ['主要交付','人工实体与\n动作答案','冻结权重与\n独立测试记录','真实 API 与\n第二台电脑记录'],
 ['检查重点','来源、分歧\n与裁决可追溯','漏检、误删、泄露\n及任务完成','延迟、显存\n及异常暂停行为']
 ],[190,320,320,322],{y:190,h:329,size:27,headerH:67});
 tb.getCell(0,2).fill=C.blue;tb.getCell(0,3).fill=C.teal;
 t(s,'优先服务',68,569,176,54,29,C.teal,true);
 t(s,'学生组织  /  课程项目  /  科研协作',272,567,936,61,32,C.navy,true);
}
// Closing, no repeated emblem.
{
 const s=base(14,'隐盾',{bg:{type:'gradient',gradientKind:'linear',angleDeg:20,stops:[{offset:0,color:'#102F46'},{offset:100000,color:'#155C63'}]},dark:true,manualTitle:true});
 t(s,'隐盾',65,141,1150,162,117,C.white,true);
 t(s,'面向任务必要性的本地隐私保护',70,365,1140,87,47,'#8BD8D0',true);
 t(s,'中文材料与多轮对话的一体化保护',72,474,1138,60,29,'#C4D9E2');
 t(s,'感谢聆听',73,610,600,45,25,C.white);
}
// Hidden appendix.
{
 const s=base(15,'备答  实体输出与失败处理',{bg:C.soft,foot:'校验发现错误时暂停本轮，修正后重新处理。'});
 tbl(s,['输出字段','校验内容'],[['text','必须是原文中实际出现的片段'],['start / end','Unicode 字符索引，切片与 text 一致'],['category','属于版本冻结的 14 类标签清单']],[300,852],{y:191,h:320,size:29,headerH:66});
 t(s,'格式错误、位置歧义、超长截断均应显式失败',67,572,1140,60,31,C.coral,true);
}
{
 const s=base(16,'备答  评测口径与当前基线',{bg:C.white,foot:'上述分数均非新本地小模型的正式验收结果。'});
 tbl(s,['对象','已有记录','解释边界'],[['动作分类器','Macro-F1  0.9887','合成弱标签分组验证'],['现有实体检测器','严格 F1  0.5501','850 条合成验证材料']],[325,352,475],{y:191,h:241,size:28,headerH:67});
 t(s,'正式评测',69,479,300,53,30,C.teal,true);t(s,'识别质量、披露事件、任务完成、误暂停\n本地保护 P95 延迟与显存峰值',70,545,1138,90,28,C.navy);
}
{
 const s=base(17,'备答  API 与安全边界',{bg:C.soft,foot:'本地删除不能撤回已经外发的内容。'});
 tbl(s,['边界或能力','当前状态与要求'],[['生成 API','兼容客户端已有，真实连接待验收'],['发送内容','检查当前请求与已处理历史的完整载荷'],['回答展示','复检通过后显示并写入历史'],['外部工具','参数需单独检查，真实集成待验收']],[300,852],{y:188,h:391,size:28,headerH:67});
}

if(p.slides.items.length!==17)throw Error('Unexpected slide count');
if(notes.filter(n=>!n.backup).reduce((s,n)=>s+n.seconds,0)!==360)throw Error('Timing mismatch');
await fs.writeFile(BUILD+'/speaker_notes.json',JSON.stringify(notes,null,2));
const draft=BUILD+'/draft.pptx';await(await PresentationFile.exportPptx(p)).save(draft);console.log('Exported 17 slides');
const requested=process.argv.includes('--preview')?[0,1,4,7,10]:p.slides.items.map((_,i)=>i);
for(const i of requested){const png=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(BUILD+'/draft_render/slide-'+String(i+1).padStart(2,'0')+'.png',new Uint8Array(await png.arrayBuffer()));console.log('Rendered '+(i+1));}
if(!process.argv.includes('--preview')){
 const finalPath=OUT+'/隐盾_挑战杯大挑_6分钟答辩_蓝绿正式版.pptx';
 const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:draft,finalPath,pythonExecutable:RUNTIME+'/python/python.exe',integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],requiredNativeTableOwnerSlides:tableOwners,requiredNativeChartOwnerSlides:chartOwners,materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:BUILD+'/final_validation.json'});
 console.log(JSON.stringify({finalPath:result.finalPath,byteCount:result.byteCount,sha256:result.finalSha256}));
}
