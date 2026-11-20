const chat = document.getElementById('chat');
const form = document.getElementById('chatForm');
const question = document.getElementById('question');
const trace = document.getElementById('trace');
const sourceUsed = document.getElementById('sourceUsed');

function toStr(v){
  if (typeof v === 'string') return v;
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}
function escapeHtml(s=''){
  s = toStr(s);
  return s.replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}
function formatText(s=''){return escapeHtml(s).replace(/\n/g,'<br>');}
function addMessage(role, text, source='', citations=[]){
  const wrap=document.createElement('div'); wrap.className=`message ${role}`;
  const citeHtml=citations.length?`<div class="citations"><strong>Sources</strong><br>${citations.map(c=>c.url?`<a href="${escapeHtml(c.url)}" target="_blank" rel="noopener">${escapeHtml(c.title)}</a>`:escapeHtml(c.title)).join('<br>')}</div>`:'';
  wrap.innerHTML=`<div class="avatar">AI</div><div class="bubble">${formatText(text)}${source?`<div class="answer-source">Source: ${escapeHtml(source)}</div>`:''}${citeHtml}</div>`;
  chat.appendChild(wrap); chat.scrollTop=chat.scrollHeight;
}
function renderTrace(items=[]){
  trace.innerHTML=items.length?items.map(x=>`<div class="trace-item">${escapeHtml(x)}</div>`).join(''):'<div class="empty">No trace.</div>';
}
async function askAgent(q){
  addMessage('user',q); question.value=''; renderTrace(['Running LangGraph workflow...']); sourceUsed.textContent='Running';
  const btn=form.querySelector('button'); btn.disabled=true;
  try{
    const res=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})});
    const data=await res.json(); if(!res.ok) throw new Error(data.detail||'Request failed');
    addMessage('assistant',data.answer,data.source_used,data.citations||[]); renderTrace(data.trace||[]); sourceUsed.textContent=toStr(data.source_used);
  }catch(e){addMessage('assistant',`Error: ${e.message}`); renderTrace(['Request failed']); sourceUsed.textContent='Error';}
  finally{btn.disabled=false;}
}
form.addEventListener('submit',e=>{e.preventDefault(); const q=question.value.trim(); if(q) askAgent(q);});
document.querySelectorAll('.example').forEach(b=>b.addEventListener('click',()=>askAgent(b.textContent.trim())));

const modal=document.getElementById('uploadModal');
document.getElementById('openUpload').onclick=()=>modal.classList.remove('hidden');
document.getElementById('closeUpload').onclick=()=>modal.classList.add('hidden');
document.getElementById('uploadBtn').onclick=async()=>{
  const file=document.getElementById('fileInput').files[0]; const key=document.getElementById('adminKey').value; const status=document.getElementById('uploadStatus');
  if(!file){status.textContent='Choose a file first.'; return;}
  status.textContent='Indexing document...'; const fd=new FormData(); fd.append('file',file);
  try{const r=await fetch('/api/ingest',{method:'POST',headers:{'X-Admin-Key':key},body:fd}); const d=await r.json(); if(!r.ok) throw new Error(d.detail||'Upload failed'); status.textContent=`Indexed ${d.file}: ${d.chunks} chunks.`;}catch(e){status.textContent=`Error: ${e.message}`;}
};
// ---------------- Authorization-Aware RAG: JWT auth, role display, audit ----------------
let token = localStorage.getItem('rag_token') || '';
let me = null;

const loginModal = document.getElementById('loginModal');
const auditModal = document.getElementById('auditModal');

function authHeaders(extra={}){
  return token ? { 'Authorization': 'Bearer ' + token, ...extra } : extra;
}

function renderUser(){
  const badge = document.getElementById('userBadge');
  const logout = document.getElementById('logoutBtn');
  const auditBtn = document.getElementById('openAudit');
  if(me){
    badge.innerHTML = `<strong>${escapeHtml(me.username)}</strong><br>Roles: ${me.roles.map(escapeHtml).join(', ')}<br>Doc access: ${me.allowed_departments.map(escapeHtml).join(', ')}`;
    logout.classList.remove('hidden');
    if(me.is_admin) auditBtn.classList.remove('hidden');
    // department owners can review their departments' escalations
    if(me.is_admin || me.allowed_departments.some(d => d !== 'GENERAL')) document.getElementById('openEscalations').classList.remove('hidden');
  } else {
    badge.textContent = 'Not signed in';
    logout.classList.add('hidden');
    auditBtn.classList.add('hidden');
  }
}

async function tryRestoreSession(){
  if(!token){ loginModal.classList.remove('hidden'); return; }
  try{
    const r = await fetch('/api/auth/me', {headers: authHeaders()});
    if(!r.ok) throw new Error();
    me = await r.json(); renderUser();
  }catch{ token=''; localStorage.removeItem('rag_token'); loginModal.classList.remove('hidden'); }
}

document.getElementById('loginBtn').onclick = async () => {
  const u = document.getElementById('loginUser').value.trim();
  const p = document.getElementById('loginPass').value;
  const status = document.getElementById('loginStatus');
  try{
    const r = await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:u, password:p})});
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || 'Login failed');
    token = d.access_token; localStorage.setItem('rag_token', token);
    me = {username: d.username, roles: d.roles, allowed_departments: d.allowed_departments, is_admin: d.roles.includes('Security Admin')};
    renderUser(); loginModal.classList.add('hidden');
    addMessage('assistant', `Signed in as ${me.username}. You can retrieve documents from: ${me.allowed_departments.join(', ')}.`);
  }catch(e){ status.textContent = 'Error: ' + e.message; }
};

document.getElementById('logoutBtn').onclick = () => {
  token=''; me=null; localStorage.removeItem('rag_token'); renderUser(); loginModal.classList.remove('hidden');
};

document.getElementById('openAudit').onclick = async () => {
  auditModal.classList.remove('hidden');
  const box = document.getElementById('auditContent');
  try{
    const r = await fetch('/api/admin/audit', {headers: authHeaders()});
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || 'Failed');
    box.innerHTML = '<pre>' + escapeHtml(JSON.stringify(d, null, 2)) + '</pre>';
  }catch(e){ box.textContent = 'Error: ' + e.message; }
};
document.getElementById('closeAudit').onclick = () => auditModal.classList.add('hidden');

// Patch askAgent to include the JWT and render access scope
const _askAgent = askAgent;
askAgent = async function(q){
  if(!token){ loginModal.classList.remove('hidden'); return; }
  addMessage('user', q); question.value=''; renderTrace(['Running LangGraph workflow...']); sourceUsed.textContent='Running';
  const btn = form.querySelector('button'); btn.disabled = true;
  try{
    const res = await fetch('/api/chat', {method:'POST', headers: authHeaders({'Content-Type':'application/json'}), body: JSON.stringify({question: q})});
    const data = await res.json(); if(!res.ok) throw new Error(data.detail || 'Request failed');
    addMessage('assistant', data.answer, data.source_used, data.citations || []);
    renderTrace(data.trace || []);
    sourceUsed.textContent = toStr(data.source_used);
    if(data.access_scope){
      renderTrace([...(data.trace||[]), `Access scope: ${data.access_scope.username} [${data.access_scope.allowed_departments.join(',')}] → saw docs from: ${data.access_scope.document_departments_seen.join(', ') || 'none'}`]);
    }
    if(data.confidence !== null && data.confidence !== undefined){
      sourceUsed.textContent = `${toStr(data.source_used)} (confidence ${data.confidence}/100)`;
    }
    if(data.tool_calls && data.tool_calls.length){
      const tc = data.tool_calls[0];
      renderTrace([...(data.trace||[]), `Tool → ${tc.tool}(${JSON.stringify(tc.arguments||{})})${tc.pending_action ? ' → approval ' + tc.pending_action : ''}${tc.denied ? ' → RBAC DENIED' : ''}`]);
    }
  }catch(e){ addMessage('assistant', `Error: ${e.message}`); renderTrace(['Request failed']); sourceUsed.textContent = 'Error'; }
  finally{ btn.disabled = false; }
};

// Patch upload to send department + JWT instead of admin key
document.getElementById('uploadBtn').onclick = async () => {
  const file = document.getElementById('fileInput').files[0];
  const dept = document.getElementById('deptSelect').value;
  const status = document.getElementById('uploadStatus');
  if(!file){ status.textContent = 'Choose a file first.'; return; }
  status.textContent = 'Indexing document...';
  const fd = new FormData(); fd.append('file', file); fd.append('department', dept);
  try{
    const r = await fetch('/api/ingest', {method:'POST', headers: authHeaders(), body: fd});
    const d = await r.json(); if(!r.ok) throw new Error(d.detail || 'Upload failed');
    status.textContent = `Indexed ${d.file} as [${d.department}]: ${d.chunks} chunks.`;
  }catch(e){ status.textContent = 'Error: ' + e.message; }
};

tryRestoreSession();

// ---------------- Human-in-the-Loop Escalations ----------------
const escModal = document.getElementById('escalationModal');
const myTicketsModal = document.getElementById('myTicketsModal');

// Show confidence in trace panel and surface escalation refs
const _renderTraceOrig = renderTrace;
function _askAgentDone(data){
  if(data.confidence !== null && data.confidence !== undefined){
    sourceUsed.textContent = `${toStr(data.source_used)} (confidence ${data.confidence}/100)`;
  }
}

document.getElementById('openEscalations').onclick = async () => {
  escModal.classList.remove('hidden');
  const box = document.getElementById('escalationList');
  box.textContent = 'Loading…';
  try{
    const r = await fetch('/api/escalations', {headers: authHeaders()});
    const d = await r.json(); if(!r.ok) throw new Error(d.detail||'Failed');
    const ra = await fetch('/api/escalations/actions', {headers: authHeaders()});
    const da = await ra.json(); if(!ra.ok) throw new Error(da.detail||'Failed');
    let html = '';
    if(da.actions.length){
      html += '<h3>Pending Agent Actions</h3>' + da.actions.map(a => `
      <div class="trace-item" style="text-align:left">
        <strong>${escapeHtml(a.action_ref)}</strong> [${escapeHtml(a.department)}] — ${escapeHtml(a.status)}<br>
        <em>Tool:</em> ${escapeHtml(a.tool_name)}<br>
        <em>Args:</em> ${escapeHtml(JSON.stringify(a.arguments))}<br>
        <em>Requested by:</em> ${escapeHtml(a.username)}
        ${a.status==='pending_approval' ? `
          <textarea id="acmt-${escapeHtml(a.action_ref)}" rows="2" placeholder="Reviewer comment" style="width:100%"></textarea>
          <button onclick="reviewAction('${escapeHtml(a.action_ref)}','approved')">Approve & Execute</button>
          <button onclick="reviewAction('${escapeHtml(a.action_ref)}','rejected')">Reject</button>` :
          `<em>${escapeHtml(a.resolution||'')}</em> by ${escapeHtml(a.reviewer||'')} — result: ${escapeHtml((a.execution_result||'').slice(0,120))}`}
      </div>`).join('');
    }
    if(d.tickets.length){
      html += '<h3>Answer Escalations</h3>' + d.tickets.map(t => `
      <div class="trace-item" style="text-align:left">
        <strong>${escapeHtml(t.ticket_ref)}</strong> [${escapeHtml(t.department)}] conf ${t.confidence}/100 — ${escapeHtml(t.status)}<br>
        <em>Q:</em> ${escapeHtml(t.question)}<br>
        <em>Draft:</em> ${escapeHtml((t.draft_answer||'').slice(0,300))}<br>
        ${t.status==='pending' ? `
          <textarea id="cmt-${escapeHtml(t.ticket_ref)}" rows="2" placeholder="Reviewer comment" style="width:100%"></textarea>
          <button onclick="reviewTicket('${escapeHtml(t.ticket_ref)}','approved')">Approve</button>
          <button onclick="reviewTicket('${escapeHtml(t.ticket_ref)}','rejected')">Reject</button>` :
          `<em>${escapeHtml(t.resolution||'')}</em> by ${escapeHtml(t.reviewer||'')}: ${escapeHtml(t.reviewer_comment||'')}`}
      </div>`).join('');
    }
    box.innerHTML = html || '<p>No escalations or pending actions. 🎉</p>';
  }catch(e){ box.textContent = 'Error: ' + e.message; }
};
document.getElementById('closeEscalations').onclick = () => escModal.classList.add('hidden');

window.reviewAction = async function(ref, resolution){
  const comment = document.getElementById('acmt-'+ref)?.value || '';
  try{
    const r = await fetch(`/api/escalations/actions/${ref}/review`, {method:'POST', headers: authHeaders({'Content-Type':'application/json'}), body: JSON.stringify({resolution, comment})});
    const d = await r.json(); if(!r.ok) throw new Error(d.detail||'Failed');
    if(d.action && d.action.execution_result){ alert('Executed: ' + d.action.execution_result.slice(0,200)); }
    document.getElementById('openEscalations').click();
  }catch(e){ alert('Review failed: ' + e.message); }
};

window.reviewTicket = async function(ref, resolution){
  const comment = document.getElementById('cmt-'+ref)?.value || '';
  try{
    const r = await fetch(`/api/escalations/${ref}/review`, {method:'POST', headers: authHeaders({'Content-Type':'application/json'}), body: JSON.stringify({resolution, comment})});
    const d = await r.json(); if(!r.ok) throw new Error(d.detail||'Failed');
    document.getElementById('openEscalations').click(); // refresh list
  }catch(e){ alert('Review failed: ' + e.message); }
};

document.getElementById('openMyTickets').onclick = async () => {
  if(!token){ loginModal.classList.remove('hidden'); return; }
  myTicketsModal.classList.remove('hidden');
  const box = document.getElementById('myTicketsList');
  box.textContent = 'Loading…';
  try{
    const r = await fetch('/api/escalations/mine', {headers: authHeaders()});
    const d = await r.json(); if(!r.ok) throw new Error(d.detail||'Failed');
    box.innerHTML = d.tickets.length ? d.tickets.map(t => `
      <div class="trace-item" style="text-align:left">
        <strong>${escapeHtml(t.ticket_ref)}</strong> — ${escapeHtml(t.status)}${t.resolution ? ' ('+escapeHtml(t.resolution)+' by '+escapeHtml(t.reviewer||'')+')' : ''}<br>
        ${escapeHtml(t.question)}
      </div>`).join('') : '<p>No escalated questions yet.</p>';
  }catch(e){ box.textContent = 'Error: ' + e.message; }
};
document.getElementById('closeMyTickets').onclick = () => myTicketsModal.classList.add('hidden');

// Patch askAgent once more to include confidence display
const _prevAsk = askAgent;
askAgent = async function(q){
  await _prevAsk(q);
};
