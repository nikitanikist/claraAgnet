'use strict';
const $ = id => document.getElementById(id);
const state = {cid:null, es:null, files:[], jobs:[], status:null, settings:null, skills:[], seen:new Set(), tools:new Map(), resultGroups:new Map(), usageGroups:new Map(), usageReports:new Map(), actionCount:0, draft:null, active:null, view:'chat', pending:new Map(), initializing:false};
function el(tag, cls, text) { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; }
function toast(text){$('toast').textContent=text;$('toast').classList.remove('hidden');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').classList.add('hidden'),6500);}
async function api(path, options={}) { const headers={'X-Clara-Request':'1',...(options.headers||{})};if(options.body && !(options.body instanceof FormData))headers['Content-Type']='application/json';const response=await fetch(path,{...options,headers,credentials:'same-origin'});let body;try{body=await response.json();}catch{body={detail:'Could not read Clara’s response.'};}if(!response.ok){if(response.status===401)$('connection-gate').classList.remove('hidden');throw new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));}return body; }
function listen(id,event,fn){$(id).addEventListener(event,async e=>{try{await fn(e);}catch(error){toast(error.message);}});}
function formatBytes(value){return value<1000?`${value} B`:value<1e6?`${(value/1000).toFixed(1)} KB`:`${(value/1e6).toFixed(1)} MB`;}
function humanTool(name){return name.replace(/^mcp__[^_]+__/,'').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());}
function showView(view){state.view=view;document.querySelectorAll('.view').forEach(n=>n.classList.add('hidden'));$(view+'-view').classList.remove('hidden');document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.view===view));$('view-eyebrow').textContent={chat:'YOUR WORKSPACE',skills:'PROCEDURES & KNOWLEDGE',settings:'LOCAL CONNECTIONS',knowledge:'REFERENCE & LEARNING',workflow:'VERIFIED PROGRESS'}[view];$('view-title').textContent={chat:'A little more capable, every day.',skills:'Give Clara the context to do good work.',settings:'Set up your working environment.',knowledge:'Build on what Clara learns.',workflow:'See what is finished and what remains.'}[view];if(view==='knowledge')loadLearning().catch(e=>toast(e.message));if(view==='workflow')loadWorkflow().catch(e=>toast(e.message));}
function inlineText(parent,text){const parts=text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);for(const part of parts){if(part.startsWith('**')&&part.endsWith('**'))parent.append(el('strong','',part.slice(2,-2)));else if(part.startsWith('`')&&part.endsWith('`'))parent.append(el('code','',part.slice(1,-1)));else parent.append(document.createTextNode(part));}}
function renderText(parent,text){parent.replaceChildren();const segments=text.split('```');segments.forEach((piece,i)=>{if(i%2){parent.append(el('pre','',piece.replace(/^\w*\n/,'')));}else{inlineText(parent,piece);}});}
function addMessage(role,text,streaming=false,jobId=null){$('welcome')?.classList.add('hidden');const node=el('article','message '+role+(streaming?' streaming':''));if(jobId)node.dataset.job=jobId;node.append(el('div','message-label',role==='user'?'You':'Clara'));const body=el('div','message-body');renderText(body,text);node.append(body);$('messages').append(node);placeResultGroup(jobId);return {node,body,text};}
function scrollMessages(){const container=$('messages');if(container.scrollHeight-container.scrollTop-container.clientHeight<220||state.follow)container.scrollTop=container.scrollHeight;}
function clearConversation(){state.es?.close();state.seen.clear();state.tools.clear();state.resultGroups.clear();state.usageGroups.clear();state.usageReports.clear();state.actionCount=0;state.draft=null;state.active=null;state.pending.clear();$('messages').querySelectorAll('.message,.status-note').forEach(n=>n.remove());$('welcome').classList.remove('hidden');$('activity').replaceChildren(el('p','empty-note','Tool activity appears when a task starts.'));$('artifacts').replaceChildren(el('p','empty-note','Finished files will appear here.'));$('usage').textContent='Reported after each task. Your subscription’s limits still apply.';$('activity-count').textContent='0 actions';$('pending').classList.add('hidden');state.files=[];renderFiles();setBusy(false);}
function setBusy(busy,status=''){ $('send-button').disabled=busy;$('stop-button').classList.toggle('hidden',!busy);$('task-state').textContent=busy?({queued:'Waiting for the current task to finish',running:'Clara is working…',waiting:'Waiting for your response',cancelling:'Stopping the task…'}[status]||'Clara is working…'):'Ready for your next task';}
function placeResultGroup(jobId){
    const messages=[...$('messages').querySelectorAll('.message[data-job]')].filter(node=>node.dataset.job===jobId);
    let anchor=messages.at(-1);
    if(!anchor)return;
    for(const group of [state.resultGroups.get(jobId),state.usageGroups.get(jobId)]){
        if(group){anchor.after(group);anchor=group;}
    }
}
function usageNumber(value){return typeof value==='number'&&Number.isFinite(value)?value.toLocaleString():'Not reported';}
function usageCost(value){if(typeof value!=='number'||!Number.isFinite(value))return 'Not reported';if(value>0&&value<0.000001)return '<$0.000001';return '$'+value.toLocaleString('en-US',{minimumFractionDigits:4,maximumFractionDigits:6});}
function usageSeconds(data){const value=data.wall_duration_ms??data.duration_ms;return typeof value==='number'?(value/1000).toFixed(1)+' seconds':'Time not reported';}
function usageMetric(label,value){const box=el('div','usage-metric');box.append(el('span','',label),el('strong','',value));return box;}
function renderUsageSummary(){
    const reports=[...state.usageReports.values()].filter(row=>['completed','failed','cancelled','interrupted','incomplete','needs_review'].includes(row.status));
    const knownTokens=reports.filter(row=>typeof row.data.total_tokens==='number');
    const knownCosts=reports.filter(row=>typeof row.data.sdk_estimated_usd==='number');
    const box=$('usage');box.replaceChildren(el('strong','','Conversation totals'));
    box.append(el('div','',reports.length+' finished tasks'));
    box.append(el('div','',(knownTokens.length?usageNumber(knownTokens.reduce((sum,row)=>sum+row.data.total_tokens,0)):'Not reported')+' tokens'));
    box.append(el('div','',(knownCosts.length?usageCost(knownCosts.reduce((sum,row)=>sum+row.data.sdk_estimated_usd,0)):'Not reported')+' · API estimate (USD)'));
    if(reports.length!==knownTokens.length||reports.length!==knownCosts.length)box.append(el('small','usage-warning','Partial totals: '+knownTokens.length+'/'+reports.length+' tasks report total tokens; '+knownCosts.length+'/'+reports.length+' report cost.'));
    box.append(el('small','','Max bill and remaining allowance are not available here.'));
    if(state.cid){const link=el('a','usage-export','Download usage CSV');link.href='/api/conversations/'+encodeURIComponent(state.cid)+'/usage.csv';link.download='clara-task-usage.csv';box.append(link);}
}
function addUsage(jobId,data,status){
    const prior=state.usageReports.get(jobId);
    state.usageReports.set(jobId,{data,status:status||prior?.status||'running'});
    let group=state.usageGroups.get(jobId);
    if(!group){group=el('article','message assistant usage-message');group.dataset.usageJob=jobId;state.usageGroups.set(jobId,group);}
    const heading=el('div','message-label','Task usage');
    const metrics=el('div','usage-metrics');
    metrics.append(usageMetric('Total tokens',usageNumber(data.total_tokens)),usageMetric('API estimate · USD',usageCost(data.sdk_estimated_usd)));
    group.replaceChildren(heading,metrics,el('div','usage-meta',usageSeconds(data)+(data.turns!=null?' · '+data.turns+' model turns':'')));
    if(typeof data.user_wait_ms==='number')group.append(el('div','usage-meta','Waiting for you: '+(data.user_wait_ms/60000).toFixed(1)+' min · Working time: '+(data.active_duration_ms/60000).toFixed(1)+' min'),el('small','usage-note','Working time includes model reasoning, tools and other processing.'));
    if(data.coverage!=='reported')group.append(el('p','usage-warning','Incomplete usage: the task ended without a complete usage report. Missing values do not mean zero.'));
    if(data.unknown_price)group.append(el('p','usage-warning','The SDK did not recognize a model price. Cost is unavailable.'));
    if(data.result_subtype==='error_max_budget_usd')group.append(el('p','usage-warning','Task estimate limit reached. Review completed actions before continuing.'));
    const details=el('details','usage-details');details.append(el('summary','','Token breakdown & models'));
    const list=el('dl','usage-breakdown');
    for(const [key,label] of [['input_tokens','Input (uncached)'],['output_tokens','Output'],['cache_read_input_tokens','Cache read'],['cache_creation_input_tokens','Cache write']])list.append(el('dt','',label),el('dd','',usageNumber(data.tokens?.[key])));
    details.append(list);
    for(const model of data.models||[])details.append(el('p','usage-model',model.model+' · '+usageNumber(model.total_tokens)+' tokens · '+usageCost(model.sdk_estimated_usd)+' estimated'));
    details.append(el('p','usage-explanation','Counts include repeated context across model turns. '+(data.scope==='all_models'?'All models reported by the SDK are included.':'Main agent loop only; older records may omit helper-model tokens.')));
    details.append(el('p','usage-explanation','Input, output and cached tokens have different rates. The SDK uses its bundled price table; this estimate is not an invoice or a measurement of Max allowance.'));
    if(data.limit_usd!=null)details.append(el('p','usage-explanation','Task estimate limit: '+usageCost(data.limit_usd)+'. Checked between model steps; the final step may exceed it.'));
    if(data.total_tokens>0&&typeof data.sdk_estimated_usd==='number')details.append(el('p','usage-explanation','Blended estimate per 1,000 reported tokens: '+usageCost(data.sdk_estimated_usd*1000/data.total_tokens)+'. Average for this task, including any request fees; not a fixed token rate.'));
    group.append(details,el('small','usage-note','SDK estimate, not your actual subscription charge.'));
    const diagnosticLink=el('a','usage-export','Download task log');diagnosticLink.href='/api/jobs/'+encodeURIComponent(jobId)+'/diagnostics.json';diagnosticLink.download='clara-task-diagnostics.json';group.append(diagnosticLink);
    placeResultGroup(jobId);renderUsageSummary();
}
function updateUsageStatus(jobId,status){
    const row=state.usageReports.get(jobId);
    if(row){row.status=status;renderUsageSummary();}
    else if(['completed','failed','cancelled','interrupted','incomplete','needs_review'].includes(status))addUsage(jobId,{coverage:'unavailable',tokens:{},total_tokens:null,sdk_estimated_usd:null},status);
}
function artifactCard(file){
    const link=el('a','artifact');
    link.href='/api/files/'+encodeURIComponent(file.id);
    link.download=file.name;
    link.dataset.file=file.id;
    link.setAttribute('aria-label','Download '+file.name);
    link.append(el('strong','artifact-name','↓  '+file.name),el('small','',formatBytes(file.size)+' · Download file'));
    return link;
}
function upsertArtifact(container,file){
    const existing=[...container.querySelectorAll('[data-file]')].find(node=>node.dataset.file===file.id);
    const link=artifactCard(file);
    if(existing)existing.replaceWith(link);else container.append(link);
}
function addArtifact(file,jobId=file.job_id){
    $('artifacts').querySelector('.empty-note')?.remove();
    upsertArtifact($('artifacts'),file);
    if(!jobId)return;
    let group=state.resultGroups.get(jobId);
    if(!group){
        group=el('article','message assistant file-message');
        group.dataset.resultJob=jobId;
        group.setAttribute('aria-label','Files from this task');
        group.append(el('div','message-label','Files'),el('div','message-artifacts'));
        state.resultGroups.set(jobId,group);
    }
    upsertArtifact(group.querySelector('.message-artifacts'),file);
    placeResultGroup(jobId);
}
function eventReceived(event){if(state.seen.has(event.id))return;state.seen.add(event.id);const d=event.data;switch(event.kind){case 'user':addMessage('user',d.text,false,event.job_id);break;case 'delta':if(!state.draft)state.draft=addMessage('assistant','',true,event.job_id);state.draft.text+=d.text;state.draft.body.textContent=state.draft.text;break;case 'assistant':if(state.draft){state.draft.node.remove();state.draft=null;}addMessage('assistant',d.text,false,event.job_id);break;case 'tool':{if(state.draft){state.draft.node.remove();state.draft=null;}$('activity').querySelector('.empty-note')?.remove();const detail=el('details','activity-item');detail.append(el('summary','',humanTool(d.name)),el('pre','',d.input||''));$('activity').append(detail);state.tools.set(d.id,detail);state.actionCount++;$('activity-count').textContent=state.actionCount+' actions';break;}case 'tool_done':{const n=state.tools.get(d.id);if(n){n.classList.add(d.failed?'failed':'done');if(typeof d.duration_ms==='number')n.querySelector('summary').append(el('small','', ' · '+(d.duration_ms/1000).toFixed(1)+'s'));if(d.output_excerpt)n.append(el('pre','tool-output',d.output_excerpt));for(const shot of d.images||[]){const link=el('a','','Download screenshot evidence');link.href=shot.url;link.setAttribute('download','');n.append(link);}if(d.output_truncated)n.append(el('small','','Saved output shortened; inspect the original if more detail is needed.'));}break;}case 'artifact':addArtifact(d,event.job_id);break;case 'approval':case 'question':state.pending.set(d.request_id,{kind:event.kind,...d});renderPending();break;case 'answer':state.pending.delete(d.request_id);renderPending();$('messages').append(el('p','status-note','Your response: '+d.answer));break;case 'usage':addUsage(event.job_id,d);break;case 'status':{updateUsageStatus(event.job_id,d.status);const busy=['queued','running','waiting','cancelling'].includes(d.status);state.active=busy?event.job_id:null;setBusy(busy,d.status);if(!busy){state.pending.clear();renderPending();if(d.status!=='completed'){ $('messages').append(el('p','status-note error',d.message||d.status));}if(state.draft){state.draft.node.classList.remove('streaming');state.draft=null;}}break;}}scrollMessages();}
function renderPending(){
    const box=$('pending');box.replaceChildren();box.classList.toggle('hidden',state.pending.size===0);
    for(const [id,item] of state.pending){
        const section=el('section','pending-request');section.dataset.request=id;
        if(item.kind==='approval'){
            section.append(el('h3','','Review this action'),el('p','',humanTool(item.tool)),el('pre','',JSON.stringify(item.input,null,2)));
            for(const [label,value] of [['Allow once','allow'],['Decline','deny']]){
                const button=el('button',value==='allow'?'primary':'',label);button.onclick=()=>answerRequest(id,value);section.append(button);
            }
        }else{
            const legacyLong=item.question.length>300 || item.question.includes('\n');
            section.append(el('span','eyebrow','Your input'),el('h3','',legacyLong?'Clara needs your input':item.question));
            const content=text=>{const node=el('div','question-context');renderText(node,text);return node;};
            if(legacyLong)section.append(content(item.question));
            if(item.context)section.append(content(item.context));
            if(item.details){const details=el('details','question-details');details.append(el('summary','','Show details'),content(item.details));section.append(details);}
            if(item.choices?.length){
                const choices=el('div','question-choices');
                for(const choice of item.choices){const button=el('button','question-choice',choice.label);button.title=choice.answer;button.onclick=()=>answerRequest(id,choice.answer);choices.append(button);}
                section.append(choices);
            }
            const label=el('label','question-label',item.choices?.length?'Or write your answer':'Your answer');label.htmlFor='answer-'+id;
            const input=el('textarea','question-answer');input.id='answer-'+id;input.rows=2;input.placeholder='Type your answer…';input.setAttribute('aria-label','Answer Clara');input.value=item.answerDraft||'';
            input.oninput=()=>{item.answerDraft=input.value;};
            const button=el('button','primary','Send answer');button.onclick=()=>answerRequest(id,input.value);
            input.onkeydown=e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();button.click();}};
            section.append(label,input,button);
        }
        section.querySelectorAll('button,textarea').forEach(n=>n.disabled=!!item.submitting);
        box.append(section);
    }
}
async function answerRequest(id,answer){
    const item=state.pending.get(id);if(!item||item.submitting||!answer.trim())return;
    item.submitting=true;renderPending();
    try{await api('/api/requests/'+id,{method:'POST',body:JSON.stringify({answer})});state.pending.delete(id);renderPending();}
    catch(error){item.submitting=false;renderPending();toast(error.message);}
}
async function refreshConversations(){const rows=await api('/api/conversations');$('conversations').replaceChildren();for(const c of rows){const button=el('button','conversation'+(c.id===state.cid?' selected':''),c.title);button.title=c.title;button.onclick=()=>openConversation(c.id).catch(e=>toast(e.message));$('conversations').append(button);}return rows;}
async function openConversation(cid){clearConversation();state.cid=cid;const detail=await api('/api/conversations/'+cid);for(const file of detail.files){if(file.kind==='artifact')addArtifact(file);}state.jobs=detail.jobs;for(const job of detail.jobs){if(['completed','failed','cancelled','interrupted','incomplete','needs_review'].includes(job.status))addUsage(job.id,job.usage_report,job.status);}renderUsageSummary();const active=detail.jobs.find(j=>['queued','running','waiting','cancelling'].includes(j.status));state.active=active?.id||null;setBusy(!!active,active?.status);for(const item of detail.pending)state.pending.set(item.request_id,{kind:item.kind,...item.data});renderPending();state.follow=true;state.es=new EventSource('/api/conversations/'+cid+'/events');state.es.onmessage=e=>eventReceived(JSON.parse(e.data));state.es.onerror=()=>{$('task-state').textContent='Reconnecting to Clara…';};state.es.onopen=()=>{if(!state.active)$('task-state').textContent='Ready for your next task';};await refreshConversations();showView('chat');}
async function newConversation(){const c=await api('/api/conversations',{method:'POST',body:'{}'});await openConversation(c.id);applyDefaultMode();$('prompt').focus();}
function renderFiles(){$('attached-files').replaceChildren();for(const file of state.files){const chip=el('button','attachment-chip',file.name+' ×');chip.title='Remove attachment';chip.onclick=()=>{state.files=state.files.filter(f=>f.id!==file.id);renderFiles();};$('attached-files').append(chip);}}
async function refreshStatus(){const s=await api('/api/status');state.status=s;const connected=s.auth.connected;const expired=s.auth.needs_login;const label=expired?'Claude login needs refresh':connected?`${s.auth.plan||'Claude'} sign-in found`:'Claude not connected';$('sidebar-connection').textContent=label;$('connection-dot').classList.toggle('online',connected&&!expired);$('auth-title').textContent=label;$('auth-description').textContent=s.auth.message;$('workspace-path').textContent=s.workspace;$('browser-status').textContent=s.connectors.browser.available?'Chrome ready · sign into websites in Clara’s Chrome profile':s.connectors.browser.message;$('desktop-status').textContent=s.desktop.message;$('desktop-enabled').disabled=!s.connectors.desktop.supported_platform;$('notice').classList.toggle('hidden',connected&&!expired);$('notice').textContent=expired?'Claude’s stored session has expired. Run clara login in the terminal, then retry a task.':s.auth.message;}
async function loadSettings(){const s=await api('/api/settings');state.settings=s;$('default-mode').value=s.default_execution_mode;$('model').value=s.model;$('reasoning-effort').value=s.reasoning_effort||'medium';$('max-turns').value=s.max_turns??'';$('unlimited-turns').checked=s.max_turns===null;setTurnLimitControl('max-turns','unlimited-turns');$('timeout').value=s.task_timeout_minutes;$('budget-limit').value=s.max_budget_usd??'';$('read-roots').value=s.read_roots.join('\n');$('browser-enabled').checked=s.browser_enabled;$('desktop-enabled').checked=s.desktop_enabled;$('capture-evidence').checked=s.capture_evidence!==false;}
async function loadSkills(){state.skills=await api('/api/skills');$('skills-list').replaceChildren();for(const skill of state.skills){const button=el('button','skill-card');button.append(el('strong','',skill.name.replaceAll('-',' ')),el('p','',skill.description));button.onclick=()=>{$('skill-name').value=skill.name;$('skill-content').value=skill.content;document.querySelectorAll('.skill-card').forEach(n=>n.classList.toggle('selected',n===button));};$('skills-list').append(button);}if(!$('skill-name').value&&state.skills.length)$('skills-list').firstChild.click();}
async function initialize(){if(state.initializing)return;state.initializing=true;try{const params=new URLSearchParams(location.hash.slice(1));const token=params.get('access');if(token){await api('/api/session',{method:'POST',body:JSON.stringify({token})});history.replaceState(null,'',location.pathname);}await refreshStatus();$('connection-gate').classList.add('hidden');await Promise.all([loadSettings(),loadSkills()]);applyDefaultMode();const rows=await refreshConversations();if(rows.length)await openConversation(rows[0].id);else await newConversation();}catch(error){toast(error.message);}finally{state.initializing=false;}}
listen('retry-connect','click',initialize);listen('refresh-status','click',refreshStatus);listen('new-chat','click',newConversation);
document.querySelectorAll('.nav').forEach(button=>button.onclick=()=>showView(button.dataset.view));
document.querySelectorAll('[data-prompt]').forEach(button=>button.onclick=()=>{$('prompt').value=button.dataset.prompt;$('prompt').focus();});
listen('chat-form','submit',async e=>{e.preventDefault();const text=$('prompt').value.trim();if(!text||state.active)return;if(!state.cid)await newConversation();const job=await api('/api/conversations/'+state.cid+'/messages',{method:'POST',body:JSON.stringify({text,mode:$('execution-mode').value,attachments:state.files.map(f=>f.id)})});state.active=job.id;setBusy(true,'queued');$('prompt').value='';state.files=[];renderFiles();state.follow=true;await refreshConversations();});
listen('prompt','keydown',e=>{if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){e.preventDefault();$('chat-form').requestSubmit();}});
listen('stop-button','click',async()=>{if(state.active)await api('/api/jobs/'+state.active+'/stop',{method:'POST',body:'{}'});});
listen('attach-button','click',()=>$('attachment-input').click());
listen('attachment-input','change',async()=>{try{for(const file of $('attachment-input').files){if(file.size>25e6)throw new Error('Choose files below 25 MB.');const form=new FormData();form.append('file',file);const uploaded=await api('/api/conversations/'+state.cid+'/upload',{method:'POST',body:form});state.files.push(uploaded);renderFiles();}}finally{$('attachment-input').value='';}});
listen('execution-mode','change',()=>{$('autonomy-note').classList.toggle('hidden',$('execution-mode').value!=='autonomous');});
listen('settings-form','submit',async e=>{e.preventDefault();const data={default_execution_mode:$('default-mode').value,model:$('model').value,reasoning_effort:$('reasoning-effort').value,max_turns:$('unlimited-turns').checked?null:Number($('max-turns').value),task_timeout_minutes:Number($('timeout').value),max_budget_usd:$('budget-limit').value.trim()?Number($('budget-limit').value):null,read_roots:$('read-roots').value.split('\n').map(s=>s.trim()).filter(Boolean),browser_enabled:$('browser-enabled').checked,desktop_enabled:$('desktop-enabled').checked,capture_evidence:$('capture-evidence').checked};await api('/api/settings',{method:'PUT',body:JSON.stringify(data)});await loadSettings();applyDefaultMode();await refreshStatus();toast('Settings saved for the next task.');});
listen('new-skill','click',()=>{$('skill-name').value='';$('skill-content').value='---\nname: my-skill\ndescription: Describe when Clara should use this skill.\n---\n\nDescribe the outcome, business rules, required inputs and how to verify completion.\n';$('skill-name').focus();document.querySelectorAll('.skill-card').forEach(n=>n.classList.remove('selected'));});
listen('save-skill','click',async()=>{const name=$('skill-name').value.trim();await api('/api/skills/'+encodeURIComponent(name),{method:'PUT',body:JSON.stringify({content:$('skill-content').value})});await loadSkills();toast('Skill saved. Clara can discover it on the next task.');});
listen('import-skill','click',()=>$('skill-file').click());
listen('skill-file','change',async()=>{const file=$('skill-file').files[0];if(!file)return;try{const form=new FormData();form.append('file',file);const imported=await api('/api/skills/import',{method:'POST',body:form});await loadSkills();const skill=state.skills.find(s=>s.name===imported.name);if(skill){$('skill-name').value=skill.name;$('skill-content').value=skill.content;}toast('Skill imported. Review its instructions before using it.');}finally{$('skill-file').value='';}});
$('messages').addEventListener('wheel',()=>{state.follow=false;},{passive:true});
window.addEventListener('beforeunload',()=>state.es?.close());
initialize();

function setTurnLimitControl(inputId,checkboxId){const input=$(inputId),unlimited=$(checkboxId).checked;input.disabled=unlimited;input.required=!unlimited;if(!unlimited&&!input.value)input.value='40';}
listen('unlimited-turns','change',()=>setTurnLimitControl('max-turns','unlimited-turns'));

function applyDefaultMode(){$("execution-mode").value=state.settings?.default_execution_mode||"autonomous";$("autonomy-note").classList.toggle("hidden",$("execution-mode").value!=="autonomous");}
