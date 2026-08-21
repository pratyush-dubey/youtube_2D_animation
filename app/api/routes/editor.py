"""Small server-backed editor for the actual persisted animation timeline."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from app.config.settings import settings


router = APIRouter(prefix="/projects", tags=["production-editor"])


@router.get("/{project_id}/editor", response_class=HTMLResponse)
def production_editor(project_id: str):
    return HTMLResponse(_EDITOR_HTML.replace("__PROJECT_ID__", project_id))


@router.get("/{project_id}/media")
def production_media(project_id: str, path: str = Query(...)):
    root = (Path(settings.output_dir) / project_id).resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid media path")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(target)


_EDITOR_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Animation Production Editor</title>
<style>
:root{color-scheme:dark;--bg:#071016;--panel:#101c24;--line:#263743;--text:#eff7f7;--muted:#9ab0b6;--accent:#e9a840}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0,#17313b,#071016 50%);color:var(--text);font:15px/1.45 Inter,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:3;padding:20px 4vw;background:#071016e8;border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}h1{margin:0;font-size:23px}.sub{color:var(--muted);margin-top:4px}
main{padding:24px 4vw 60px;display:grid;gap:18px}.scene{background:linear-gradient(145deg,#12222b,#0b151c);border:1px solid var(--line);border-radius:15px;padding:18px;box-shadow:0 16px 50px #0005}
.top{display:grid;grid-template-columns:120px 1fr auto;gap:18px;align-items:start}.thumb{aspect-ratio:16/9;border-radius:9px;background:#05090c;display:grid;place-items:center;color:#59717a;overflow:hidden}.title{font-size:18px;font-weight:700}.meta{color:var(--muted);margin-top:4px}.score{color:#82d9a1;font-weight:750}
.shots{display:flex;gap:8px;overflow:auto;padding:14px 0}.shot{min-width:150px;border-left:3px solid var(--accent);background:#081117;padding:9px 11px;border-radius:6px}.shot b{display:block}.shot span{color:var(--muted);font-size:12px}
.controls{display:flex;gap:8px;flex-wrap:wrap}button,select{border:1px solid #334b57;background:#172a34;color:var(--text);padding:8px 11px;border-radius:7px;cursor:pointer}button:hover{border-color:var(--accent)}button.primary{background:var(--accent);color:#171006;border-color:var(--accent);font-weight:700}
video{width:100%;margin-top:14px;border-radius:10px;background:#000}.empty{padding:60px;text-align:center;color:var(--muted)}@media(max-width:700px){.top{grid-template-columns:1fr}.thumb{display:none}}
</style></head><body><header><h1>Cinematic Production Editor</h1><div class="sub">Project __PROJECT_ID__ · live scene graph, shots, layers, animation and audio</div></header><main id="app"><div class="empty">Loading production plan…</div></main>
<script>
const id='__PROJECT_ID__', api=`/api/projects/${id}`; const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function request(url,options){const r=await fetch(url,options);if(!r.ok)throw new Error(await r.text());return r.json()}
async function load(){const plan=await request(`${api}/production-plan`);document.querySelector('#app').innerHTML=plan.scenes.map(card).join('')||'<div class="empty">No scenes yet.</div>'}
function card(s){const shots=(s.shots||[]).map(x=>`<div class="shot"><b>${esc(x.id)} · ${esc(x.shot_type)}</b><span>${esc(x.duration)}s · ${esc(x.camera?.move)}<br>${esc(x.action)} · ${esc(x.expression)}</span></div>`).join('');return `<article class="scene" id="scene-${s.scene_id}"><div class="top"><div class="thumb">Scene ${s.scene_id}</div><div><div class="title">Scene ${s.scene_id}: ${esc(s.text_overlay||s.visual_description||'Visual beat')}</div><div class="meta">${esc(s.duration_seconds)}s · ${esc(s.emotion)} · ${esc(s.render_mode)} · ${(s.layers||[]).length} layers</div><div class="score">Animation quality ${esc(s.animation_quality?.score||0)}/100</div></div><select onchange="camera(${s.scene_id},this.value)"><option value="">Change camera…</option><option>slow_push</option><option>track_character</option><option>dolly_in</option><option>pan_left</option><option>pan_right</option><option>handheld</option><option>orbit_simulation</option></select></div><div class="shots">${shots}</div><div class="controls"><button class="primary" onclick="preview(${s.scene_id})">Preview</button><button onclick="regen(${s.scene_id},'background')">Regenerate Background</button><button onclick="regen(${s.scene_id},'character')">Regenerate Character</button><button onclick="regen(${s.scene_id},'voice')">Change Voice</button><button onclick="regen(${s.scene_id},'sfx')">Change SFX</button><button onclick="expression(${s.scene_id})">Change Expression</button><button onclick="regen(${s.scene_id},'scene')">Regenerate Scene</button></div><div class="player"></div></article>`}
async function preview(scene){const box=document.querySelector(`#scene-${scene} .player`);box.textContent='Rendering animated preview…';try{const x=await request(`${api}/scenes/${scene}/preview?quality=PREVIEW`,{method:'POST'});box.innerHTML=`<video controls autoplay src="${api}/media?path=${encodeURIComponent(x.preview_path.split(/[\\/]/).slice(-2).join('/'))}"></video>`}catch(e){box.textContent=e.message}}
async function regen(scene,component){await request(`${api}/scenes/${scene}/regenerate/${component}`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});await load()}
async function camera(scene,value){if(!value)return;await request(`${api}/scenes/${scene}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({camera:value})});await load()}
async function expression(scene){const value=prompt('Expression: neutral, happy, sad, angry, fear, surprised, confused, thinking');if(!value)return;await request(`${api}/scenes/${scene}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({expression:value})});await load()}
load().catch(e=>document.querySelector('#app').innerHTML=`<div class="empty">${esc(e.message)}</div>`)
</script></body></html>"""

