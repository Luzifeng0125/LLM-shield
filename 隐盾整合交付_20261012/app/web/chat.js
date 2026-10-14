"use strict";
const el = id => document.getElementById(id);
let sessionId = null, files = [], library = [], busy = false, ready = false;
const actionNames = {DELETE:'删除敏感值',LOCAL_AGGREGATE:'本地汇总',GENERALIZE:'降低精度',PSEUDONYMIZE:'替换为代号',RETAIN:'受控保留',PAUSE:'暂停发送'};
function notice(message,error=false) { el('notice').textContent=message; el('notice').classList.toggle('error',error); }
function setBusy(value) {
  busy=value;
  ['send','newChat','clearChat','file'].forEach(id=>{el(id).disabled=value||!ready;});
  ['identity','task','description'].forEach(id=>{el(id).disabled=value||!!sessionId;});
  el('message').disabled=value; el('send').textContent=value?'正在处理…':'发送'; renderFiles();
}
async function api(url,options={}) {
  const response=await fetch(url,options), data=await response.json();
  if (!response.ok) {const error=new Error(typeof data.detail==='string'?data.detail:'请求未通过检查'); error.status=response.status; throw error;}
  return data;
}
function smallButton(label,action) {
  const button=document.createElement('button'); button.type='button'; button.className='btn ghost compact';
  button.textContent=label; button.disabled=busy; button.onclick=action; return button;
}
function renderFiles() {
  el('attachments').replaceChildren();
  for (const file of files) {
    const chip=document.createElement('div'); chip.className='attachment';
    const name=document.createElement('span'); name.textContent=file.title;
    chip.append(name,smallButton('移出本轮',()=>{files=files.filter(f=>f.id!==file.id);renderFiles();}));
    el('attachments').append(chip);
  }
  el('library').replaceChildren();
  if (!library.length) el('library').textContent='尚未上传材料';
  for (const file of library) {
    const row=document.createElement('div'); row.className='material-row';
    const title=document.createElement('div'); title.textContent=file.title;
    const controls=document.createElement('div'); controls.className='material-actions';
    const added=files.some(f=>f.id===file.doc_id);
    const add=smallButton(added?'已加入':'加入本轮',()=>{
      if (files.length>=10) return notice('每轮最多添加 10 份材料。',true);
      files.push({id:file.doc_id,title:file.title});renderFiles();
    });
    add.disabled=busy||added;
    controls.append(add,smallButton('删除文件',async()=>{
      setBusy(true);
      try {
        await api(`/api/upload/${encodeURIComponent(file.doc_id)}`,{method:'DELETE'});
        files=files.filter(f=>f.id!==file.doc_id);await refreshLibrary();notice('本机材料已删除。已有对话历史保持原样。');
      } catch(error) {notice(error.message,true);} finally {setBusy(false);}
    }));
    row.append(title,controls);el('library').append(row);
  }
}
async function refreshLibrary() {library=(await api('/api/materials')).items;renderFiles();}
function render(data) {
  el('messages').replaceChildren();
  if (!(data.messages||[]).length) {
    const empty=document.createElement('p');empty.className='empty-conversation';
    empty.textContent='把材料和问题放在这里。上传、脱敏和连续追问都在这一段对话中完成。';el('messages').append(empty);
  }
  for (const message of data.messages||[]) {
    const box=document.createElement('article');box.className='chat-message';
    const title=document.createElement('h3');title.textContent=message.role==='user'?'你 · 发送的内容':'隐盾';
    const text=document.createElement('p');text.textContent=message.content;
    box.append(title,text);el('messages').append(box);
  }
  el('turns').textContent=`${data.turns||0} / 20 轮`;el('messages').scrollTop=el('messages').scrollHeight;
}
function showDecisions(decisions=[]) {
  el('decisions').replaceChildren();el('processing').hidden=!decisions.length;
  for (const item of decisions) {
    const text=document.createElement('p');text.textContent=`${actionNames[item.action]||item.action}：${item.reason||'处理完成'}`;
    el('decisions').append(text);
  }
}
async function clearRemoteSession() {
  if (sessionId) {try {await api(`/api/chat/${encodeURIComponent(sessionId)}`,{method:'DELETE'});} catch(error) {if(error.status!==404)throw error;}}
  sessionId=null;
}
async function createSession() {
  const data=await api('/api/chat/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({identity:el('identity').value,task:el('task').value,task_description:el('description').value})});
  sessionId=data.session_id;render(data);
}
async function resetConversation(message) {
  if (busy||!ready)return;
  setBusy(true);
  try {await clearRemoteSession();files=[];el('message').value='';render({});showDecisions();notice(message);}
  catch(error){notice(error.message,true);}finally{setBusy(false);}
}
el('newChat').onclick=()=>resetConversation('新对话已准备好，可以调整设置后直接发送。');
el('clearChat').onclick=()=>resetConversation('对话和代号映射已清除。本机材料可在左侧单独删除。');
el('file').onchange=async()=>{
  const selected=[...el('file').files];if(!selected.length||busy||!ready)return;
  if(selected.length+files.length>10){el('file').value='';return notice('每轮最多添加 10 份材料。',true);}
  setBusy(true);
  try {
    for(const file of selected){
      const form=new FormData();form.append('file',file);
      const result=await api('/api/upload',{method:'POST',body:form});
      files.push({id:result.doc_id,title:result.title});await refreshLibrary();
    }
    notice('材料已加入本轮。填写问题后发送，也可以直接发送材料。');
  }catch(error){notice(error.message,true);}finally{el('file').value='';setBusy(false);}
};
el('composer').onsubmit=async event=>{
  event.preventDefault();if(busy||!ready)return;
  if(!el('message').value.trim()&&!files.length)return notice('请输入消息或添加材料。',true);
  setBusy(true);
  el('apiStatus').textContent='正在处理本轮…';
  try{
    if(!sessionId)await createSession();
    const result=await api(`/api/chat/${encodeURIComponent(sessionId)}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:el('message').value,doc_ids:files.map(f=>f.id)})});
    render(result);showDecisions(result.decisions);
    if(!result.ok){el('apiStatus').textContent='本轮已暂停';notice(result.pause_reason,true);return;}
    el('message').value='';files=[];
    el('apiStatus').textContent=result.engine==='real'?'本轮真实 API 调用成功':'本轮为离线演示回复';
    notice((result.engine==='mock'?'离线演示完成。':'已收到真实生成服务的回答。')+'发送内容和回答均已通过复检。'+(result.warning||''));
  }catch(error){el('apiStatus').textContent='本轮未完成';notice(error.message,true);}finally{setBusy(false);}
};
async function initialize(){
  try{
    const config=await api('/api/config');
    for(const[id,source]of[['identity',config.identities],['task',config.tasks]]){
      for(const[key,value]of Object.entries(source)){const option=document.createElement('option');option.value=key;option.textContent=value.name;el(id).append(option);}
    }
    el('identity').value='student_leader';el('task').value='meeting_minutes';
    el('modelStatus').textContent=config.models.necessity_available?'本地脱敏决策模型已就绪':'本地模型不可用，发送将暂停';
    const llm=config.models.llm;
    el('apiStatus').textContent=llm.mode==='mock'?'离线演示 · 未调用真实 API':llm.has_key?'API 已配置 · 发送时连接':llm.mode==='real'?'API 未配置 · 无法生成回答':'未配置 API · 使用离线演示';
    el('apiHelp').textContent=`生成服务：${llm.provider} / ${llm.model}。真实调用需在本机 app/.env 配置服务地址、模型和密钥，并将 LLM_MODE 设为 real 后重启。已配置不代表已连接成功。`;
    library=config.materials;ready=true;render({});setBusy(false);
  }catch(error){notice('初始化失败，请刷新重试：'+error.message,true);}
}
initialize();
