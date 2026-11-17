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
