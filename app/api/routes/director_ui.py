"""Minimal dependency-free web UI for the AI Video Director."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["director-ui"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def director_home():
    return HTMLResponse(_SHELL.replace("__VIEW__", _CREATE_VIEW).replace("__PROJECT_ID__", ""))


@router.get("/projects/{project_id}", response_class=HTMLResponse, include_in_schema=False)
def director_project(project_id: str):
    return HTMLResponse(_SHELL.replace("__VIEW__", _PROJECT_VIEW).replace("__PROJECT_ID__", project_id))


_SHELL = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Video Director</title>
<style>
:root{--ink:#eaf0f4;--muted:#91a0aa;--line:#263642;--panel:#111c24;--accent:#ffb347;--good:#5ed19b;--bad:#ff786f;--bg:#071016;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:radial-gradient(circle at 80% -20%,#203b48 0,transparent 38%),radial-gradient(circle at 0 80%,#211d32 0,transparent 34%),var(--bg);font:15px/1.5 Inter,Segoe UI,sans-serif;min-height:100vh}
nav{height:68px;padding:0 max(24px,5vw);display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff12}.brand{font-weight:800;letter-spacing:.09em;font-size:14px}.brand i{color:var(--accent);font-style:normal}.advanced{color:var(--muted);text-decoration:none;font-size:13px}.advanced:hover{color:var(--ink)}
main{width:min(980px,calc(100% - 36px));margin:0 auto;padding:64px 0 90px}.eyebrow{color:var(--accent);font-weight:700;letter-spacing:.15em;text-transform:uppercase;font-size:11px}h1{font-size:clamp(38px,6vw,70px);line-height:1.02;letter-spacing:-.045em;margin:12px 0 18px}.lede{color:var(--muted);font-size:18px;max-width:650px;margin:0 0 36px}
.card{background:linear-gradient(145deg,#14232d,#0d171e);border:1px solid var(--line);border-radius:20px;padding:clamp(20px,4vw,38px);box-shadow:0 25px 80px #0008}label{display:block;font-weight:650;margin-bottom:9px}textarea,select,input{width:100%;border:1px solid #334957;background:#091218;color:var(--ink);border-radius:11px;padding:13px 14px;font:inherit;outline:none}textarea{min-height:145px;resize:vertical;font-size:17px}textarea:focus,select:focus,input:focus{border-color:var(--accent);box-shadow:0 0 0 3px #ffb34718}.options{display:grid;grid-template-columns:1fr 1fr 1.3fr;gap:13px;margin:20px 0 24px}.options label{color:var(--muted);font-size:12px}.options select{margin-top:7px;color:var(--ink)}
button{border:0;border-radius:11px;padding:14px 20px;font:700 14px inherit;letter-spacing:.04em;cursor:pointer}.primary{background:var(--accent);color:#211405;width:100%;box-shadow:0 10px 30px #ffb34724}.primary:disabled{opacity:.55;cursor:wait}.secondary{background:#1a2a34;color:var(--ink);border:1px solid #38505d}.danger{background:#2b1c20;color:#ffaca6;border:1px solid #6a3234}.error{color:#ff9e97;margin-top:14px;min-height:22px}
.project-head{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:30px}.project-head h1{font-size:clamp(32px,5vw,56px);margin-bottom:6px}.meta{color:var(--muted)}.state{color:var(--accent);font-weight:800;letter-spacing:.1em}.bar{height:7px;background:#1c2a33;border-radius:20px;overflow:hidden;margin:20px 0 32px}.bar span{display:block;height:100%;background:linear-gradient(90deg,#ff9f43,#ffd071);transition:width .4s}
.stage-list{display:grid;grid-template-columns:1fr 1fr;gap:1px 30px}.stage{display:grid;grid-template-columns:28px 1fr auto;align-items:center;padding:11px 0;border-bottom:1px solid #ffffff0c}.stage-icon{color:#60727d}.stage.complete .stage-icon{color:var(--good)}.stage.running .stage-icon,.stage.retrying .stage-icon{color:var(--accent)}.stage.failed .stage-icon{color:var(--bad)}.stage small{color:var(--muted)}
.result{display:none;margin-top:28px}.result.ready{display:block}.preview{width:100%;aspect-ratio:16/9;background:#020405;border-radius:14px;margin:18px 0}.final-grid{display:grid;grid-template-columns:180px 1fr;gap:22px}.thumb{width:100%;aspect-ratio:16/9;object-fit:cover;background:#071016;border-radius:9px}.tags{color:var(--muted);font-size:13px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}.actions button{width:auto}.change-box{display:none;margin-top:16px}.change-box.show{display:flex;gap:8px}.change-box input{flex:1}.notice{padding:13px 15px;background:#172731;border-left:3px solid var(--accent);border-radius:6px;margin-top:16px;color:var(--muted)}
@media(max-width:700px){main{padding-top:38px}.options,.stage-list,.final-grid{grid-template-columns:1fr}.project-head{display:block}.state{margin-top:12px}.change-box.show{display:block}.change-box button{margin-top:8px;width:100%}}
</style></head><body><nav><div class="brand"><i>AI</i> VIDEO DIRECTOR</div><a class="advanced" href="/character-studio">Advanced Mode ↗</a></nav><main>__VIEW__</main>
<script>const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));</script></body></html>'''


_CREATE_VIEW = r'''
<section><div class="eyebrow">One input · One button · Automated production</div><h1>What should I create?</h1><p class="lede">Describe the finished video. Your AI Director handles research, writing, visuals, animation, voice, sound, subtitles, quality control and publishing preparation.</p>
<form class="card" id="create"><label for="request">Your video request</label><textarea id="request" required minlength="10" placeholder="Create a 60-second cinematic documentary about…"></textarea>
<div class="options"><label>Duration<select id="duration"><option value="60">60-second test</option><option value="300">5 minutes</option><option value="600">10 minutes</option><option value="1200">20 minutes</option></select></label><label>Language<select id="language"><option>English</option><option>Hindi</option><option>Kannada</option><option>Tamil</option><option>Telugu</option></select></label><label>Style<select id="style"><option>Cinematic Documentary</option><option>Illustrated Explainer</option><option>Dramatic Biography</option><option>Educational Story</option></select></label></div>
<button class="primary" id="submit">CREATE VIDEO</button><div class="error" id="error"></div></form></section>
<script>document.querySelector('#create').addEventListener('submit',async e=>{e.preventDefault();const b=document.querySelector('#submit'),err=document.querySelector('#error');b.disabled=true;b.textContent='STARTING PRODUCTION…';err.textContent='';try{const r=await fetch('/api/director/videos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:document.querySelector('#request').value,duration_seconds:+document.querySelector('#duration').value,language:document.querySelector('#language').value,style:document.querySelector('#style').value})});if(!r.ok)throw new Error((await r.json()).detail||'Could not start production');const x=await r.json();location.href=x.url}catch(x){err.textContent=x.message;b.disabled=false;b.textContent='CREATE VIDEO'}})</script>'''


_PROJECT_VIEW = r'''
<section id="app"><div class="card">Loading production…</div></section>
<script>
const projectId='__PROJECT_ID__',endpoint=`/api/director/projects/${projectId}`;
let timer;
function duration(s){s=+s||0;return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`}
function icon(s){return s==='complete'?'✓':s==='running'?'●':s==='retrying'?'↻':s==='failed'?'!':'—'}
async function load(){try{const r=await fetch(endpoint);if(!r.ok)throw new Error('Project not found');const p=await r.json(),stages=Object.values(p.stages||{}),a=p.artifacts||{},ready=['VIDEO_READY','APPROVED','SCHEDULED'].includes(p.state);document.querySelector('#app').innerHTML=`
<div class="project-head"><div><div class="eyebrow">Project ${esc(projectId)}</div><h1>${esc(a.title||shortTitle(p.request))}</h1><div class="meta">${duration(p.duration_seconds||p.request?.duration_seconds)} · ${esc(p.language||p.request?.language)} · ${esc(p.style||p.request?.style)}</div></div><div class="state">${esc(String(p.state).replaceAll('_',' '))}</div></div>
<div class="card"><b>Production</b><div class="bar"><span style="width:${p.progress||0}%"></span></div><div class="stage-list">${stages.map(s=>`<div class="stage ${esc(s.status)}"><span class="stage-icon">${icon(s.status)}</span><span>${esc(s.label)}</span><small>${s.status==='running'?`${s.progress||0}%`:esc(s.status)}</small></div>`).join('')}</div>${p.requires_attention?`<div class="notice">${esc(stages.find(s=>s.message)?.message||'Production needs attention. Open Advanced Mode for the quality report and technical controls.')}</div>`:''}</div>
<div class="card result ${ready?'ready':''}"><div class="eyebrow">Video ready</div><h2>Final package</h2>${a.video?`<video class="preview" controls poster="${a.thumbnail||''}" src="${a.video}"></video>`:''}<div class="final-grid">${a.thumbnail?`<img class="thumb" src="${a.thumbnail}" alt="Selected thumbnail">`:'<div class="thumb"></div>'}<div><h3>${esc(a.title||'Title generated')}</h3><p>${esc(a.description||'Description generated from the completed video.')}</p><div class="tags">${(a.tags||[]).map(esc).join(' · ')}</div><p><b>Quality score: ${esc(a.quality_score??'—')}/100</b></p></div></div><div class="actions"><button class="primary" style="width:auto" onclick="approve()">APPROVE & SCHEDULE</button><button class="secondary" onclick="toggleChange()">REQUEST CHANGES</button><a class="advanced" href="/api/projects/${projectId}/editor"><button class="secondary">OPEN EDITOR</button></a></div><div class="change-box" id="changes"><input id="changeText" placeholder="Make the narration more dramatic."><button class="secondary" onclick="sendChange()">SEND TO DIRECTOR</button></div><div id="notice"></div></div>`;
if(!ready&&p.state!=='REQUIRES_ATTENTION'&&p.state!=='EDITOR_REVIEW')timer=setTimeout(load,2000)}catch(e){document.querySelector('#app').innerHTML=`<div class="card error">${esc(e.message)}</div>`}}
function shortTitle(x){const s=typeof x==='string'?x:(x?.request||'Untitled video');return s.replace(/^create\s+(a\s+)?/i,'').slice(0,80)}
function toggleChange(){document.querySelector('#changes').classList.toggle('show')}
async function sendChange(){const input=document.querySelector('#changeText');if(!input.value.trim())return;const r=await fetch(`${endpoint}/changes`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:input.value})});if(r.ok){document.querySelector('#notice').innerHTML='<div class="notice">Revision queued. The Director will update only the affected production work.</div>';setTimeout(()=>location.reload(),900)}}
async function approve(){const r=await fetch(`${endpoint}/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}),x=await r.json();document.querySelector('#notice').innerHTML=`<div class="notice">${esc(x.message||x.detail)}</div>`}
load();
</script>'''
