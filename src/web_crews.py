"""
MeshCtx Web Crews — 对标 hermes-studio / penguin-harness 的写作+多agent Web UI
=============================================================================
Copyright (c) 2026 MeshCtx. ALL RIGHTS RESERVED.

新增页面（复用 web_ui._TEMPLATES / web_ui._render）：

  GET  /ui/crews        — Crew/Conductor 模板管理（7 Crew + 4 Conductor + 克隆 + 成本 + 运行）
  POST /ui/crews/clone  — 克隆模板
  POST /ui/crews/run    — 按模板运行一次 crew
  GET  /ui/agents       — 智能体库写作助手（角色模板起草 + 创建/编辑/克隆/删除）
  POST /ui/agents/create / clone / edit / delete
  GET  /ui/tuning       — Agent Tuning 技能包（4 skill + 自我进化闭环）
  GET  /ui/crews/dag    — DAG 可视化 + 实时活动流（activity feed）
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from .web_ui import _TEMPLATES, _render
from .core.agent_crew_templates import CrewTemplateEngine, CREW_TEMPLATES, CONDUCTOR_TEMPLATES
from .core.agent_writing_studio import AgentWritingStudio, ROLE_WRITING_TEMPLATES
from .core.agent_crew_cost_tracker import CrewCostTracker
from .core.agent_tuning_skills import AgentTuningSkillPack

logger = logging.getLogger("meshctx.webcrews")

router = APIRouter(prefix="/ui", tags=["Web Crews"])

_CSS = """
:root{--bg:#0f172a;--text:#e2e8f0;--muted:#64748b;--surface:#1e293b;--border:#334155;--accent:#6c5ce7;--green:#22c55e;--red:#dc2626;--yellow:#fbbf24}
/* 2026-08-26 004meshctx: 用户要求白底黑字 — crews/agents/tuning 浅色主题 */
[data-theme="light"]{--bg:#f8fafc;--text:#0f172a;--muted:#64748b;--surface:#ffffff;--border:#e2e8f0;--accent:#6c5ce7;--green:#16a34a;--red:#dc2626;--yellow:#d97706}
[data-theme="light"] h2{color:#6c5ce7}
[data-theme="light"] .tag.crew{color:#0369a1}[data-theme="light"] .tag.conductor{color:#b45309}
[data-theme="light"] .steps li{color:#475569}[data-theme="light"] .feed .item{color:#475569}
*{box-sizing:border-box}body{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:0;padding:0}
a{color:var(--accent);text-decoration:none}.wrap{max-width:1100px;margin:0 auto;padding:24px}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px}
h1{font-size:22px;margin:0}h2{font-size:17px;margin:24px 0 10px;color:#a5b4fc}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px}
.card h3{margin:0 0 6px;font-size:15px}.card .meta{color:var(--muted);font-size:12px;margin-bottom:8px}
.tag{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;margin-right:6px;border:1px solid var(--border)}
.tag.crew{color:#7dd3fc}.tag.conductor{color:#fbbf24}
.steps{list-style:none;padding:0;margin:0 0 10px}.steps li{font-size:13px;color:#94a3b8;padding:3px 0}
.btn{display:inline-block;background:var(--accent);color:#fff;border:none;border-radius:8px;padding:7px 14px;font-size:13px;cursor:pointer;text-decoration:none;margin-right:8px}
.btn.ghost{background:transparent;border:1px solid var(--border);color:var(--text)}
.btn.small{padding:4px 10px;font-size:12px}
form.inline{display:inline}
input,select,textarea{background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:13px;margin:4px 0}
textarea{width:100%;min-height:70px}
.notice{background:var(--surface);border-left:3px solid var(--green);padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.bar a{padding:7px 14px;border-radius:8px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-size:13px}
.bar a.on{background:var(--accent);border-color:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-weight:600}
.dag{display:flex;flex-direction:column;gap:8px;margin:14px 0}.dag .node{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 12px;display:flex;align-items:center;gap:8px}
.dag .node .dot{width:10px;height:10px;border-radius:50%;background:var(--green)}
.dag .arrow{color:var(--muted);padding-left:22px}
.feed{max-height:320px;overflow-y:auto;background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px}
.feed .item{padding:6px 0;border-bottom:1px dashed var(--border);font-size:13px;color:#94a3b8}
.feed .item b{color:var(--text)}
"""


def _ctx(request: Request, **extra):
    return {"title": "meshctx", **extra}


# ══════════════════════════════════════════════════════════════════
# 模板：crews.html
# ══════════════════════════════════════════════════════════════════
_TEMPLATES["crews.html"] = r"""<!DOCTYPE html>
<html lang="{{ __lang }}" dir="{{ 'rtl' if __lang == 'ar' else 'ltr' }}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ t('crew_title') }} - meshctx</title>
<style>__CSS__</style></head>
<script>
// 2026-08-26 004meshctx: 浅色主题 (用户要求白底黑字, 默认 light)
(function(){
  var s = localStorage.getItem('meshctx_theme');
  document.body.setAttribute('data-theme', (s === 'dark') ? 'dark' : 'light');
})();
</script>
<body><div class="wrap">
<header><h1>🧑‍🚀 {{ t('crew_title') }}</h1><div>
<a class="btn ghost" href="/ui/dashboard">← {{ t('dashboard') }}</a>
<a class="btn" href="/ui/crews/dag">📊 {{ t('crew_dag_title') }}</a>
</div></header>
<div class="bar">
<a class="on" href="/ui/crews">{{ t('crew_templates_label') }}</a>
<a href="/ui/agents">{{ t('agent_library_title') }}</a>
<a href="/ui/tuning">{{ t('tuning_title') }}</a>
</div>
{% if msg %}<div class="notice">✅ {{ msg }}</div>{% endif %}
{% if err %}<div class="notice" style="border-left-color:var(--red)">❌ {{ err }}</div>{% endif %}
<h2>{{ t('crew_templates_label') }} ({{ crew|length }})</h2>
<div class="grid">
{% for tpl in crew %}
<div class="card">
  <h3>{{ tpl.name }}</h3>
  <div class="meta"><span class="tag crew">{{ t('crew_type_label') }}</span>{{ t('crew_steps_label') }}: {{ tpl.steps|length }}</div>
  <ul class="steps">{% for s in tpl.steps %}<li>▸ {{ s.agent }} — {{ s.instruction[:48] }}…</li>{% endfor %}</ul>
  <div class="meta" style="margin-bottom:8px">{{ t('crew_est_cost_label') }}: ${{ '%.4f'|format(tpl.est_low) }} ~ ${{ '%.4f'|format(tpl.est_high) }}</div>
  <form class="inline" method="post" action="/ui/crews/run">
    <input type="hidden" name="name" value="{{ tpl.name }}">
    <input type="text" name="goal" placeholder="{{ t('crew_goal_placeholder') }}" required style="width:150px">
    <button class="btn small">{{ t('crew_run_btn') }}</button>
  </form>
  <form class="inline" method="post" action="/ui/crews/clone">
    <input type="hidden" name="name" value="{{ tpl.name }}">
    <input type="text" name="new_name" placeholder="{{ t('crew_clone_placeholder') }}" required style="width:130px">
    <button class="btn small ghost">{{ t('crew_clone_btn') }}</button>
  </form>
</div>
{% endfor %}
</div>
<h2>{{ t('crew_conductor_label') }} ({{ conductor|length }})</h2>
<div class="grid">
{% for tpl in conductor %}
<div class="card">
  <h3>{{ tpl.name }}</h3>
  <div class="meta"><span class="tag conductor">{{ t('crew_conductor_type_label') }}</span>{{ t('crew_steps_label') }}: {{ tpl.steps|length }}</div>
  <ul class="steps">{% for s in tpl.steps %}<li>▸ {{ s.agent }}</li>{% endfor %}</ul>
  <div class="meta" style="margin-bottom:8px">{{ t('crew_est_cost_label') }}: ${{ '%.4f'|format(tpl.est_low) }} ~ ${{ '%.4f'|format(tpl.est_high) }}</div>
  <form class="inline" method="post" action="/ui/crews/run">
    <input type="hidden" name="name" value="{{ tpl.name }}">
    <input type="text" name="goal" placeholder="{{ t('crew_goal_placeholder') }}" required style="width:150px">
    <button class="btn small">{{ t('crew_run_btn') }}</button>
  </form>
</div>
{% endfor %}
</div>
</div></body></html>""".replace("__CSS__", _CSS)

_TEMPLATES["crews_dag.html"] = r"""<!DOCTYPE html>
<html lang="{{ __lang }}" dir="{{ 'rtl' if __lang == 'ar' else 'ltr' }}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ t('crew_dag_title') }} - meshctx</title>
<style>__CSS__</style></head>
<script>
// 2026-08-26 004meshctx: 浅色主题 (用户要求白底黑字, 默认 light)
(function(){
  var s = localStorage.getItem('meshctx_theme');
  document.body.setAttribute('data-theme', (s === 'dark') ? 'dark' : 'light');
})();
</script>
<body><div class="wrap">
<header><h1>📊 {{ t('crew_dag_title') }}</h1><div><a class="btn ghost" href="/ui/crews">← {{ t('crew_templates_label') }}</a></div></header>
<div class="bar"><a href="/ui/crews">{{ t('crew_templates_label') }}</a><a class="on" href="/ui/crews/dag">{{ t('crew_dag_title') }}</a><a href="/ui/agents">{{ t('agent_library_title') }}</a><a href="/ui/tuning">{{ t('tuning_title') }}</a></div>
<h2>{{ t('crew_dag_pipeline_label') }}</h2>
<div class="dag">
{% for node in dag %}
  <div class="node"><span class="dot"></span><b>{{ node.agent }}</b> — {{ node.instruction[:60] }}…</div>
  {% if not loop.last %}<div class="arrow">↓</div>{% endif %}
{% endfor %}
</div>
<h2>🟢 {{ t('crew_activity_feed_label') }}</h2>
<div class="feed" id="feed">
{% for ev in feed %}
  <div class="item">[{{ ev.ts }}] <b>{{ ev.agent }}</b> — {{ ev.event }}</div>
{% endfor %}
</div>
<script>
// 轮询 activity feed（SSE 降级为 3s 轮询）
setInterval(function(){
  fetch('/ui/crews/feed').then(function(r){return r.json()}).then(function(d){
    var el = document.getElementById('feed');
    el.innerHTML = (d.feed||[]).map(function(ev){
      return '<div class="item">['+ev.ts+'] <b>'+ev.agent+'</b> — '+ev.event+'</div>';
    }).join('');
  }).catch(function(){});
}, 3000);
</script>
</div></body></html>""".replace("__CSS__", _CSS)

_TEMPLATES["agents_library.html"] = r"""<!DOCTYPE html>
<html lang="{{ __lang }}" dir="{{ 'rtl' if __lang == 'ar' else 'ltr' }}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ t('agent_library_title') }} - meshctx</title>
<style>__CSS__</style></head>
<script>
// 2026-08-26 004meshctx: 浅色主题 (用户要求白底黑字, 默认 light)
(function(){
  var s = localStorage.getItem('meshctx_theme');
  document.body.setAttribute('data-theme', (s === 'dark') ? 'dark' : 'light');
})();
</script>
<body><div class="wrap">
<header><h1>🤖 {{ t('agent_library_title') }}</h1><div><a class="btn ghost" href="/ui/dashboard">← {{ t('dashboard') }}</a></div></header>
<div class="bar"><a href="/ui/crews">{{ t('crew_templates_label') }}</a><a class="on" href="/ui/agents">{{ t('agent_library_title') }}</a><a href="/ui/tuning">{{ t('tuning_title') }}</a></div>
{% if msg %}<div class="notice">✅ {{ msg }}</div>{% endif %}
{% if err %}<div class="notice" style="border-left-color:var(--red)">❌ {{ err }}</div>{% endif %}
<h2>{{ t('agent_create_title') }}</h2>
<div class="card">
<form method="post" action="/ui/agents/create" style="display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end">
  <div><label>{{ t('agent_name_label') }}</label><br><input type="text" name="name" required></div>
  <div><label>{{ t('agent_role_label') }}</label><br>
    <select name="role">{% for r in roles %}<option value="{{ r }}">{{ r }}</option>{% endfor %}</select>
  </div>
  <div style="flex:1;min-width:200px"><label>{{ t('agent_domain_label') }}</label><br><input type="text" name="domain" style="width:100%"></div>
  <div><button class="btn">{{ t('agent_create_btn') }}</button></div>
</form>
</div>
<h2>{{ t('agent_builtin_label') }}</h2>
<table>
<tr><th>{{ t('agent_name_label') }}</th><th>{{ t('agent_role_label') }}</th><th>{{ t('agent_prompt_label') }}</th><th></th></tr>
{% for a in builtin %}
<tr><td>{{ a.name }}</td><td><span class="tag crew">{{ a.role }}</span></td><td style="color:#94a3b8">{{ a.system_prompt[:60] }}…</td>
<td><form class="inline" method="post" action="/ui/agents/clone"><input type="hidden" name="name" value="{{ a.name }}"><input type="text" name="new_name" placeholder="{{ t('crew_clone_placeholder') }}" style="width:110px"><button class="btn small ghost">{{ t('crew_clone_btn') }}</button></form></td></tr>
{% endfor %}
</table>
<h2>{{ t('agent_custom_label') }}</h2>
{% if custom %}
<table>
<tr><th>{{ t('agent_name_label') }}</th><th>{{ t('agent_role_label') }}</th><th>{{ t('agent_prompt_label') }}</th><th></th></tr>
{% for a in custom %}
<tr><td>{{ a.name }}</td><td><span class="tag conductor">{{ a.role }}</span></td><td style="color:#94a3b8">{{ a.system_prompt[:60] }}…</td>
<td><form class="inline" method="post" action="/ui/agents/delete"><input type="hidden" name="name" value="{{ a.name }}"><button class="btn small ghost" style="color:var(--red)">{{ t('delete') }}</button></form></td></tr>
{% endfor %}
</table>
{% else %}<p style="color:var(--muted)">{{ t('agent_custom_empty') }}</p>{% endif %}
</div></body></html>""".replace("__CSS__", _CSS)

_TEMPLATES["tuning.html"] = r"""<!DOCTYPE html>
<html lang="{{ __lang }}" dir="{{ 'rtl' if __lang == 'ar' else 'ltr' }}">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ t('tuning_title') }} - meshctx</title>
<style>__CSS__</style></head>
<script>
// 2026-08-26 004meshctx: 浅色主题 (用户要求白底黑字, 默认 light)
(function(){
  var s = localStorage.getItem('meshctx_theme');
  document.body.setAttribute('data-theme', (s === 'dark') ? 'dark' : 'light');
})();
</script>
<body><div class="wrap">
<header><h1>🎛️ {{ t('tuning_title') }}</h1><div><a class="btn ghost" href="/ui/dashboard">← {{ t('dashboard') }}</a></div></header>
<div class="bar"><a href="/ui/crews">{{ t('crew_templates_label') }}</a><a href="/ui/agents">{{ t('agent_library_title') }}</a><a class="on" href="/ui/tuning">{{ t('tuning_title') }}</a></div>
{% if msg %}<div class="notice">✅ {{ msg }}</div>{% endif %}
<h2>{{ t('tuning_skills_label') }}</h2>
<div class="grid">
{% for s in skills %}
<div class="card"><h3>🛠️ {{ s.skill }}</h3><div class="meta">{{ s.desc }}</div></div>
{% endfor %}
</div>
<h2>{{ t('tuning_loop_title') }}</h2>
<div class="card">
<form method="post" action="/ui/tuning/loop" style="display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end">
  <div><label>{{ t('agent_name_label') }}</label><br><input type="text" name="agent_name" required></div>
  <div><label>{{ t('agent_role_label') }}</label><br><select name="role">{% for r in roles %}<option value="{{ r }}">{{ r }}</option>{% endfor %}</select></div>
  <div style="flex:1;min-width:200px"><label>{{ t('agent_domain_label') }}</label><br><input type="text" name="domain" style="width:100%"></div>
  <div><label>{{ t('tuning_rounds_label') }}</label><br><input type="number" name="rounds" value="3" min="1" max="10" style="width:70px"></div>
  <div><button class="btn">{{ t('tuning_run_btn') }}</button></div>
</form>
</div>
{% if result %}
<h2>{{ t('tuning_result_title') }}</h2>
<div class="card" style="white-space:pre-wrap;font-family:monospace;font-size:12px">{{ result }}</div>
{% endif %}
</div></body></html>""".replace("__CSS__", _CSS)


# ══════════════════════════════════════════════════════════════════
# 路由
# ══════════════════════════════════════════════════════════════════

def _roles():
    return list(ROLE_WRITING_TEMPLATES.keys())


@router.get("/crews", response_class=HTMLResponse)
async def crews_page(request: Request):
    eng = CrewTemplateEngine()
    crew = [{"name": n, "steps": t.steps, "est_low": eng.estimate_cost(n)["est_cost_usd_low"],
             "est_high": eng.estimate_cost(n)["est_cost_usd_high"]}
            for n, t in CREW_TEMPLATES.items()]
    conductor = [{"name": n, "steps": t.steps, "est_low": eng.estimate_cost(n)["est_cost_usd_low"],
                  "est_high": eng.estimate_cost(n)["est_cost_usd_high"]}
                 for n, t in CONDUCTOR_TEMPLATES.items()]
    return _render("crews.html", {"crew": crew, "conductor": conductor}, request)


@router.post("/crews/clone")
async def crews_clone(request: Request, name: str = Form(...), new_name: str = Form(...)):
    eng = CrewTemplateEngine()
    try:
        eng.clone(name, new_name)
        msg = f"Cloned {name} → {new_name}"
    except Exception as e:
        msg, err = None, str(e)
        return _render("crews.html", {"crew": [], "conductor": [], "msg": None, "err": err}, request)
    return RedirectResponse("/ui/crews?msg=cloned", status_code=303)


@router.post("/crews/run")
async def crews_run(request: Request, name: str = Form(...), goal: str = Form(...)):
    eng = CrewTemplateEngine()
    try:
        res = eng.run(name, goal)
        return RedirectResponse(f"/ui/crews/dag?ran={name}", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/ui/crews?err={type(e).__name__}", status_code=303)


@router.get("/crews/dag", response_class=HTMLResponse)
async def crews_dag(request: Request, ran: str = ""):
    eng = CrewTemplateEngine()
    # 默认展示 conductor_deploy 的 DAG；若指定则展示该模板
    name = ran or "conductor_deploy"
    try:
        plan = eng.instantiate(name, "—")
    except Exception:
        plan = eng.instantiate("build", "—")
    tracker = CrewCostTracker()
    feed = tracker.get_feed() if hasattr(tracker, "get_feed") else []
    return _render("crews_dag.html", {"dag": plan, "feed": feed}, request)


@router.get("/crews/feed")
async def crews_feed(request: Request):
    tracker = CrewCostTracker()
    feed = tracker.get_feed() if hasattr(tracker, "get_feed") else []
    return {"feed": feed[-30:]}


@router.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request):
    studio = AgentWritingStudio()
    builtin = studio.list_builtin()
    custom = studio.list_custom()
    return _render("agents_library.html",
                   {"builtin": builtin, "custom": custom, "roles": _roles()}, request)


@router.post("/agents/create")
async def agents_create(request: Request, name: str = Form(...), role: str = Form(...), domain: str = Form("")):
    studio = AgentWritingStudio()
    try:
        draft = studio.draft_prompt(role, domain) if domain else studio.draft_prompt(role, name)
        studio.create_agent(name, role, draft.prompt)
    except Exception:
        pass
    return RedirectResponse("/ui/agents", status_code=303)


@router.post("/agents/clone")
async def agents_clone(request: Request, name: str = Form(...), new_name: str = Form(...)):
    studio = AgentWritingStudio()
    try:
        studio.clone_agent(name, new_name)
    except Exception:
        pass
    return RedirectResponse("/ui/agents", status_code=303)


@router.post("/agents/delete")
async def agents_delete(request: Request, name: str = Form(...)):
    studio = AgentWritingStudio()
    studio.delete_agent(name)
    return RedirectResponse("/ui/agents", status_code=303)


@router.get("/tuning", response_class=HTMLResponse)
async def tuning_page(request: Request):
    pack = AgentTuningSkillPack()
    return _render("tuning.html",
                   {"skills": pack.list_skills(), "roles": _roles(), "result": None}, request)


@router.post("/tuning/loop")
async def tuning_loop(request: Request, agent_name: str = Form(...), role: str = Form(...),
                      domain: str = Form(""), rounds: int = Form(3)):
    pack = AgentTuningSkillPack()
    try:
        result = pack.run_tuning_loop(agent_name, role, domain or agent_name,
                                      rounds=int(rounds), base_score=0.55)
        result_text = json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        result_text = f"Error: {e}"
    return _render("tuning.html",
                   {"skills": pack.list_skills(), "roles": _roles(), "result": result_text}, request)
