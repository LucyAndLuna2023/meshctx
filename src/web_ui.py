"""
meshctx Web 管理界面
FastAPI + Jinja2 DictLoader（模板内嵌，适配 PyInstaller）
"""
import sys
import yaml
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from jinja2 import Environment, DictLoader

# ── 内嵌模板（绕过 PyInstaller 文件系统问题）───────────────────
_TEMPLATES = {}

_TEMPLATES["base.html"] = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - meshctx</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }
        .header { background: #1e293b; border-bottom: 1px solid #334155; padding: 16px 24px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
        .header h1 { font-size: 20px; color: #38bdf8; }
        .nav { display: flex; gap: 8px; flex-wrap: wrap; }
        .nav a { color: #94a3b8; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 14px; transition: all .2s; }
        .nav a:hover, .nav a.active { background: #334155; color: #e2e8f0; }
        .main { padding: 24px; max-width: 1400px; margin: 0 auto; }
        .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 16px; }
        .card h2 { font-size: 18px; margin-bottom: 12px; color: #f1f5f9; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; text-align: center; }
        .stat-card .value { font-size: 32px; font-weight: 700; color: #38bdf8; }
        .stat-card .label { font-size: 13px; color: #64748b; margin-top: 4px; }
        .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .badge-active { background: #065f46; color: #6ee7b7; }
        .badge-inactive { background: #451a03; color: #fbbf24; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; font-size: 14px; }
        th { color: #64748b; font-weight: 600; }
        tr:hover { background: #1a2332; }
        .btn { display: inline-block; padding: 8px 16px; border-radius: 6px; font-size: 13px; border: none; cursor: pointer; text-decoration: none; transition: all .2s; }
        .btn-primary { background: #2563eb; color: white; }
        .btn-primary:hover { background: #1d4ed8; }
        .btn-danger { background: #dc2626; color: white; }
        .btn-danger:hover { background: #b91c1c; }
        input, textarea, select { background: #0f172a; border: 1px solid #334155; color: #e2e8f0; padding: 8px 12px; border-radius: 6px; font-size: 14px; width: 100%; }
        input:focus, textarea:focus, select:focus, button:focus-visible { border-color: #2563eb; outline: 2px solid #8b5cf6; outline-offset: 2px; }
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 4px; }
        .empty { text-align: center; color: #64748b; padding: 40px; }
        .flash { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
        .flash-success { background: #065f46; color: #6ee7b7; }
        .flash-error { background: #7f1d1d; color: #fca5a5; }
        a { color: #38bdf8; text-decoration: none; }
        a:hover { text-decoration: underline; }
        /* 亮色主题 */
        body.light { background:#f8fafc; color:#1e293b; }
        body.light .header { background:#fff; border-bottom:1px solid #e2e8f0; }
        body.light .card { background:#fff; border:1px solid #e2e8f0; }
        body.light .stat-card { background:#fff; border:1px solid #e2e8f0; }
        body.light .stat-card .value { color:#2563eb; }
        body.light .stat-card .label { color:#64748b; }
        body.light th, body.light td { border-bottom:1px solid #e2e8f0; }
        body.light th { color:#64748b; }
        body.light tr:hover { background:#f1f5f9; }
        body.light input, body.light textarea, body.light select { background:#fff; border:1px solid #e2e8f0; color:#1e293b; }
        body.light #messages { background:#f8fafc; border-color:#e2e8f0; }
        body.light .flash-success { background:#dcfce7; color:#166534; }
        body.light .flash-error { background:#fef2f2; color:#991b1b; }
        body.light a { color:#2563eb; }
        .cursor { display:inline-block;width:2px;height:1em;background:#38bdf8;animation:blink 1s infinite;vertical-align:text-bottom;margin-left:2px; } @keyframes blink { 0%,50% {opacity:1} 51%,100% {opacity:0} }
        /* ── 移动端响应式 (v2.19) ── */
        @media (max-width: 768px) {
            .header { padding: 12px 16px; flex-direction: column; align-items: flex-start; }
            .header h1 { font-size: 18px; }
            .nav { gap: 4px; }
            .nav a { padding: 5px 10px; font-size: 12px; }
            .main { padding: 16px; }
            .stats { grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
            .stat-card { padding: 14px; }
            .stat-card .value { font-size: 24px; }
            .card { padding: 14px; }
            table { font-size: 12px; }
            th, td { padding: 8px 10px; }
        }
        @media (max-width: 480px) {
            .nav { flex-direction: column; width: 100%; }
            .nav a { width: 100%; text-align: center; }
            .stats { grid-template-columns: 1fr 1fr; gap: 8px; }
            .stat-card .value { font-size: 20px; }
        }
    </style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
</head>
<body>
<div class="header">
    <h1>🧠 meshctx</h1>
    <div class="nav">
        <a href="/ui/" class="{% if request.url.path == '/ui/' %}active{% endif %}">仪表板</a>
        <a href="/ui/projects" class="{% if '/ui/projects' in request.url.path %}active{% endif %}">项目</a>
        <a href="/ui/memories" class="{% if '/ui/memories' in request.url.path %}active{% endif %}">记忆</a>
        <a href="/ui/continuity" class="{% if '/ui/continuity' in request.url.path %}active{% endif %}">连续性</a>
        <a href="/ui/chat" class="{% if '/ui/chat' in request.url.path %}active{% endif %}">Chat</a>
        <a href="/ui/setup" class="{% if '/ui/setup' in request.url.path %}active{% endif %}">Setup</a>
        <a href="/ui/dashboard" class="{% if '/ui/dashboard' in request.url.path %}active{% endif %}">📊</a>
        <a href="/ui/plugins" class="{% if '/ui/plugins' in request.url.path %}active{% endif %}">🔌 插件</a>
        <a href="/docs" target="_blank" class="" style="color:#f59e0b;">📚 API</a>
    </div>
    <div style="margin-left:auto;display:flex;align-items:center;gap:4px;">
        <select id="langSelect" onchange="switchLang(this.value)" 
                style="background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 8px;border-radius:4px;font-size:12px;cursor:pointer;">
            <option value="zh">中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
            <option value="ko">한국어</option>
            <option value="fr">Français</option>
            <option value="de">Deutsch</option>
            <option value="es">Español</option>
        </select>
        <button onclick="toggleTheme()" style="background:transparent;border:1px solid #334155;color:#94a3b8;padding:4px 8px;border-radius:4px;font-size:12px;cursor:pointer;margin-left:4px;" title="切换主题">🌓</button>
    </div>
</div>
<div class="main">
{% block content %}{% endblock %}
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.0/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script>
marked.setOptions({breaks:true, gfm:true});
hljs.configure({languages:['python','javascript','bash','json','yaml','sql','css','html','xml','java','go','rust','cpp','typescript','shell']});

// Language switcher — localStorage + server sync
function switchLang(lang) {
    localStorage.setItem('meshctx_lang', lang);
    fetch('/api/lang/set', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({lang:lang})})
        .then(function(){ location.reload(); })
        .catch(function(){ location.reload(); });
}
(function(){
    // Theme init on load
(function(){
    var theme = localStorage.getItem('meshctx_theme');
    if (theme === 'light') document.body.classList.add('light');
})();
var saved = localStorage.getItem('meshctx_lang') || 'zh';
    var sel = document.getElementById('langSelect');
    if (sel) sel.value = saved;
})();
</script>
</body>
</html>"""

_TEMPLATES["dashboard.html"] = r"""{% extends "base.html" %}
{% block content %}
{% if total_projects == 0 %}
<div class="card" style="background:linear-gradient(135deg,#1e3a5f,#1e293b);border:1px solid #38bdf8;margin-bottom:20px;">
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
        <div style="font-size:40px;">🔑</div>
        <div style="flex:1;">
            <h2 style="margin:0;color:#38bdf8;">欢迎使用 meshctx！</h2>
            <p style="color:#94a3b8;margin:8px 0 0;">首次使用需要配置 AI 模型 API 密钥才能开始。</p>
        </div>
        <a href="/ui/setup" class="btn btn-primary" style="font-size:15px;padding:12px 24px;white-space:nowrap;">⚙️ 配置 API 密钥</a>
    </div>
</div>
{% endif %}
<div class="stats">
    <div class="stat-card"><div class="value">{{ total_projects }}</div><div class="label">项目</div></div>
    <div class="stat-card"><div class="value">{{ total_conversations }}</div><div class="label">会话</div></div>
    <div class="stat-card"><div class="value">{{ total_memories }}</div><div class="label">记忆</div></div>
    <div class="stat-card"><div class="value">{{ total_agents }}</div><div class="label">Agent</div></div>
    <div class="stat-card"><div class="value">{{ total_sessions }}</div><div class="label">活跃会话</div></div>
</div>

<h2 style="margin-bottom:16px;">📊 项目概览</h2>
{% if project_data %}
<table>
    <thead><tr><th>项目</th><th>状态</th><th>会话</th><th>记忆</th><th>连续性</th><th>更新时间</th></tr></thead>
    <tbody>
    {% for d in project_data %}
    <tr>
        <td><a href="/ui/projects/{{ d.project.id }}">{{ d.project.name }}</a></td>
        <td><span class="badge {% if d.project.status == 'active' %}badge-active{% else %}badge-inactive{% endif %}">{{ d.project.status }}</span></td>
        <td>{{ d.conv_count }}</td>
        <td>{{ d.mem_count }}</td>
        <td><span style="color:{{ continuity_color(d.continuity.continuity_score) }}">{{ continuity_label(d.continuity.continuity_score) }}</span></td>
        <td>{{ d.project.updated_at }}</td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<div class="empty">📭 暂无项目，<a href="/ui/projects">创建一个</a></div>
{% endif %}
{% endblock %}"""

_TEMPLATES["projects.html"] = r"""{% extends "base.html" %}
{% block content %}
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2>📁 项目管理</h2>
    <button class="btn btn-primary" onclick="document.getElementById('createForm').style.display='block'">+ 新建项目</button>
</div>

<div id="createForm" class="card" style="display:none;">
    <h2>新建项目</h2>
    <form method="POST" action="/ui/projects/create">
        <div class="form-group"><label>名称</label><input name="name" required></div>
        <div class="form-group"><label>描述</label><textarea name="description" rows="2"></textarea></div>
        <div class="form-group"><label>标签（逗号分隔）</label><input name="tags"></div>
        <button type="submit" class="btn btn-primary">创建</button>
    </form>
</div>

{% if projects %}
<table>
    <thead><tr><th>名称</th><th>描述</th><th>会话</th><th>记忆</th><th>连续性</th><th>操作</th></tr></thead>
    <tbody>
    {% for p in projects %}
    <tr>
        <td><a href="/ui/projects/{{ p.project.id }}">{{ p.project.name }}</a></td>
        <td>{{ truncate(p.project.description or '-') }}</td>
        <td>{{ p.conv_count }}</td>
        <td>{{ p.mem_count }}</td>
        <td><span style="color:{{ continuity_color(p.continuity.continuity_score) }}">{{ continuity_label(p.continuity.continuity_score) }}</span></td>
        <td>
            <form method="POST" action="/ui/projects/{{ p.project.id }}/delete" style="display:inline" onsubmit="return confirm('确定删除?')">
                <button class="btn btn-danger" style="padding:4px 10px;font-size:12px;">删除</button>
            </form>
        </td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<div class="empty">📭 暂无项目</div>
{% endif %}
{% endblock %}"""

_TEMPLATES["project_detail.html"] = r"""{% extends "base.html" %}
{% block content %}
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2>📁 {{ project.name }}</h2>
    <span class="badge {% if project.status == 'active' %}badge-active{% else %}badge-inactive{% endif %}">{{ project.status }}</span>
</div>
<p style="color:#94a3b8;margin-bottom:16px;">{{ project.description or '无描述' }}</p>

<div class="card">
    <h2>📈 连续性</h2>
    <p>得分: <span style="color:{{ continuity_color(continuity.continuity_score) }};font-size:24px;font-weight:700;">{{ "%.2f"|format(continuity.continuity_score) }}</span>
    — {{ continuity_label(continuity.continuity_score) }}</p>
    {% if continuity.last_active %}<p style="color:#64748b;font-size:13px;">最后活动: {{ format_dt(continuity.last_active) }}</p>{% endif %}
</div>

<div class="card">
    <h2>💬 会话 ({{ conversations|length }})</h2>
    {% if conversations %}
    <table>
        <thead><tr><th>标题</th><th>消息</th><th>活跃Agent</th><th>更新时间</th></tr></thead>
        <tbody>
        {% for c in conversations %}
        <tr>
            <td><a href="/ui/conversations/{{ c.conversation.id }}">{{ truncate(c.conversation.title, 40) }}</a></td>
            <td>{{ c.message_count }}</td>
            <td>{{ c.active_sessions|length }}</td>
            <td>{{ format_dt(c.conversation.updated_at) }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    {% else %}<div class="empty">暂无会话</div>{% endif %}
</div>

<div class="card">
    <h2>🧠 记忆 ({{ memories|length }})</h2>
    {% if memories %}
    {% for m in memories[:20] %}
    <div style="border-bottom:1px solid #334155;padding:8px 0;font-size:13px;">
        <span style="color:#38bdf8;font-weight:600;">[{{ "%.2f"|format(m.importance) }}]</span>
        {{ truncate(m.content or '', 100) }}
    </div>
    {% endfor %}
    {% else %}<div class="empty">暂无记忆</div>{% endif %}
</div>
{% endblock %}"""

_TEMPLATES["conversation.html"] = r"""{% extends "base.html" %}
{% block content %}
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
    <h2>💬 {{ conversation.title }}</h2>
    {% if project %}<span style="color:#64748b;">项目: <a href="/ui/projects/{{ project.id }}">{{ project.name }}</a></span>{% endif %}
</div>
<p style="color:#64748b;font-size:13px;margin-bottom:16px;">创建: {{ format_dt(conversation.created_at) }} | 更新: {{ format_dt(conversation.updated_at) }}</p>

<div class="card">
    <h2>消息 ({{ messages|length }})</h2>
    {% if messages %}
    {% for msg in messages %}
    <div style="border-bottom:1px solid #334155;padding:10px 0;">
        <div style="font-size:12px;color:#64748b;margin-bottom:4px;">
            <span style="color:#38bdf8;">{{ msg.role }}</span>
            · {{ format_dt(msg.created_at) }}
        </div>
        <div style="font-size:14px;white-space:pre-wrap;">{{ msg.content }}</div>
    </div>
    {% endfor %}
    {% else %}<div class="empty">暂无消息</div>{% endif %}
</div>
{% endblock %}"""

_TEMPLATES["memories.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2 style="margin-bottom:16px;">🧠 记忆浏览</h2>

{% if memories %}
<table>
    <thead><tr><th>重要性</th><th>项目</th><th>内容</th><th>时间</th><th>操作</th></tr></thead>
    <tbody>
    {% for m in memories %}
    <tr>
        <td><span style="color:{{ continuity_color(m.memory.importance) }};font-weight:600;">{{ "%.2f"|format(m.memory.importance) }}</span></td>
        <td><a href="/ui/projects/{{ m.memory.project_id }}">{{ m.project_name }}</a></td>
        <td>{{ truncate(m.memory.content or '', 60) }}</td>
        <td style="font-size:12px;">{{ format_dt(m.memory.created_at) }}</td>
        <td>
            <form method="POST" action="/ui/memories/{{ m.memory.id }}/delete" style="display:inline" onsubmit="return confirm('确定删除?')">
                <button class="btn btn-danger" style="padding:2px 8px;font-size:11px;">删除</button>
            </form>
        </td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<div class="empty">
        <p style="font-size:48px;margin-bottom:16px;">🧠</p>
        <h3>还没有记忆</h3>
        <p style="color:#64748b;margin-top:8px;">创建项目并开始对话后，meshctx会自动从对话中提取重要信息作为记忆。</p>
        <a href="/ui/projects" class="btn btn-primary" style="margin-top:16px;">创建项目 →</a>
    </div>
{% endif %}
{% endblock %}"""

_TEMPLATES["continuity.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2 style="margin-bottom:16px;">📊 连续性检测</h2>
<p style="color:#64748b;margin-bottom:16px;">连续性项目: {{ continuous_count }} / {{ total_count }}</p>

{% if data %}
<table>
    <thead><tr><th>项目</th><th>得分</th><th>状态</th><th>会话数</th><th>记忆数</th><th>活跃会话</th><th>最后活跃</th></tr></thead>
    <tbody>
    {% for d in data %}
    <tr>
        <td><a href="/ui/projects/{{ d.project.id }}">{{ d.project.name }}</a></td>
        <td><span style="color:{{ continuity_color(d.continuity.continuity_score) }};font-weight:700;">{{ "%.2f"|format(d.continuity.continuity_score) }}</span></td>
        <td><span class="badge {% if d.continuity.is_continuous %}badge-active{% else %}badge-inactive{% endif %}">{{ "连续" if d.continuity.is_continuous else "断裂" }}</span></td>
        <td>{{ d.continuity.conversation_count }}</td>
        <td>{{ d.continuity.memory_count }}</td>
        <td>{{ d.continuity.active_session_count }}/{{ d.continuity.total_session_count }}</td>
        <td style="font-size:12px;">{{ format_dt(d.continuity.last_active) }}</td>
    </tr>
    {% endfor %}
    </tbody>
</table>
{% else %}
<div class="empty">📭 暂无数据</div>
{% endif %}
{% endblock %}"""

_TEMPLATES["chat.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>💬 Chat</h2>
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
    <span style="color:#64748b;font-size:13px;">模型:</span>
    <select id="modelSelect" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:4px 8px;border-radius:4px;font-size:13px;" onchange="localStorage.setItem('meshctx_model',this.value)">
        <option value="">加载中...</option>
    </select>
    <button id="compareBtn" onclick="toggleCompare()" style="background:#8b5cf6;color:#fff;border:none;padding:6px 14px;border-radius:6px;font-size:13px;cursor:pointer;margin-left:12px;">⚡ 对比模式</button>
</div>
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;">
    <span style="color:#64748b;font-size:13px;">📋 模板:</span>
    <select id="promptTemplate" onchange="loadTemplate(this.value)" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:4px 8px;border-radius:4px;font-size:12px;min-width:120px;">
        <option value="">-- 选择模板 --</option>
    </select>
    <button onclick="saveAsTemplate()" title="保存当前输入为模板" style="background:transparent;border:1px solid #334155;color:#64748b;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer;">💾 保存</button>
    <button onclick="deleteTemplate()" title="删除选中模板" style="background:transparent;border:1px solid #334155;color:#64748b;padding:4px 6px;border-radius:4px;font-size:11px;cursor:pointer;">🗑️</button>
</div>
<!-- v2.16: 可折叠系统提示词编辑器 -->
<div style="margin-bottom:8px;">
    <button onclick="toggleSystemPrompt()" style="background:transparent;border:1px solid #334155;color:#64748b;padding:2px 10px;border-radius:4px;font-size:11px;cursor:pointer;" id="sysPromptToggle">⚙️ 系统提示词 ▸</button>
    <div id="sysPromptArea" style="display:none;margin-top:6px;">
        <textarea id="sysPromptInput" placeholder="设置AI的行为和角色...&#10;例如: 你是一个Python专家，用中文回答，代码要加注释" style="width:100%;height:60px;background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:8px;border-radius:6px;font-size:12px;resize:vertical;"></textarea>
        <div style="display:flex;gap:6px;margin-top:4px;">
            <button onclick="saveSystemPrompt()" style="background:#2563eb;color:#fff;border:none;padding:3px 12px;border-radius:4px;font-size:11px;cursor:pointer;">💾 保存</button>
            <button onclick="clearSystemPrompt()" style="background:transparent;border:1px solid #334155;color:#64748b;padding:3px 10px;border-radius:4px;font-size:11px;cursor:pointer;">清空</button>
        </div>
    </div>
</div>
<div class="card" style="margin-top:16px; display:flex; flex-direction:column; height:60vh;" id="chatCard">
    <div id="chatTabs" style="display:flex;gap:4px;margin-bottom:8px;flex-wrap:wrap;">
    <button class="tab-btn active" data-tab="default" onclick="switchTab('default')" style="background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:6px 14px;border-radius:6px 6px 0 0;font-size:12px;cursor:pointer;">Chat 1</button>
    <button onclick="newTab()" style="background:transparent;border:1px dashed #334155;color:#64748b;padding:6px 10px;border-radius:6px;font-size:12px;cursor:pointer;">+ 新建</button>
</div>
<div id="messages" style="flex:1; overflow-y:auto; margin-bottom:12px; padding:8px; border:1px solid #334155; border-radius:0 8px 8px 8px; background:#0a0f1a;" 
     ondragover="event.preventDefault();this.style.borderColor='#8b5cf6'" 
     ondragleave="this.style.borderColor='#334155'"
     ondrop="event.preventDefault();this.style.borderColor='#334155';handleDrop(event)"></div>
    <div id="fileTag" style="margin-top:8px;font-size:12px;color:#38bdf8;display:none;"></div>
    <div style="display:flex;gap:6px;margin-bottom:8px;flex-wrap:wrap;" id="quickActions">
        <button onclick="quickAction('翻译成中文')" style="background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer;">🌐 翻译</button>
        <button onclick="quickAction('总结要点')" style="background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer;">📝 总结</button>
        <button onclick="quickAction('解释这段代码')" style="background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer;">💻 解释代码</button>
        <button onclick="quickAction('修复Bug')" style="background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer;">🔧 修复</button>
        <button onclick="quickAction('优化性能')" style="background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 10px;border-radius:4px;font-size:11px;cursor:pointer;">⚡ 优化</button>
    </div>
    <div style="display:flex;gap:8px;margin-top:16px;position:relative;">
        <input id="userInput" placeholder="/read /ls /search /run /context /win @文件引用 命令大全" style="flex:1;" onkeydown="handleChatKeydown(event)" oninput="handleAtInput(this);updateTokenCount()" autocomplete="off">
        <span id="tokenCount" style="color:#64748b;font-size:10px;margin-left:8px;align-self:center;white-space:nowrap;">0 tokens</span>
        <button class="btn" style="background:#334155;color:#94a3b8;font-size:16px;padding:8px 12px;" onclick="document.getElementById('fileInput').click()" title="上传文件">📎</button>
        <button id="compareBtn" class="btn" style="background:#8b5cf6;color:#e2e8f0;font-size:12px;padding:8px 12px;border:none;border-radius:6px;cursor:pointer;" onclick="toggleCompare()" title="多模型对比">⚡ 对比</button>
        <button onclick="exportChat()" title="导出对话" style="background:transparent;border:1px solid #334155;color:#64748b;padding:6px 10px;border-radius:4px;font-size:11px;cursor:pointer;">📥 导出</button>
        <button class="btn btn-primary" onclick="send()">发送</button>
        <div id="atAutocomplete" style="display:none;position:absolute;top:100%;left:0;background:#1e293b;border:1px solid #334155;border-radius:6px;max-height:200px;overflow-y:auto;z-index:1000;min-width:300px;box-shadow:0 4px 12px rgba(0,0,0,0.5);"></div>
    </div>
    <input type="file" id="fileInput" style="display:none" multiple onchange="uploadFiles()">
</div>
<details style="margin-top:12px;">
    <summary style="color:#64748b;font-size:12px;cursor:pointer;">🖥️ 终端</summary>
    <div style="background:#0a0a0a;border:1px solid #334155;border-radius:6px;padding:8px;margin-top:8px;font-family:monospace;font-size:12px;">
        <div id="termOutput" style="max-height:200px;overflow-y:auto;color:#22c55e;white-space:pre-wrap;min-height:40px;">$ _</div>
        <div style="display:flex;gap:4px;margin-top:4px;">
            <span style="color:#22c55e;">$</span>
            <input id="termInput" placeholder="输入命令..." style="flex:1;background:transparent;border:none;color:#22c55e;font-family:monospace;font-size:12px;outline:none;" onkeydown="if(event.key==='Enter')runTerm()">
        </div>
    </div>
</details>

<!-- ═══ 对比模式: 模型选择弹窗 ═══ -->
<div id="compareModal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:1000;align-items:center;justify-content:center;">
    <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:24px;max-width:480px;width:90%;max-height:80vh;overflow-y:auto;">
        <h3 style="margin:0 0 4px;font-size:18px;">⚡ 多模型对比</h3>
        <p style="color:#64748b;font-size:13px;margin:0 0 16px;">勾选 2-6 个模型，同时提问并对比回答</p>
        <div id="compareModelList" style="max-height:300px;overflow-y:auto;margin-bottom:16px;">
            <div style="color:#64748b;font-size:13px;">加载模型列表...</div>
        </div>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button onclick="cancelCompare()" style="background:#334155;color:#94a3b8;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;">取消</button>
            <button id="compareStartBtn" onclick="startCompare()" style="background:#8b5cf6;color:#fff;border:none;padding:8px 20px;border-radius:6px;cursor:pointer;">⚡ 开始对比</button>
        </div>
    </div>
</div>

<!-- ═══ 对比模式: 三列结果展示 ═══ -->
<div id="compareResults" style="display:none;margin-top:16px;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <h3 style="margin:0;font-size:16px;">📊 模型对比结果</h3>
        <button onclick="closeCompare()" style="background:#334155;color:#94a3b8;border:none;padding:4px 12px;border-radius:6px;font-size:12px;cursor:pointer;">✕ 关闭</button>
    </div>
    <div id="compareQuery" style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:14px;color:#94a3b8;">
        <strong style="color:#e2e8f0;">提问:</strong> <span id="compareQueryText"></span>
    </div>
    <div id="compareCards" style="display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));">
    </div>
</div>

<script>
let uploadedContents = [];  // v1.7: 多文件支持

async function uploadFiles() {
    const input = document.getElementById('fileInput');
    const files = Array.from(input.files);
    if (!files.length) return;
    
    const tag = document.getElementById('fileTag');
    tag.style.display = 'block';
    uploadedContents = [];
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        tag.textContent = '⏳ 上传中 (' + (i+1) + '/' + files.length + '): ' + file.name;
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/chat/upload', {method: 'POST', body: formData});
            if (!res.ok) {
                const err = await res.json();
                tag.innerHTML += '<br><span style="color:#fca5a5;">❌ ' + file.name + ': ' + (err.detail || '失败') + '</span>';
                continue;
            }
            const data = await res.json();
            uploadedContents.push({filename: data.filename, content: data.content, size: data.size});
        } catch(e) {
            tag.innerHTML += '<br><span style="color:#fca5a5;">❌ ' + file.name + ': ' + e.message + '</span>';
        }
    }
    
    if (uploadedContents.length > 0) {
        const names = uploadedContents.map(f => f.filename).join(', ');
        const totalSize = uploadedContents.reduce((s,f) => s + f.size, 0);
        tag.innerHTML = '📄 ' + uploadedContents.length + '个文件: ' + names + 
            ' <span style="color:#64748b;">(' + (totalSize > 1024 ? (totalSize/1024).toFixed(1)+'KB' : totalSize+'B') + ')</span>' +
            ' <a href="#" onclick="clearFiles()" style="color:#f87171;text-decoration:none;">✕</a>';
    }
    input.value = '';
}

function clearFiles() {
    uploadedContents = [];
    document.getElementById('fileTag').style.display = 'none';
    document.getElementById('fileInput').value = '';
}

// 向后兼容: 单文件旧接口
async function uploadFile() {
    return uploadFiles();
}

// v2.6: 拖拽上传
async function handleDrop(event) {
    var files = Array.from(event.dataTransfer.files);
    if (!files.length) return;
    var input = document.getElementById('fileInput');
    var dt = new DataTransfer();
    files.forEach(function(f){ dt.items.add(f); });
    input.files = dt.files;
    await uploadFiles();
}

async function loadModels() {
    try {
        const res = await fetch('/api/models');
        const data = await res.json();
        const sel = document.getElementById('modelSelect');
        sel.innerHTML = '';
        if (data.models) {
            data.models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = m.id + (m.usable ? ' ✓' : (m.has_key ? ' ⚠' : ' 🔒'));
                if (!m.usable) opt.disabled = true;
                sel.appendChild(opt);
            });
        }
        if (data.default) {
        const saved = localStorage.getItem('meshctx_model');
        sel.value = saved || data.default;
    }
    } catch(e) {
        document.getElementById('modelSelect').innerHTML = '<option>加载失败</option>';
    }
}
loadModels();
loadTemplates();

// Chat历史持久化
const HISTORY_KEY = 'meshctx_chat_history';
let chatHistory = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
function saveHistory() { localStorage.setItem(HISTORY_KEY, JSON.stringify(chatHistory.slice(-100))); }
function restoreHistory() {
    const div = document.getElementById('messages');
    chatHistory.forEach((h, i) => {
        if (h.role === 'user') {
            var userBubble = document.createElement('div');
            userBubble.style.cssText = 'margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;';
            userBubble.innerHTML = '<strong>You:</strong> ' + h.content;
            var editBtn = document.createElement('button');
            editBtn.textContent = '✏️';
            editBtn.title = '编辑并重发';
            editBtn.style.cssText = 'float:right;background:transparent;border:1px solid #334155;color:#64748b;border-radius:4px;padding:1px 6px;cursor:pointer;font-size:11px;margin-left:4px;';
            editBtn.onclick = function(){ editMessage(i); };
            userBubble.appendChild(editBtn);
            div.appendChild(userBubble);
        }
        else {
            var aiBubble = document.createElement('div');
            aiBubble.style.cssText = 'margin:8px 0;padding:8px;background:#1e293b;border-radius:8px;';
            aiBubble.innerHTML = '<strong style="color:#38bdf8;">AI:</strong> ' + h.content;
            div.appendChild(aiBubble);
        }
    });
    // v1.5.18: 添加代码运行按钮
    setTimeout(function(){ addCodeRunButtons(div); }, 100);
    div.scrollTop = div.scrollHeight;
}
// 消息编辑重发
function editMessage(idx) {
    if(idx >= chatHistory.length) return;
    var msg = chatHistory[idx];
    if(msg.role !== 'user') return;
    document.getElementById('userInput').value = msg.content;
    document.getElementById('userInput').focus();
    chatHistory.splice(idx);
    saveHistory();
    restoreHistory();
}
// 多会话标签
let activeTab = 'default';
const TABS_KEY = 'meshctx_tabs';
let allTabs = (function() {
    var raw = JSON.parse(localStorage.getItem(TABS_KEY) || '{"default":[]}');
    var migrated = {};
    Object.keys(raw).forEach(function(k, i) {
        if (Array.isArray(raw[k])) {
            migrated[k] = {messages: raw[k], name: 'Chat ' + (i+1)};
        } else if (raw[k] && typeof raw[k] === 'object' && Array.isArray(raw[k].messages)) {
            migrated[k] = raw[k];
        } else {
            migrated[k] = {messages: [], name: 'Chat ' + (i+1)};
        }
    });
    return migrated;
})();
function saveTabs() { localStorage.setItem(TABS_KEY, JSON.stringify(allTabs)); }
function switchTab(tabId) {
    activeTab = tabId;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('[data-tab="'+tabId+'"]').classList.add('active');
    localStorage.setItem('meshctx_active_tab', tabId);
    const div = document.getElementById('messages');
    div.innerHTML = '';
    (allTabs[tabId] && allTabs[tabId].messages || []).forEach(function(h) {
        if (h.role==='user') div.innerHTML += '<div style="margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;"><strong>You:</strong> ' + h.content + '</div>';
        else div.innerHTML += '<div style="margin:8px 0;padding:8px;background:#1e293b;border-radius:8px;"><strong style="color:#38bdf8;">AI:</strong> ' + h.content + '</div>';
    });
    div.scrollTop = div.scrollHeight;
}
function newTab() {
    const id = 'chat_' + Date.now();
    const n = Object.keys(allTabs).length + 1;
    allTabs[id] = {messages: [], name: 'Chat ' + n};
    saveTabs();
    const tabs = document.getElementById('chatTabs');
    const btn = document.createElement('button');
    btn.className = 'tab-btn'; btn.dataset.tab = id;
    btn.textContent = 'Chat ' + n;
    btn.style.cssText = 'background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:6px 14px;border-radius:6px 6px 0 0;font-size:12px;cursor:pointer;';
    btn.onclick = function(){switchTab(id)};
    btn.oncontextmenu = function(e) {
        e.preventDefault();
        var tabId = this.dataset.tab;
        var curName = (allTabs[tabId] && allTabs[tabId].name) || tabId;
        var newName = prompt('重命名会话:', curName);
        if (newName && newName.trim()) {
            if (!allTabs[tabId]) allTabs[tabId] = {messages: [], name: newName.trim()};
            allTabs[tabId].name = newName.trim();
            this.textContent = newName.trim();
            saveTabs();
        }
        return false;
    };
    tabs.insertBefore(btn, tabs.lastElementChild);
    switchTab(id);
}
// Override chatHistory to use per-tab storage
chatHistory = (allTabs[activeTab] && allTabs[activeTab].messages || []);
function saveHistory() { 
    if (!allTabs[activeTab]) allTabs[activeTab] = {messages: [], name: 'Chat ' + (Object.keys(allTabs).length + 1)};
    allTabs[activeTab].messages = chatHistory.slice(-100);
    saveTabs();
}
function toggleTheme() {
    document.body.classList.toggle('light');
    localStorage.setItem('meshctx_theme', document.body.classList.contains('light') ? 'light' : 'dark');
    const isLight = document.body.classList.contains('light');
    localStorage.setItem('meshctx_theme', isLight ? 'light' : 'dark');
}
// Restore theme
if (localStorage.getItem('meshctx_theme') === 'light') document.body.classList.add('light');

// 恢复标签页
(function restoreTabs() {
    const tabIds = Object.keys(allTabs);
    const tabsDiv = document.getElementById('chatTabs');
    // 清除旧标签（保留+按钮）
    while (tabsDiv.children.length > 1) tabsDiv.removeChild(tabsDiv.firstChild);
    tabIds.forEach(function(id) {
        const btn = document.createElement('button');
        btn.className = 'tab-btn'; btn.dataset.tab = id;
        btn.textContent = (allTabs[id] && allTabs[id].name) || id;
        btn.style.cssText = 'background:#1e293b;border:1px solid #334155;color:#e2e8f0;padding:6px 14px;border-radius:6px 6px 0 0;font-size:12px;cursor:pointer;';
        btn.onclick = function(){switchTab(id)};
        btn.oncontextmenu = function(e) {
            e.preventDefault();
            var tabId = this.dataset.tab;
            var curName = (allTabs[tabId] && allTabs[tabId].name) || tabId;
            var newName = prompt('重命名会话:', curName);
            if (newName && newName.trim()) {
                if (!allTabs[tabId]) allTabs[tabId] = {messages: [], name: newName.trim()};
                allTabs[tabId].name = newName.trim();
                this.textContent = newName.trim();
                saveTabs();
            }
            return false;
        };
        tabsDiv.insertBefore(btn, tabsDiv.lastElementChild);
    });
    // 恢复上次活跃标签
    const lastActive = localStorage.getItem('meshctx_active_tab') || 'default';
    if (allTabs[lastActive]) switchTab(lastActive);
    else if (allTabs['default']) switchTab('default');
})();
restoreHistory();

async function runTerm() {
    const inp = document.getElementById('termInput');
    const out = document.getElementById('termOutput');
    const cmd = inp.value.trim();
    if (!cmd) return;
    out.innerHTML += '\n$ ' + cmd;
    inp.value = '';
    try {
        const res = await fetch('/api/terminal', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body:JSON.stringify({cmd:cmd})
        });
        const d = await res.json();
        out.innerHTML += '\n' + (d.output || d.error || '(无输出)');
    } catch(e) {
        out.innerHTML += '\n错误: ' + e.message;
    }
    out.scrollTop = out.scrollHeight;
}

// ═══ Multi-Model Compare v2.11 ═══
var compareMode = false;
function toggleCompare(){
  compareMode = !compareMode;
  var btn = document.getElementById('compareBtn');
  var input = document.getElementById('userInput');
  if(compareMode){
    btn.style.background = '#22c55e';
    btn.textContent = '⚡ 对比中';
    input.placeholder = '对比模式: 同时问3个模型...';
  } else {
    btn.style.background = '#8b5cf6';
    btn.textContent = '⚡ 对比';
    input.placeholder = '/read /ls /search /run /context /win 命令大全';
  }
}

// ═══ Compare Modal Functions ═══
function cancelCompare(){
  document.getElementById('compareModal').style.display = 'none';
}
function startCompare(){
  var checks = document.querySelectorAll('#compareModelList input[type=checkbox]:checked');
  if(checks.length < 2){ alert('请至少选择2个模型进行对比'); return; }
  var models = [];
  checks.forEach(function(c){ models.push(c.value); });
  localStorage.setItem('meshctx_compare_models', JSON.stringify(models));
  document.getElementById('compareModal').style.display = 'none';
  compareMode = true;
  var btn = document.getElementById('compareBtn');
  btn.style.background = '#22c55e';
  btn.textContent = '⚡ 对比中';
  document.getElementById('userInput').placeholder = '对比模式: 同时问'+models.length+'个模型...';
}
function closeCompare(){
  document.getElementById('compareResults').style.display = 'none';
}

async function compareSend(msg){
  var div = document.getElementById('messages');
  div.innerHTML += '<div style="margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;"><strong>You:</strong> ' + msg + '</div>';
  document.getElementById('userInput').value = '';
  
  var models = JSON.parse(localStorage.getItem('meshctx_compare_models') || '["deepseek:chat","openai:gpt-4o-mini","anthropic:claude-haiku"]');
  
  // Show loading
  var loadId = 'load_' + Date.now();
  div.innerHTML += '<div id="'+loadId+'" style="display:grid;grid-template-columns:repeat('+models.length+',1fr);gap:8px;margin:8px 0;">';
  models.forEach(function(m){
    div.querySelector('#'+loadId).innerHTML += '<div style="background:#1e293b;border-radius:8px;padding:10px;text-align:center;color:var(--muted);"><strong>'+m+'</strong><br>⏳...</div>';
  });
  div.querySelector('#'+loadId).innerHTML += '</div>';
  div.scrollTop = div.scrollHeight;
  
  try {
    var res = await fetch('/api/chat/compare', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message:msg, models:models})
    });
    var data = await res.json();
    var html = '<div style="display:grid;grid-template-columns:repeat('+models.length+',1fr);gap:8px;margin:8px 0;">';
    (data.results||[]).forEach(function(r){
      var color = r.error ? '#fca5a5' : '#22c55e';
      html += '<div style="background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px;font-size:12px;">'+
        '<div style="display:flex;justify-content:space-between;margin-bottom:4px;">'+
        '<strong style="color:#38bdf8;">'+r.model+'</strong>'+
        '<span style="font-size:10px;color:var(--muted);">'+r.latency_ms+'ms · '+r.tokens+'t</span></div>'+
        '<div style="color:#e2e8f0;white-space:pre-wrap;max-height:300px;overflow-y:auto;">'+r.content+'</div></div>';
    });
    html += '</div>';
    document.getElementById(loadId).outerHTML = html;
  } catch(e) {
    document.getElementById(loadId).outerHTML = '<div style="color:#fca5a5;">对比失败: '+e.message+'</div>';
  }
}

// ── 提示词模板 ──
async function loadTemplates() {
    try {
        var res = await fetch('/api/prompts');
        var data = await res.json();
        var sel = document.getElementById('promptTemplate');
        sel.innerHTML = '<option value="">-- 选择模板 --</option>';
        if (data && data.prompts) {
            data.prompts.forEach(function(p) {
                var opt = document.createElement('option');
                opt.value = p;
                opt.textContent = p;
                sel.appendChild(opt);
            });
        }
    } catch(e) { console.error('加载模板失败:', e); }
}

async function loadTemplate(name) {
    if (!name) return;
    try {
        var res = await fetch('/api/prompts/' + encodeURIComponent(name));
        var data = await res.json();
        document.getElementById('userInput').value = data.content || '';
    } catch(e) { alert('加载模板失败: ' + e.message); }
}

async function saveAsTemplate() {
    var name = prompt('模板名称:');
    if (!name || !name.trim()) return;
    var content = document.getElementById('userInput').value;
    try {
        var res = await fetch('/api/prompts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name: name.trim(), content: content})
        });
        if (!res.ok) { var err = await res.json(); alert(err.detail || '保存失败'); return; }
        loadTemplates();
    } catch(e) { alert('保存失败: ' + e.message); }
}

async function deleteTemplate() {
    var sel = document.getElementById('promptTemplate');
    var name = sel.value;
    if (!name) { alert('请先选择模板'); return; }
    if (!confirm('删除模板 "' + name + '"?')) return;
    try {
        var res = await fetch('/api/prompts/' + encodeURIComponent(name), {method: 'DELETE'});
        if (!res.ok) { var err = await res.json(); alert(err.detail || '删除失败'); return; }
        loadTemplates();
    } catch(e) { alert('删除失败: ' + e.message); }
}

// ── 系统提示词 ──
function toggleSystemPrompt() {
    var area = document.getElementById('sysPromptArea');
    var btn = document.getElementById('sysPromptToggle');
    var visible = area.style.display !== 'none';
    area.style.display = visible ? 'none' : 'block';
    btn.textContent = visible ? '⚙️ 系统提示词 ▸' : '⚙️ 系统提示词 ▾';
    if(!visible) {
        // 加载当前tab的system prompt
        var tabId = localStorage.getItem('meshctx_active_tab') || 'default';
        var tab = allTabs[tabId];
        document.getElementById('sysPromptInput').value = (tab && tab.systemPrompt) || '';
    }
}

function saveSystemPrompt() {
    var tabId = localStorage.getItem('meshctx_active_tab') || 'default';
    var prompt = document.getElementById('sysPromptInput').value.trim();
    if(!allTabs[tabId]) allTabs[tabId] = {messages:[], name:'Chat'};
    allTabs[tabId].systemPrompt = prompt;
    saveTabs();
    // 视觉反馈
    var btns = document.querySelectorAll('#sysPromptArea button');
    if (btns.length > 0) {
        var btn = btns[0];
        var orig = btn.textContent;
        btn.textContent = '✅ 已保存';
        setTimeout(function(){ btn.textContent = orig; }, 1500);
    }
}

function clearSystemPrompt() {
    document.getElementById('sysPromptInput').value = '';
    saveSystemPrompt();
}

// ── 对比模式 ──
function exportChat() {
    var md = '# MeshCtx Chat Export\n\n';
    var tabId = localStorage.getItem('meshctx_active_tab') || 'default';
    var history = JSON.parse(localStorage.getItem('meshctx_chat_' + tabId) || '[]');
    if(history.length === 0) { alert('当前无对话可导出'); return; }
    history.forEach(function(m) {
        var role = m.role === 'user' ? '**🧑 User:**' : '**🤖 AI:**';
        md += role + '\n\n' + m.content + '\n\n---\n\n';
    });
    var blob = new Blob([md], {type: 'text/markdown;charset=utf-8'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'meshctx-chat-' + new Date().toISOString().slice(0,10) + '.md';
    a.click(); URL.revokeObjectURL(url);
}

// ═══ @文件引用自动补全 v2.16 ═══
let _atDebounce = null;
let _atSelectedIndex = -1;
let _atFiles = [];

function hideAtAutocomplete() {
    var dd = document.getElementById('atAutocomplete');
    dd.style.display = 'none';
    dd.innerHTML = '';
    _atSelectedIndex = -1;
    _atFiles = [];
}

async function handleAtInput(el) {
    var val = el.value;
    var cursorPos = el.selectionStart;
    // 找到光标前最后一个@符号
    var textBeforeCursor = val.substring(0, cursorPos);
    var lastAt = textBeforeCursor.lastIndexOf('@');
    
    if (lastAt === -1) { hideAtAutocomplete(); return; }
    
    // 检查@是否在单词边界（前面是空白或行首）
    if (lastAt > 0 && !/\\s/.test(textBeforeCursor[lastAt - 1])) { hideAtAutocomplete(); return; }
    
    var filter = textBeforeCursor.substring(lastAt + 1);
    
    // 防抖
    if (_atDebounce) clearTimeout(_atDebounce);
    _atDebounce = setTimeout(async function() {
        await fetchAtFiles(filter);
    }, 200);
}

async function fetchAtFiles(filter) {
    var dd = document.getElementById('atAutocomplete');
    var allFiles = [];
    
    // 搜索项目文件
    try {
        var res = await fetch('/api/project/search?q=' + encodeURIComponent(filter) + '&limit=15');
        if (res.ok) {
            var data = await res.json();
            if (data.files) {
                data.files.forEach(function(f) {
                    allFiles.push({name: f.name || f.path, path: f.path, source: 'project'});
                });
            }
        }
    } catch(e) {}
    
    // 搜索当前目录文件
    try {
        var res2 = await fetch('/api/file/list?path=.');
        if (res2.ok) {
            var data2 = await res2.json();
            if (data2.items) {
                data2.items.forEach(function(f) {
                    if (f.is_dir) return; // 只显示文件
                    allFiles.push({name: f.name, path: data2.path + '/' + f.name, source: 'local'});
                });
            }
        }
    } catch(e) {}
    
    // 去重 + 过滤
    var seen = {};
    var results = [];
    for (var i = 0; i < allFiles.length; i++) {
        var f = allFiles[i];
        if (seen[f.path]) continue;
        seen[f.path] = true;
        var lf = f.name.toLowerCase();
        var lfilter = filter.toLowerCase();
        if (filter && lf.indexOf(lfilter) === -1) continue;
        results.push(f);
    }
    
    // 排序：精确匹配优先，前缀匹配次之，其余按名字
    results.sort(function(a, b) {
        var la = a.name.toLowerCase(), lb = b.name.toLowerCase();
        var lf = filter.toLowerCase();
        if (la === lf && lb !== lf) return -1;
        if (lb === lf && la !== lf) return 1;
        if (la.indexOf(lf) === 0 && lb.indexOf(lf) !== 0) return -1;
        if (lb.indexOf(lf) === 0 && la.indexOf(lf) !== 0) return 1;
        return la.localeCompare(lb);
    });
    
    _atFiles = results;
    _atSelectedIndex = -1;
    
    if (results.length === 0) {
        dd.style.display = 'none';
        return;
    }
    
    var html = '';
    for (var i = 0; i < results.length; i++) {
        var f = results[i];
        var icon = f.source === 'project' ? '📁' : '📄';
        html += '<div class="at-item" data-idx="' + i + '" style="padding:6px 12px;cursor:pointer;font-size:13px;display:flex;align-items:center;gap:8px;border-bottom:1px solid #1e293b;" onmousedown="event.preventDefault();selectAtFile(' + i + ')" onmouseenter="_atSelectedIndex=' + i + ';highlightAtItem(' + i + ')">';
        html += '<span style="font-size:14px;">' + icon + '</span>';
        html += '<span style="flex:1;color:#e2e8f0;">' + f.name + '</span>';
        html += '<span style="color:#64748b;font-size:11px;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + f.path + '</span>';
        html += '</div>';
    }
    dd.innerHTML = html;
    dd.style.display = 'block';
}

function highlightAtItem(idx) {
    var items = document.querySelectorAll('#atAutocomplete .at-item');
    items.forEach(function(item, i) {
        item.style.background = i === idx ? '#334155' : '';
    });
}

function selectAtFile(idx) {
    var f = _atFiles[idx];
    if (!f) return;
    
    var el = document.getElementById('userInput');
    var val = el.value;
    var cursorPos = el.selectionStart;
    var textBeforeCursor = val.substring(0, cursorPos);
    var lastAt = textBeforeCursor.lastIndexOf('@');
    
    if (lastAt === -1) return;
    
    // 替换 @filter 为 @[文件名](路径) 
    var before = val.substring(0, lastAt);
    var after = val.substring(cursorPos);
    var replacement = '@[' + f.name + '](' + f.path + ') ';
    el.value = before + replacement + after;
    
    // 移动光标到替换文本之后
    var newPos = lastAt + replacement.length;
    el.setSelectionRange(newPos, newPos);
    el.focus();
    
    hideAtAutocomplete();
}

// 键盘导航: Enter/Escape/ArrowUp/ArrowDown/Tab + Chat快捷键(Ctrl+Enter/Esc/ArrowUp)
function handleChatKeydown(event) {
    // Ctrl+Enter 或 Cmd+Enter: 发送
    if((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        hideAtAutocomplete();
        send();
        return;
    }
    
    var dd = document.getElementById('atAutocomplete');
    var isVisible = dd.style.display === 'block';
    
    if (event.key === 'Escape') {
        if (isVisible) { hideAtAutocomplete(); event.preventDefault(); return; }
        // 中断流式输出(如果有)
        if(window._abortStream) { window._abortStream(); return; }
        // 清空输入
        var input = document.getElementById('userInput');
        if(input.value) { input.value = ''; updateTokenCount(); }
        return;
    }
    
    if (isVisible && _atFiles.length > 0) {
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            _atSelectedIndex = Math.min(_atSelectedIndex + 1, _atFiles.length - 1);
            highlightAtItem(_atSelectedIndex);
            return;
        }
        if (event.key === 'ArrowUp') {
            event.preventDefault();
            _atSelectedIndex = Math.max(_atSelectedIndex - 1, 0);
            highlightAtItem(_atSelectedIndex);
            return;
        }
        if (event.key === 'Enter' || event.key === 'Tab') {
            if (_atSelectedIndex >= 0) {
                event.preventDefault();
                selectAtFile(_atSelectedIndex);
                return;
            }
        }
    }
    
    // ArrowUp: 上一条历史消息(如果输入为空且不在自动补全中)
    if (event.key === 'ArrowUp' && !document.getElementById('userInput').value && !isVisible) {
        event.preventDefault();
        var history = JSON.parse(localStorage.getItem('meshctx_chat_' + (localStorage.getItem('meshctx_active_tab')||'default')) || '[]');
        for(var i=history.length-1; i>=0; i--) {
            if(history[i].role === 'user') {
                document.getElementById('userInput').value = history[i].content;
                updateTokenCount();
                break;
            }
        }
        return;
    }
    
    if (event.key === 'Enter') {
        hideAtAutocomplete();
        send();
    }
}

// v2.15.6: Token 计数器, 防抖300ms, 颜色警告
var tokenDebounce = null;
function updateTokenCount() {
    clearTimeout(tokenDebounce);
    tokenDebounce = setTimeout(async function() {
        var text = document.getElementById('userInput').value;
        var el = document.getElementById('tokenCount');
        if (!text) { el.textContent = '0 tokens'; el.style.color = '#64748b'; return; }
        try {
            var res = await fetch('/api/utils/tokens', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text:text})});
            var data = await res.json();
            el.textContent = data.tokens + ' tokens';
            if (data.tokens > 8000) el.style.color = '#ef4444';
            else if (data.tokens > 4000) el.style.color = '#f59e0b';
            else el.style.color = '#64748b';
        } catch(e) {}
    }, 300);
}

async function send() {
    const input = document.getElementById('userInput');
    if (!input) return;
    let msg = input.value.trim();
    if (!msg) return;
    
    // Compare mode intercept
    if(compareMode){
      await compareSend(msg);
      return;
    }
    let fullMsg = msg;
    const div = document.getElementById('messages');
    
    // v2.2: 本地文件快捷指令 /read /ls
    if (msg.startsWith('/read ') || msg.startsWith('/ls ')) {
        var parts = msg.split(' ');
        var cmd = parts[0];
        var fpath = parts.slice(1).join(' ');
        if (!fpath) { alert('用法: /read 文件路径  或  /ls 目录路径'); return; }
        var apiUrl = cmd === '/read' ? '/api/file/read?path=' + encodeURIComponent(fpath)
                                     : '/api/file/list?path=' + encodeURIComponent(fpath);
        try {
            var res = await fetch(apiUrl);
            var data = await res.json();
            if (!res.ok) { alert('❌ ' + (data.detail || '失败')); return; }
            if (cmd === '/read') {
                fullMsg = '[本地文件: ' + data.filename + ' (' + (data.size>1024?(data.size/1024).toFixed(1)+'KB':data.size+'B') + ')]\n```\n' + data.content.substring(0, 50000) + '\n```\n\n用户消息: 请分析以上文件内容';
            } else {
                var listing = data.items.map(function(it){ return (it.is_dir?'📁':'📄')+' '+it.name + (it.size?' ('+(it.size>1024?(it.size/1024).toFixed(1)+'KB':it.size+'B')+')':''); }).join('\n');
                fullMsg = '[目录: ' + data.path + ']\n' + listing + '\n\n用户消息: 请分析以上目录结构';
            }
            msg = cmd + ' ' + fpath;
        } catch(e) { alert('读取失败: ' + e.message); return; }
    }
    
    // v2.7: Web搜索 /search 
    if (msg.startsWith('/search ')) {
        var query = msg.substring(8).trim();
        if (!query) { alert('用法: /search 搜索词'); return; }
        try {
            var res = await fetch('/api/search?q=' + encodeURIComponent(query));
            var data = await res.json();
            var results = data.results || [];
            var searchBlock = '[Web搜索: ' + query + ']\n';
            for (var i=0; i<results.length; i++) {
                searchBlock += (i+1) + '. ' + results[i].title + '\n   ' + results[i].snippet + '\n   ' + results[i].url + '\n\n';
            }
            fullMsg = searchBlock + '\n用户消息: 请基于以上搜索结果回答';
            msg = '/search ' + query;
        } catch(e) { alert('搜索失败: ' + e.message); return; }
    }
    
    // v2.7: 代码沙箱 /run python|bash|js 代码
    if (msg.startsWith('/run ')) {
        var parts = msg.substring(5).trim();
        var lang = 'python';
        var code = parts;
        // Parse: /run python print('hello')  or  /run bash echo hi
        if (parts.match(/^(python|bash|javascript|js|sh)\s/)) {
            var spaceIdx = parts.indexOf(' ');
            lang = parts.substring(0, spaceIdx);
            code = parts.substring(spaceIdx + 1);
            if (lang === 'js') lang = 'javascript';
            if (lang === 'sh') lang = 'bash';
        }
        if (!code) { alert('用法: /run [python|bash|js] 代码'); return; }
        try {
            var runRes = await fetch('/api/sandbox/execute', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({code:code, language:lang, timeout:30})
            });
            var runData = await runRes.json();
            var runBlock = '[Sandbox执行: ' + lang + ']\\n```\\n' + (runData.stdout || '') + '\\n```\\n';
            if (runData.stderr) runBlock += '[stderr]\\n```\\n' + runData.stderr + '\\n```\\n';
            runBlock += '[退出码: ' + runData.exit_code + ' | 耗时: ' + runData.duration_ms + 'ms | 方式: ' + (runData.method||'unknown') + ']\\n';
            fullMsg = runBlock + '\\n用户消息: 请分析以上执行结果并回答';
            msg = '/run ' + lang + ' ' + code.substring(0, 50);
        } catch(e) { alert('沙箱执行失败: ' + e.message); return; }
    }
    
    // v2.7: 项目上下文 /context 查询
    if (msg.startsWith('/context ')) {
        var query = msg.substring(9).trim();
        if (!query) { alert('用法: /context 搜索词'); return; }
        try {
            var ctxRes = await fetch('/api/project/context?q=' + encodeURIComponent(query));
            var ctxData = await ctxRes.json();
            var ctxBlock = '[项目上下文: ' + query + ']\\n```\\n' + ctxData.context + '\\n```\\n';
            fullMsg = ctxBlock + '\\n用户消息: 请基于以上项目上下文回答';
            msg = '/context ' + query;
        } catch(e) { alert('项目索引失败: ' + e.message); return; }
    }
    
    // v2.10.1: Windows管理 /win 命令
    if (msg.startsWith('/win ')) {
        var parts = msg.substring(5).trim();
        var action = parts.split(' ')[0]; // list/start/stop/restart/exec/service/process/system
        var arg = parts.substring(action.length).trim();
        
        if (action === 'services' || action === 'service') {
            try {
                var svcRes = await fetch('/api/win/services' + (arg ? '?filter=' + encodeURIComponent(arg) : ''));
                var svcData = await svcRes.json();
                var svcBlock = '[Windows Services]\n';
                (svcData.services||[]).forEach(function(s){
                    svcBlock += s.status + ' ' + s.name + ' - ' + s.display_name + '\n';
                });
                fullMsg = svcBlock + '\n用户消息: 以上是Windows服务列表';
                msg = '/win services';
            } catch(e) { alert('获取服务失败: ' + e.message); return; }
        } else if (action === 'processes' || action === 'ps') {
            try {
                var procRes = await fetch('/api/win/processes');
                var procData = await procRes.json();
                var procBlock = '[Windows Processes Top 30]\n';
                (procData.processes||[]).forEach(function(p){
                    procBlock += 'PID:' + p.pid + ' ' + p.name + ' CPU:' + p.cpu + ' MEM:' + p.memory_mb + 'MB\n';
                });
                fullMsg = procBlock + '\n用户消息: 以上是Windows进程列表';
                msg = '/win processes';
            } catch(e) { alert('获取进程失败: ' + e.message); return; }
        } else if (action === 'system' || action === 'sys') {
            try {
                var sysRes = await fetch('/api/win/system');
                var sysData = await sysRes.json();
                fullMsg = '[Windows System Info]\n' + JSON.stringify(sysData, null, 2)
                    + '\n用户消息: 以上是Windows系统信息';
                msg = '/win system';
            } catch(e) { alert('获取系统信息失败: ' + e.message); return; }
        } else if (action === 'exec' || action === 'ps1') {
            if (!arg) { alert('用法: /win exec <PowerShell命令>'); return; }
            try {
                var execRes = await fetch('/api/win/execute', {
                    method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({command:arg, timeout:30})
                });
                var execData = await execRes.json();
                fullMsg = '[PowerShell: ' + arg.substring(0,80) + ']\n'
                    + (execData.stdout || '') + '\n'
                    + (execData.stderr ? '[STDERR] ' + execData.stderr + '\n' : '')
                    + '[Exit: ' + execData.exit_code + ' | ' + execData.duration_ms + 'ms]'
                    + '\n用户消息: 请分析以上PowerShell执行结果';
                msg = '/win exec ' + arg.substring(0,50);
            } catch(e) { alert('PowerShell执行失败: ' + e.message); return; }
        } else if (action === 'software' || action === 'apps') {
            try {
                var swRes = await fetch('/api/win/software');
                var swData = await swRes.json();
                var swBlock = '[Installed Software]\n';
                (swData.software||[]).slice(0,20).forEach(function(s){
                    swBlock += (s.name||'?') + ' v' + (s.version||'?') + '\n';
                });
                fullMsg = swBlock + '\n用户消息: 以上是已安装软件列表';
                msg = '/win software';
            } catch(e) { alert('获取软件列表失败: ' + e.message); return; }
        } else {
            alert('用法: /win services|processes|system|software|exec <PS命令>');
            return;
        }
    }
    
    // v2.12: Agent统计 /stats 命令
    if (msg === '/stats') {
        try {
            var statsRes = await fetch('/api/agent/monitor');
            var statsData = await statsRes.json();
            var statsBlock = '[MeshCtx Agent Stats]\n'+
                '⏱ Uptime: '+(statsData.uptime_seconds||0)+'s\n'+
                '💬 Messages: '+(statsData.chat?.messages||0)+' | Tokens: '+(statsData.chat?.tokens||0)+'\n'+
                '✅ Tasks: '+(statsData.tasks?.completed||0)+' | ❌ Failed: '+(statsData.tasks?.failed||0)+'\n'+
                '🖥️ Sandbox: '+(statsData.tools?.sandbox||0)+' | 🔍 Search: '+(statsData.tools?.search||0)+'\n'+
                '🪟 Windows: '+(statsData.tools?.windows||0)+' | 📄 Files: '+(statsData.tools?.file_reads||0)+'\n'+
                '🧠 Brain: '+(statsData.brain_cycles||0)+' cycles\n'+
                '❤️ Health: '+(statsData.health||'unknown')+'\n';
            fullMsg = statsBlock + '\n用户消息: 请分析以上Agent运行统计';
            msg = '/stats';
        } catch(e) { alert('统计获取失败: '+e.message); return; }
    }
    
    // v2.16: @文件引用自动补全 — 检测 @[文件名](路径) 并注入文件内容
    var atFilePattern = /@\x5B([^\x5D]+)\x5D\x28([^\x29]+)\x29/g;
    var atFiles = [];
    var atMatch;
    while ((atMatch = atFilePattern.exec(msg)) !== null) {
        atFiles.push({name: atMatch[1], path: atMatch[2]});
    }
    if (atFiles.length > 0) {
        var refBlocks = [];
        for (var fi = 0; fi < atFiles.length; fi++) {
            var af = atFiles[fi];
            try {
                var refRes = await fetch('/api/file/read?path=' + encodeURIComponent(af.path));
                if (refRes.ok) {
                    var refData = await refRes.json();
                    var content = refData.content || '';
                    if (content.length > 50000) content = content.substring(0, 50000) + '\\n... (已截断)';
                    refBlocks.push('[文件引用: ' + af.name + ']\\n```\\n' + content + '\\n```');
                } else {
                    refBlocks.push('[文件引用: ' + af.name + ']\\n⚠️ 无法读取: ' + af.path);
                }
            } catch(e) {
                refBlocks.push('[文件引用: ' + af.name + ']\\n⚠️ 读取失败: ' + e.message);
            }
        }
        var refBlock = refBlocks.join('\\n\\n');
        // 去除消息中的@引用标记，保留用户实际消息
        var cleanMsg = msg.replace(atFilePattern, '').trim();
        fullMsg = refBlock + '\\n\\n用户消息: ' + (cleanMsg || '请分析以上文件内容');
        msg = atFiles.map(function(f){ return '@' + f.name; }).join(' ') + (cleanMsg ? ' ' + cleanMsg : '');
    }
    
    // v1.7: 多文件批量上传
    if (uploadedContents && uploadedContents.length > 0) {
        let fileBlock = '';
        let fnames = [];
        for (const f of uploadedContents) {
            fileBlock += '[上传文件: ' + f.filename + ']\n```\n' + f.content + '\n```\n\n';
            fnames.push(f.filename);
        }
        fullMsg = fileBlock + msg;
        const displayMsg = '[📄 ' + fnames.join(', ') + '] ' + msg;
        var msgIdx = chatHistory.length;
        var userBubble = document.createElement('div');
        userBubble.style.cssText = 'margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;';
        userBubble.innerHTML = '<strong>You:</strong> ' + displayMsg;
        var editBtn = document.createElement('button');
        editBtn.textContent = '✏️';
        editBtn.title = '编辑并重发';
        editBtn.style.cssText = 'float:right;background:transparent;border:1px solid #334155;color:#64748b;border-radius:4px;padding:1px 6px;cursor:pointer;font-size:11px;margin-left:4px;';
        editBtn.onclick = function(){ editMessage(msgIdx); };
        userBubble.appendChild(editBtn);
        div.appendChild(userBubble);
        chatHistory.push({role:'user', content:displayMsg});
        uploadedContents = [];
        document.getElementById('fileTag').style.display = 'none';
    } else {
        const displayMsg = msg;
        var msgIdx = chatHistory.length;
        var userBubble = document.createElement('div');
        userBubble.style.cssText = 'margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;';
        userBubble.innerHTML = '<strong>You:</strong> ' + displayMsg;
        var editBtn = document.createElement('button');
        editBtn.textContent = '✏️';
        editBtn.title = '编辑并重发';
        editBtn.style.cssText = 'float:right;background:transparent;border:1px solid #334155;color:#64748b;border-radius:4px;padding:1px 6px;cursor:pointer;font-size:11px;margin-left:4px;';
        editBtn.onclick = function(){ editMessage(msgIdx); };
        userBubble.appendChild(editBtn);
        div.appendChild(userBubble);
        chatHistory.push({role:'user', content:displayMsg});
    }
    saveHistory();
    input.value = '';
    clearFiles();
    
    // 创建AI消息气泡(流式填充)
    const aiBubble = document.createElement('div');
    aiBubble.style.cssText = 'margin:8px 0;padding:8px;background:#1e293b;border-radius:8px;position:relative;';
    aiBubble.innerHTML = '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;"><strong style="color:#38bdf8;">AI:</strong><button id="stopStreamBtn" onclick="event.stopPropagation();window._abortStream()" style="background:#dc2626;color:#fff;border:none;border-radius:4px;padding:2px 8px;font-size:10px;cursor:pointer;display:none;">⏹ 停止</button></div><span class="streamText"></span><span class="cursor">▊</span>';
    div.appendChild(aiBubble);
    const streamText = aiBubble.querySelector('.streamText');
    const cursor = aiBubble.querySelector('.cursor');
    const stopBtn = document.getElementById('stopStreamBtn');
    stopBtn.style.display = 'inline-block';
    
    // 流式状态指示器
    var statusEl = document.createElement('div');
    statusEl.className = 'stream-status';
    statusEl.style.cssText = 'color:#64748b;font-size:10px;margin-bottom:4px;';
    statusEl.textContent = '🔵 思考中...';
    aiBubble.insertBefore(statusEl, aiBubble.firstChild);
    
    // 全局中断函数
    window._abortStream = function(){
        streamAborted = true;
        if (innerAbortController) innerAbortController.abort();
        stopBtn.style.display = 'none';
    };
    
    // v1.5.22: 增强流式(重试+工具调用+思考折叠+中断按钮)
    let streamAborted = false;
    let retryCount = 0;
    const maxRetries = 3;
    let innerAbortController = null; // 中断当前fetch

    // v2.16: 读取当前tab的系统提示词
    var sysPrompt = (allTabs[activeTab] && allTabs[activeTab].systemPrompt) || '';

    while (retryCount <= maxRetries) {
      if (streamAborted) break;
      if (retryCount > 0) {
        // 重试前等待
        var waitMs = Math.pow(2, retryCount-1) * 1000;
        streamText.innerHTML += '<div style="color:#fbbf24;font-size:11px;margin:4px 0;">⏳ 重试 ' + retryCount + '/' + maxRetries + ' (等待' + (waitMs/1000) + 's)...</div>';
        await new Promise(function(r){setTimeout(r, waitMs);});
      }
      try {
        innerAbortController = new AbortController();
        var res = await fetch('/api/chat/stream', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message: fullMsg, model: document.getElementById('modelSelect').value, system: sysPrompt}),
          signal: innerAbortController.signal
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);

        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        while (true) {
          var readResult = await reader.read();
          if (readResult.done) break;
          buffer += decoder.decode(readResult.value, {stream: true});

          var lines = buffer.split('\n');
          buffer = lines.pop();

          for (var li = 0; li < lines.length; li++) {
            var line = lines[li];
            if (!line.startsWith('data: ')) continue;
            var data = line.slice(6);

            if (data === '[DONE]') {
              if(statusEl) statusEl.textContent = '✅ 完成 (' + new Date().toLocaleTimeString() + ')';
              if(cursor) cursor.style.display = 'none';
              chatHistory.push({role:'assistant', content:streamText.innerHTML});
              saveHistory();
              var raw = streamText.innerHTML;
              // v1.5.22: 渲染前处理工具调用/思考标记
              raw = raw.replace(/🔧\s*调用:\s*(\S+)/g, function(m,tool){
                return '<details style="background:#312e81;border-radius:6px;padding:6px;margin:6px 0;font-size:12px;"><summary style="cursor:pointer;color:#a5b4fc;">🔧 工具调用: '+tool+'</summary><pre style="background:#1e1b4b;padding:6px;border-radius:4px;overflow-x:auto;max-height:200px;"></pre></details>';
              });
              raw = raw.replace(/💭\s*思考:/g, function(m){
                return '<details style="background:#1e293b;border-radius:6px;padding:6px;margin:6px 0;font-size:12px;"><summary style="cursor:pointer;color:#94a3b8;">💭 思考过程</summary><div style="padding:6px;color:#94a3b8;">';
              });
              raw = raw.replace(/💭结束/g, '</div></details>');
              streamText.innerHTML = marked.parse(raw);
              streamText.querySelectorAll('pre code').forEach(function(b){hljs.highlightElement(b);});
              enhanceCodeBlocks(streamText);
              // 复制按钮
              var copyBtn = document.createElement('button');
              copyBtn.textContent = '📋';
              copyBtn.title = '复制回复';
              copyBtn.style.cssText = 'float:right;background:transparent;border:1px solid #334155;color:#64748b;border-radius:4px;padding:1px 6px;cursor:pointer;font-size:11px;';
              copyBtn.onclick = function(){
                var txt = streamText.textContent;
                navigator.clipboard.writeText(txt).then(function(){
                  copyBtn.textContent = '✅';
                  setTimeout(function(){copyBtn.textContent='📋';},1500);
                });
              };
              aiBubble.insertBefore(copyBtn, aiBubble.firstChild);
              retryCount = maxRetries + 1; // 成功，跳出重试循环
              continue;
            }

            try {
              var parsed = JSON.parse(data);
              if (parsed.error) {
                streamText.innerHTML += '<span style="color:#fca5a5;">' + parsed.error + '</span>';
                cursor.remove();
                throw new Error(parsed.error); // 触发重试
              } else if (parsed.token) {
                var token = parsed.token.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                streamText.innerHTML += token;
                // 首token到达，更新状态
                if(statusEl && statusEl.textContent === '🔵 思考中...') {
                    statusEl.textContent = '🟢 生成中...';
                }
              } else if (parsed.tool_call) {
                // v1.5.22: 工具调用内联展示
                streamText.innerHTML += '<div style="background:#312e81;border-radius:6px;padding:6px;margin:4px 0;font-size:12px;"><span style="color:#a5b4fc;">🔧 '+parsed.tool_call+'</span></div>';
              }
            } catch(parseErr) {
              // 忽略解析错误
            }
          }
        }
      } catch(e) {
        if (e.name === 'AbortError') {
          streamText.innerHTML += '<span style="color:#fbbf24;">⏹ 已中断</span>';
          cursor.remove();
          break;
        }
        retryCount++;
        if (retryCount > maxRetries) {
          streamText.innerHTML += '<span style="color:#fca5a5;">❌ 失败(重试' + maxRetries + '次): ' + e.message + '</span>';
          cursor.remove();
        }
      }
    }
    div.scrollTop = div.scrollHeight;
}

// 拖拽上传
const chatCard = document.getElementById('chatCard');
chatCard.addEventListener('dragover', function(e) {
    e.preventDefault();
    e.stopPropagation();
    chatCard.style.borderColor = '#38bdf8';
});
chatCard.addEventListener('dragleave', function(e) {
    e.preventDefault();
    e.stopPropagation();
    chatCard.style.borderColor = '';
});
chatCard.addEventListener('drop', function(e) {
    e.preventDefault();
    e.stopPropagation();
    chatCard.style.borderColor = '';
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        document.getElementById('fileInput').files = files;
        uploadFile();
    }
});

// v1.5.9: Desktop快速提问监听
window.addEventListener('message', function(e){
  var d = e.data;
  if(d && d.type === 'meshctx-quick-ask' && d.message){
    document.getElementById('userInput').value = d.message;
    send();
  }
});

// ═══ v1.5.19 增强代码运行引擎 ═══
var _runningAbort = null; // 运行中的AbortController

async function runCodeBlock(code, lang, preEl){
  var wrapper = preEl.parentNode;
  // 移除旧输出
  var oldOut = wrapper.querySelector('.code-output');
  if(oldOut) oldOut.remove();
  
  var runBtn = wrapper.querySelector('.run-btn');
  if(runBtn){ runBtn.textContent = '⏳'; runBtn.disabled = true; runBtn.title='运行中...'; }
  
  // 显示停止按钮
  var stopBtn = wrapper.querySelector('.stop-btn');
  if(stopBtn) stopBtn.style.display = 'inline-block';
  
  // 创建输出区域
  var output = document.createElement('div');
  output.className = 'code-output';
  output.innerHTML = '<div class="code-output-header"><span>▶ 输出</span><button class="output-toggle" onclick="this.parentNode.nextSibling.classList.toggle(\'collapsed\');this.textContent=this.textContent===\'展开\'?\'收起\':\'展开\'">收起</button></div><pre class="code-output-body" style="margin:0;padding:8px;white-space:pre-wrap;word-break:break-all;max-height:400px;overflow-y:auto;">⏳ 执行中...</pre>';
  wrapper.appendChild(output);
  
  var outBody = output.querySelector('.code-output-body');
  var startTime = Date.now();
  
  // 创建AbortController用于停止
  _runningAbort = new AbortController();
  
  try {
    var res = await fetch('/api/code/run', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:code, lang:lang||'python', timeout:30}),
      signal: _runningAbort.signal
    });
    var elapsed = ((Date.now()-startTime)/1000).toFixed(1);
    var d = await res.json();
    if(d.error){
      outBody.style.color = '#fca5a5';
      outBody.textContent = '❌ ' + d.error + '\n\n⏱ ' + elapsed + 's';
      output.querySelector('.code-output-header span').textContent = '✗ 错误';
      output.querySelector('.code-output-header span').style.color = '#fca5a5';
    } else {
      outBody.textContent = (d.output||'(无输出)') + (d.exit_code!==undefined ? '\n\n[退出码: '+d.exit_code+' | ⏱ '+elapsed+'s]' : '\n\n[⏱ '+elapsed+'s]');
      if(d.exit_code===0){
        outBody.style.color = '#22c55e';
        output.querySelector('.code-output-header span').textContent = '✓ 成功';
        output.querySelector('.code-output-header span').style.color = '#22c55e';
      } else {
        outBody.style.color = '#fbbf24';
        output.querySelector('.code-output-header span').textContent = '⚠ 警告';
        output.querySelector('.code-output-header span').style.color = '#fbbf24';
      }
    }
    // 长输出自动折叠
    if(outBody.textContent.length > 500){
      outBody.classList.add('collapsed');
      outBody.style.maxHeight = '120px';
      output.querySelector('.output-toggle').textContent = '展开';
    }
  } catch(e){
    if(e.name === 'AbortError'){
      outBody.style.color = '#fbbf24';
      outBody.textContent = '⏹ 已手动停止';
      output.querySelector('.code-output-header span').textContent = '⏹ 已停止';
    } else {
      outBody.style.color = '#fca5a5';
      outBody.textContent = '❌ 请求失败: ' + e.message;
      output.querySelector('.code-output-header span').textContent = '✗ 失败';
    }
  }
  
  if(runBtn){ runBtn.textContent = '▶'; runBtn.disabled = false; runBtn.title='运行此代码块'; }
  if(stopBtn) stopBtn.style.display = 'none';
  _runningAbort = null;
}

function stopCodeBlock(){
  if(_runningAbort){
    _runningAbort.abort();
    _runningAbort = null;
  }
}

// 复制代码块内容
function copyCodeBlock(code, btn){
  navigator.clipboard.writeText(code).then(function(){
    btn.textContent = '✓';
    setTimeout(function(){ btn.textContent = '📋'; }, 1500);
  });
}

// 为代码块添加增强UI (运行/复制/语言标签)
function enhanceCodeBlocks(container){
  container.querySelectorAll('pre').forEach(function(pre){
    if(pre.querySelector('.run-btn')) return; // 已完成
    var code = pre.querySelector('code');
    if(!code) return;
    var lang = '';
    var cls = code.className || '';
    var m = cls.match(/language-(\\w+)/);
    if(m) lang = m[1];
    else if(code.className.match(/python|py/)) lang='python';
    
    var wrapper = document.createElement('div');
    wrapper.className = 'code-block-wrapper';
    wrapper.style.cssText = 'position:relative;margin:8px 0;border:1px solid #30363d;border-radius:8px;overflow:hidden;background:#0d1117;';
    
    // 顶部工具栏
    var toolbar = document.createElement('div');
    toolbar.style.cssText = 'display:flex;align-items:center;justify-content:space-between;padding:4px 8px;background:#161b22;border-bottom:1px solid #30363d;font-size:12px;';
    
    var langLabel = document.createElement('span');
    langLabel.textContent = lang || 'code';
    langLabel.style.cssText = 'color:#8b949e;font-weight:600;text-transform:uppercase;letter-spacing:1px;font-size:10px;';
    toolbar.appendChild(langLabel);
    
    var actions = document.createElement('span');
    
    // 复制按钮
    var copyBtn = document.createElement('button');
    copyBtn.textContent = '📋';
    copyBtn.title = '复制代码';
    copyBtn.style.cssText = 'background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:1px 6px;cursor:pointer;font-size:11px;margin-right:4px;';
    copyBtn.onclick = function(){ copyCodeBlock(code.textContent, copyBtn); };
    actions.appendChild(copyBtn);
    
    // HTML预览按钮 (仅html/js/css)
    if(lang.match(/^(html|js|javascript|css|svg)$/)){
      var previewBtn = document.createElement('button');
      previewBtn.textContent = '🌐';
      previewBtn.title = '预览HTML';
      previewBtn.style.cssText = 'background:transparent;border:1px solid #30363d;color:#8b949e;border-radius:4px;padding:1px 6px;cursor:pointer;font-size:11px;margin-right:4px;';
      previewBtn.onclick = function(){ previewHTML(code.textContent, wrapper); };
      actions.appendChild(previewBtn);
    }
    
    // 运行按钮
    var runBtn = document.createElement('button');
    runBtn.textContent = '▶';
    runBtn.title = '运行此代码块 (Python/Bash/JS)';
    runBtn.className = 'run-btn';
    runBtn.style.cssText = 'background:#2563eb;color:#fff;border:none;border-radius:4px;padding:1px 8px;font-size:11px;cursor:pointer;';
    runBtn.onclick = function(){ runCodeBlock(code.textContent, lang, pre); };
    actions.appendChild(runBtn);
    
    // 停止按钮 (默认隐藏)
    var stopBtn = document.createElement('button');
    stopBtn.textContent = '⏹';
    stopBtn.title = '停止运行';
    stopBtn.className = 'stop-btn';
    stopBtn.style.cssText = 'display:none;background:#dc2626;color:#fff;border:none;border-radius:4px;padding:1px 8px;font-size:11px;cursor:pointer;margin-left:4px;';
    stopBtn.onclick = stopCodeBlock;
    actions.appendChild(stopBtn);
    
    toolbar.appendChild(actions);
    wrapper.appendChild(toolbar);
    
    // 代码块
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);
    
    // 行号增强
    var lines = code.innerHTML.split('\n');
    var lineCount = lines.length;
    var nums = '';
    for(var i=1; i<=lineCount; i++) {
        nums += '<span>' + i + '</span>\n';
    }
    var lineNum = document.createElement('div');
    lineNum.className = 'line-numbers';
    lineNum.innerHTML = nums;
    lineNum.style.cssText = 'padding:8px 8px 8px 0;margin-right:12px;border-right:1px solid #334155;color:#64748b;font-size:11px;text-align:right;user-select:none;min-width:30px;line-height:1.5;';
    pre.style.cssText = 'display:flex;margin:0;border-radius:0;';
    pre.insertBefore(lineNum, pre.firstChild);
    code.style.cssText = 'flex:1;padding:8px 0;overflow-x:auto;';
  });
}

function previewHTML(code, wrapper){
  var oldPreview = wrapper.querySelector('.html-preview');
  if(oldPreview){ oldPreview.remove(); return; }
  
  var preview = document.createElement('div');
  preview.className = 'html-preview';
  preview.style.cssText = 'border-top:1px solid #30363d;background:#fff;min-height:200px;max-height:500px;overflow:auto;';
  var iframe = document.createElement('iframe');
  iframe.style.cssText = 'width:100%;height:300px;border:none;';
  iframe.sandbox = 'allow-scripts allow-same-origin';
  iframe.srcdoc = code;
  preview.appendChild(iframe);
  wrapper.appendChild(preview);
}

function quickAction(action) {
    var input = document.getElementById('userInput');
    var current = input.value.trim();
    if(current) {
        input.value = action + ':\n' + current;
    } else {
        input.value = action;
    }
    input.focus();
}

// 为历史消息中代码块添加运行按钮 (兼容旧版)
function addCodeRunButtons(container){
  enhanceCodeBlocks(container);
}</script>
{% endblock %}"""

_TEMPLATES["setup.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>⚙️ 模型管理</h2>

{% if flash == "success" %}
<div class="flash flash-success">✅ 已保存！配置自动生效。</div>
{% elif flash == "error" %}
<div class="flash flash-error">❌ 操作失败。</div>
{% elif flash == "deleted" %}
<div class="flash flash-success">🗑 已删除。</div>
{% endif %}

<div style="display:flex;justify-content:space-between;align-items:center;margin:16px 0;">
    <h3 style="margin:0;">已配置模型 <span style="color:var(--accent);" id="modelCount">{{ configured|length }}</span></h3>
    <button class="btn btn-primary" onclick="showAddForm()" style="padding:10px 20px;">+ 添加模型</button>
</div>

<!-- v2.17: 本地模型快捷预设 -->
<div style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:6px;">
    <span style="font-size:12px;color:var(--muted);line-height:28px;">快捷预设:</span>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('ollama','qwen2.5:7b','Ollama本地','http://localhost:11434/v1','')">🦙 Ollama</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('vllm','qwen','vLLM本地','http://localhost:8000/v1','')">🚀 vLLM</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('localai','gpt-3.5-turbo','LocalAI','http://localhost:8080/v1','')">🏠 LocalAI</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('openai-compat','gpt-3.5-turbo','OpenAI兼容','https://your-api.com/v1','sk-...')">🔌 通用OpenAI</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('custom','custom-model','自定义供应商','https://your-server.com','your-key')">⚙️ 完全自定义</button>
</div>

<!-- 添加/编辑表单(默认隐藏) -->
<div id="modelForm" style="display:none;margin-bottom:16px;">
    <div class="card">
        <h3 id="formTitle">添加模型</h3>
        <input type="hidden" id="editModelId">
        <div class="form-group"><label>模型ID</label><input id="fid" placeholder="deepseek:chat"></div>
        <div class="form-group"><label>提供商</label><input id="fprovider" placeholder="deepseek"></div>
        <div class="form-group"><label>API Key</label><input id="fkey" type="password" placeholder="sk-..."></div>
        <div class="form-group"><label>模型名(可选)</label><input id="fmodel" placeholder="auto"></div>
        <div class="form-group"><label>Base URL(可选)</label><input id="furl" placeholder="auto"></div>
        <div style="display:flex;gap:8px;">
            <button class="btn btn-primary" onclick="saveModel()">💾 保存</button>
            <button class="btn btn-ghost" onclick="hideForm()">取消</button>
            <button class="btn btn-ghost" onclick="testFromForm()" style="margin-left:auto;">🔍 测试连接</button>
        </div>
        <div id="testResult" style="margin-top:8px;font-size:13px;"></div>
    </div>
</div>

<!-- 模型列表 + 状态统计 -->
{% set all_models = configured %}
<div class="card" style="overflow-x:auto;">
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div>
        <span style="color:var(--muted);font-size:12px;">
            🟢 <b id="readyCount">{{ all_models|selectattr('ready')|list|length }}</b> 已配置
            &nbsp;🔴 <b id="unreadyCount">{{ all_models|rejectattr('ready')|list|length }}</b> 未配置
        </span>
    </div>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;color:#f85149;" onclick="cleanUnconfigured()">🗑 清理未配置</button>
</div>
{% if has_more_unconfigured %}
<div style="text-align:center;margin-bottom:12px;">
    <span style="color:var(--muted);font-size:11px;">仅显示前20个未配置模型 (共{{ total_unconfigured }}个)</span>
    <a href="?all=1" style="color:var(--accent);font-size:11px;margin-left:8px;">展开全部 →</a>
</div>
{% endif %}
<table style="width:100%;border-collapse:collapse;font-size:13px;">
<thead><tr style="border-bottom:1px solid var(--border);text-align:left;color:var(--muted);">
    <th style="padding:8px;">状态</th>
    <th style="padding:8px;">模型ID</th>
    <th style="padding:8px;">提供商</th>
    <th style="padding:8px;">端点</th>
    <th style="padding:8px;">Key</th>
    <th style="padding:8px;">操作</th>
</tr></thead>
<tbody>
{% for m in all_models %}
{% set is_ready = m.ready|default(true) %}
{% set is_def = m.is_default|default(false) %}
<tr style="border-bottom:1px solid var(--border);{% if is_def %}background:rgba(108,92,231,0.08);{% endif %}" data-id="{{ m.id }}">
    <td style="padding:8px;">
        {% if is_def %}
        <span style="background:var(--accent);color:#fff;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;">⭐ 默认</span>
        {% elif is_ready %}
        <span style="color:#22c55e;font-size:11px;">🟢 已配置</span>
        {% else %}
        <span style="color:#f85149;font-size:11px;">🔴 未配置</span>
        {% endif %}
    </td>
    <td style="padding:8px;">
        <strong>{{ m.id }}</strong>
        {% if m.model and m.model != m.id %}<br><span style="font-size:10px;color:var(--muted);">→ {{ m.model }}</span>{% endif %}
    </td>
    <td style="padding:8px;">{{ m.provider }}</td>
    <td style="padding:8px;">
        {% if m.base_url %}
        <code style="font-size:10px;background:#1e293b;padding:1px 4px;border-radius:3px;max-width:120px;display:inline-block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{{ m.base_url }}">{{ m.base_url }}</code>
        {% elif is_ready %}
        <span style="color:var(--muted);font-size:10px;">默认</span>
        {% else %}
        <span style="color:#f85149;font-size:10px;">未设置</span>
        {% endif %}
    </td>
    <td style="padding:8px;">
        {% if m.key_masked %}
        <code style="font-size:10px;background:#1e293b;padding:2px 6px;border-radius:4px;">{{ m.key_masked }}</code>
        {% else %}
        <span style="color:#f85149;font-size:10px;">—</span>
        {% endif %}
    </td>
    <td style="padding:8px;">
        <div style="display:flex;gap:4px;">
            {% if is_ready %}
            <button class="btn btn-ghost" style="font-size:11px;padding:2px 8px;" onclick="editModel('{{ m.id }}','{{ m.provider }}','{{ m.key_full or '' }}','{{ m.model }}','{{ m.base_url or '' }}')">✏️</button>
            <button class="btn btn-ghost" style="font-size:11px;padding:2px 8px;" onclick="testModel('{{ m.id }}')">🔍</button>
            {% if not is_def %}
            <button class="btn btn-ghost" style="font-size:11px;padding:2px 8px;color:#22c55e;" onclick="setDefault('{{ m.id }}')">⭐默认</button>
            {% endif %}
            {% else %}
            <button class="btn btn-ghost" style="font-size:11px;padding:2px 8px;color:var(--accent);" onclick="configureModel('{{ m.id }}')">⚡ 配置</button>
            {% endif %}
            {% if not is_def %}
            <button class="btn btn-ghost" style="font-size:11px;padding:2px 8px;color:#f85149;" onclick="if(confirm('确定删除 {{ m.id }}?'))deleteModel('{{ m.id }}')">✕</button>
            {% endif %}
        </div>
    </td>
</tr>
{% endfor %}
</tbody></table>
</div>

{% if not all_models %}
<div class="card" style="text-align:center;padding:40px;color:var(--muted);">
    <p style="font-size:48px;margin-bottom:12px;">🔑</p>
    <p>尚未配置任何模型。点击上方「+ 添加模型」开始。</p>
</div>
{% endif %}

<!-- 获取Key链接 -->
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:16px;">
    <a href="https://platform.deepseek.com/api_keys" target="_blank" class="card" style="text-align:center;text-decoration:none;color:inherit;padding:12px;">
        <span>🟢 DeepSeek</span><br><span style="color:#38bdf8;font-size:11px;">获取 Key →</span>
    </a>
    <a href="https://bailian.console.aliyun.com/" target="_blank" class="card" style="text-align:center;text-decoration:none;color:inherit;padding:12px;">
        <span>🔵 阿里百炼</span><br><span style="color:#38bdf8;font-size:11px;">获取 Key →</span>
    </a>
    <a href="https://siliconflow.cn/" target="_blank" class="card" style="text-align:center;text-decoration:none;color:inherit;padding:12px;">
        <span>🔴 硅基流动</span><br><span style="color:#38bdf8;font-size:11px;">获取 Key →</span>
    </a>
</div>

<script>
function showAddForm() {
    document.getElementById('modelForm').style.display = 'block';
    document.getElementById('formTitle').textContent = '添加模型';
    document.getElementById('editModelId').value = '';
    document.getElementById('fid').value = ''; document.getElementById('fid').disabled = false;
    document.getElementById('fprovider').value = 'deepseek';
    document.getElementById('fkey').value = '';
    document.getElementById('fmodel').value = '';
    document.getElementById('furl').value = '';
    document.getElementById('testResult').innerHTML = '';
}
function hideForm() { document.getElementById('modelForm').style.display = 'none'; }

function presetModel(id, model, provider, url, key) {
    showAddForm();
    document.getElementById('fid').value = id;
    document.getElementById('fprovider').value = provider;
    document.getElementById('fkey').value = key;
    document.getElementById('fmodel').value = model;
    document.getElementById('furl').value = url;
    document.getElementById('fid').focus();
}

function editModel(id, provider, key, model, url) {
    showAddForm();
    document.getElementById('formTitle').textContent = '编辑 ' + id;
    document.getElementById('editModelId').value = id;
    document.getElementById('fid').value = id;
    document.getElementById('fid').disabled = false;
    document.getElementById('fprovider').value = provider;
    document.getElementById('fkey').value = key;
    document.getElementById('fmodel').value = model;
    document.getElementById('furl').value = url||'';
}

async function saveModel() {
    var eid = document.getElementById('editModelId').value.trim();
    var newId = document.getElementById('fid').value.trim();
    var body = {
        id: newId,
        provider: document.getElementById('fprovider').value.trim(),
        key: document.getElementById('fkey').value.trim(),
        model: document.getElementById('fmodel').value.trim(),
        base_url: document.getElementById('furl').value.trim(),
    };
    if (!body.id || !body.provider) { alert('ID和提供商为必填'); return; }
    if (!body.key && !body.base_url) { alert('请填写API Key或Base URL'); return; }
    
    try {
        var res, data;
        if (eid && eid !== newId) {
            // Rename: update old entry with new ID
            res = await fetch('/api/models/' + eid, {
                method: 'PATCH',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({rename_to: newId, key: body.key, model: body.model, base_url: body.base_url, provider: body.provider})
            });
        } else if (eid) {
            res = await fetch('/api/models/' + eid, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({key: body.key, model: body.model, base_url: body.base_url, provider: body.provider})
            });
        } else {
            body.overwrite = true;
            res = await fetch('/api/models', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
        }
        data = await res.json();
        if (res.ok) { location.reload(); }
        else { alert('失败: ' + (data.detail||data.message||JSON.stringify(data))); }
    } catch(e) { alert('网络错误: ' + e.message); }
}
async function deleteModel(id) {
    try {
        var res = await fetch('/api/models/' + id, {method: 'DELETE'});
        if (res.ok) location.reload();
        else { var d = await res.json(); alert('失败: ' + (d.detail||'')); }
    } catch(e) { alert('错误: ' + e.message); }
}
async function setDefault(id) {
    try {
        var res = await fetch('/api/models/' + id + '/default', {method: 'PATCH'});
        if (res.ok) location.reload();
        else { var d = await res.json(); alert('失败: ' + (d.detail||'')); }
    } catch(e) { alert('错误: ' + e.message); }
}
async function cleanUnconfigured() {
    if (!confirm('确定删除所有未配置Key的模型吗？此操作不可撤销。')) return;
    try {
        var res = await fetch('/api/models/clean-unconfigured', {method: 'POST'});
        var d = await res.json();
        alert('已清理 ' + (d.deleted || 0) + ' 个未配置模型');
        location.reload();
    } catch(e) { alert('错误: ' + e.message); }
}
function configureModel(id) {
    showAddForm();
    document.getElementById('fid').value = id;
    document.getElementById('fid').disabled = false;
    document.getElementById('editModelId').value = id;
    document.getElementById('formTitle').textContent = '配置 API Key — ' + id;
    document.getElementById('fkey').focus();
}
async function testModel(id) {
    var tr = document.querySelector('tr[data-id="' + id + '"]');
    if (tr) tr.style.background = '#1a2a1a';
    try {
        var res = await fetch('/api/models/' + id + '/test', {method: 'POST'});
        var d = await res.json();
        if (d.status === 'ok') alert('✅ ' + id + ' 连接成功');
        else alert('❌ ' + id + ': ' + (d.message||'失败'));
    } catch(e) { alert('错误: ' + e.message); }
    if (tr) tr.style.background = '';
}
async function testFromForm() {
    var id = document.getElementById('fid').value.trim();
    if (!id) { alert('请先输入模型ID'); return; }
    document.getElementById('testResult').innerHTML = '⏳ 测试中...';
    try {
        var res = await fetch('/api/models/' + id + '/test', {method: 'POST'});
        var d = await res.json();
        document.getElementById('testResult').innerHTML = d.status === 'ok' 
            ? '<span style="color:#22c55e;">✅ ' + d.message + '</span>'
            : '<span style="color:#f85149;">❌ ' + (d.message||'失败') + '</span>';
    } catch(e) { document.getElementById('testResult').innerHTML = '<span style="color:#f85149;">错误: ' + e.message + '</span>'; }
}
</script>
{% endblock %}"""

_TEMPLATES["desktop.html"] = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>meshctx Desktop</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
  --accent2: #3fb950; --warn: #d29922; --danger: #f85149;
}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--bg);color:var(--text);
  display:flex;flex-direction:column;
}
.topbar{
  background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:12px;padding:8px 16px;
  min-height:44px;
}
.topbar .logo{font-size:16px;font-weight:700;color:var(--accent);white-space:nowrap;}
.topbar .logo .v{font-size:11px;color:var(--muted);font-weight:400;}
.topbar .spacer{flex:1;}
.topbar select,.topbar button{
  background:var(--bg);color:var(--text);border:1px solid var(--border);
  padding:5px 10px;border-radius:6px;font-size:12px;cursor:pointer;
}
.topbar select:hover,.topbar button:hover{border-color:var(--accent);}
.topbar .status-dot{width:8px;height:8px;border-radius:50%;background:var(--accent2);box-shadow:0 0 6px var(--accent2);margin-left:-6px;}
.topbar .live-indicator{transition:transform 0.15s ease;}font-size:11px;color:var(--muted);margin-left:4px;}
.tabbar{
  background:var(--surface);border-bottom:1px solid var(--border);
  display:flex;padding:0 16px;
}
.tabbar .tab{
  padding:10px 20px;font-size:13px;cursor:pointer;
  border:none;background:none;color:var(--muted);
  border-bottom:2px solid transparent;transition:all .15s;
  font-family:inherit;
}
.tabbar .tab:hover{color:var(--text);}
.tabbar .tab.active{color:var(--accent);border-bottom-color:var(--accent);}
.content{flex:1;overflow:hidden;position:relative;}
.content .pane{display:none;height:100%;overflow:auto;}
.content .pane.active{display:flex;flex-direction:column;}
.content iframe{border:none;width:100%;height:100%;}
.pane-inner{padding:16px;overflow-y:auto;flex:1;}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px;}
.stat-card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:14px;text-align:center;
}
.stat-card .value{font-size:26px;font-weight:700;color:var(--accent);}
.stat-card .v-green{color:var(--accent2);}
.stat-card .v-warn{color:var(--warn);}
.stat-card .v-red{color:var(--danger);}
.stat-card .label{font-size:11px;color:var(--muted);margin-top:3px;}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:16px;margin-bottom:12px;
}
.card h2{font-size:13px;color:var(--muted);margin-bottom:10px;font-weight:600;
  display:flex;align-items:center;gap:8px;}
.card .empty{color:var(--muted);font-size:13px;text-align:center;padding:20px;}
.row{
  display:flex;align-items:center;gap:10px;
  padding:7px 0;border-bottom:1px solid var(--border);
  font-size:12px;
}
.row:last-child{border-bottom:none;}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.dot.on{background:var(--accent2);box-shadow:0 0 6px var(--accent2);}
.dot.off{background:var(--border);}
.dot.warn{background:var(--warn);box-shadow:0 0 6px var(--warn);}
.dot.err{background:var(--danger);box-shadow:0 0 6px var(--danger);}
.tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:600;}
.tag-ok{background:#065f46;color:#6ee7b7;}
.tag-warn{background:#451a03;color:#fbbf24;}
.tag-err{background:#7f1d1d;color:#fca5a5;}
.tag-info{background:#1e3a5f;color:#93c5fd;}
.meta{font-size:10px;color:var(--muted);}
.loading{color:var(--muted);font-size:12px;padding:12px;}
.spin{display:inline-block;animation:spin 1s linear infinite;}@keyframes spin{to{transform:rotate(360deg)}}
.error-block{color:var(--danger);font-size:11px;padding:8px;}
.refresh-btn{font-size:10px;padding:2px 8px;margin-left:8px;cursor:pointer;background:var(--bg);color:var(--muted);border:1px solid var(--border);border-radius:4px;}
.timeline{max-height:200px;overflow-y:auto;font-size:11px;}
.timeline .tl-item{padding:4px 0;border-bottom:1px solid var(--border);display:flex;gap:8px;}
.timeline .tl-time{color:var(--muted);white-space:nowrap;min-width:60px;}
.timeline .tl-type{color:var(--accent);min-width:55px;font-weight:600;}
.timeline .tl-detail{color:var(--text);flex:1;}
.gauge-wrap{text-align:center;padding:8px;}
.gauge-value{font-size:40px;font-weight:700;}
.ooda-box{
  display:flex;gap:6px;padding:12px 0;overflow-x:auto;align-items:center;
}
.ooda-step{
  background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:10px 14px;text-align:center;
  min-width:70px;flex-shrink:0;
}
.ooda-step .letter{font-size:22px;font-weight:700;}
.ooda-step .name{font-size:10px;color:var(--muted);}
.ooda-step.active{border-width:2px;}
.ooda-step.O{border-color:#58a6ff;}.ooda-step.O .letter{color:#58a6ff;}
.ooda-step.Oo{border-color:#3fb950;}.ooda-step.Oo .letter{color:#3fb950;}
.ooda-step.D{border-color:#d29922;}.ooda-step.D .letter{color:#d29922;}
.ooda-step.A{border-color:#f85149;}.ooda-step.A .letter{color:#f85149;}
.ooda-arrow{font-size:18px;color:var(--muted);}
.progress-bar{height:6px;background:var(--border);border-radius:3px;margin-top:6px;overflow:hidden;}
.progress-fill{height:100%;border-radius:3px;transition:width .5s;}
.setup-hint{text-align:center;padding:40px;color:var(--muted);}
.setup-hint .icon{font-size:48px;margin-bottom:12px;}
.setup-hint a{color:var(--accent);}
.auto-refresh{font-size:10px;color:var(--muted);}
.plugin-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;}
.plugin-card{
  background:var(--bg);border:1px solid var(--border);
  border-radius:8px;padding:12px;
}
.plugin-card .pname{font-size:13px;font-weight:600;margin-bottom:4px;}
.plugin-card .pmeta{font-size:10px;color:var(--muted);}
.action-btn{
  font-size:11px;padding:4px 12px;border-radius:6px;cursor:pointer;
  border:1px solid var(--border);background:var(--bg);color:var(--text);
  font-family:inherit;transition:all .15s;
}
.action-btn:hover{border-color:var(--accent);}
.action-btn.start-btn{color:var(--accent2);border-color:var(--accent2);}
.action-btn.start-btn:hover{background:#065f46;}
.action-btn.stop-btn{color:var(--danger);border-color:var(--danger);}
.action-btn.stop-btn:hover{background:#7f1d1d;}
.action-btn:disabled{opacity:0.5;cursor:not-allowed;}

/* v1.5.4: OODA相位脉冲动画 */
@keyframes phasePulse {
  0%,100%{box-shadow:0 0 0 0 rgba(0,208,132,0.4);}
  50%{box-shadow:0 0 0 6px rgba(0,208,132,0);}
}
.phase-observing{background:var(--accent);}
.phase-orienting{background:#ffa940;}
.phase-deciding{background:#ff7875;}
.phase-acting{background:#36cfc9;}
.phase-active{animation:phasePulse 2s ease-in-out infinite;border-radius:50%;display:inline-block;width:10px;height:10px;margin-right:4px;vertical-align:middle;}
.phase-badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:9px;color:#000;font-weight:600;margin-left:6px;}

/* v1.5.4: 下载Banner */
.dl-banner{background:linear-gradient(135deg,#1a1a3e,#2a1a5e);border:1px solid var(--border);border-radius:10px;padding:12px 16px;margin-bottom:12px;display:flex;align-items:center;gap:12px;}
.dl-banner .dlicon{font-size:20px;}
.dl-banner .dltxt{flex:1;font-size:12px;line-height:1.6;}
.dl-banner .dltxt b{color:var(--accent);}
.dl-btn{background:var(--accent);color:#000;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-weight:600;font-size:11px;text-decoration:none;display:inline-block;}
.dl-btn:hover{filter:brightness(1.2);}
.heal-chain{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0;}
.heal-node{padding:3px 10px;border-radius:12px;font-size:10px;border:1px solid var(--border);display:flex;align-items:center;gap:4px;}
.heal-node.ok{border-color:var(--accent);color:var(--accent);}
.heal-node.warn{border-color:#ffa940;color:#ffa940;}
.heal-node .heal-dot{width:6px;height:6px;border-radius:50%;display:inline-block;}
.heal-node.ok .heal-dot{background:var(--accent);}
.heal-node.warn .heal-dot{background:#ffa940;}

select#quickModel{
  background:var(--bg);color:var(--text);border:1px solid var(--border);
  border-radius:6px;padding:4px 8px;font-size:11px;max-width:180px;
  cursor:pointer;font-family:inherit;
}
select#quickModel:focus{outline:none;border-color:var(--accent);}
</style>
</head>
<body>
<div class="topbar">
  <span class="logo">🕸 meshctx <span class="v">Desktop v2.15</span></span>
  <span class="status-dot" id="sysDot" title="系统状态"></span>
  <span class="live-indicator" id="liveTag"></span>
  <span class="spacer"></span>
  <form onsubmit="quickAsk(event)" style="display:flex;gap:4px;align-items:center;">
    <input type="text" id="quickInput" placeholder="快速提问..." style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:11px;width:140px;font-family:inherit;">
    <button type="submit" style="background:var(--accent);color:#000;border:none;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;font-weight:600;">发送</button>
  </form>
  <button onclick="toggleTheme()" title="切换明暗主题" style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:4px 8px;cursor:pointer;font-size:14px;" id="themeBtn">🌓</button>
  <a href="/ui/download" title="下载Windows客户端" style="text-decoration:none;font-size:13px;padding:4px 6px;">💻</a>
  <select id="quickModel" onchange="switchQuickModel()" title="快速切换模型">
    <option value="">加载中...</option>
  </select>
  <button onclick="window.open('/ui/setup','_blank')" title="设置">⚙</button>
</div>
<div id="updateBar" style="display:none;background:linear-gradient(135deg,#8b5cf6,#06b6d4);color:#fff;padding:8px 16px;text-align:center;font-size:12px;cursor:pointer;" onclick="window.open('https://github.com/LucyAndLuna2023/meshctx/releases/latest','_blank')">🚀 新版本可用！点击下载 →</div>
<div class="tabbar" id="tabbar">
  <button class="tab active" data-pane="chat">💬 Chat</button>
  <button class="tab" data-pane="agent">🤖 Agent</button>
  <button class="tab" data-pane="monitor">📊 Monitor</button>
  <button class="tab" data-pane="providers">🔌 供应商</button>
  <button class="tab" data-pane="lab">🧪 Lab</button>
  <button class="tab" data-pane="history">📜 历史</button>
  <button class="tab" data-pane="brain">🧠 Brain</button>
  <button class="tab" data-pane="plugins-dt">🔌 Plugins</button>
  <button class="tab" data-pane="sandbox-dt">🖥️ Sandbox</button>
  <button class="tab" data-pane="project-dt">📂 Project</button>
  <button class="tab" data-pane="win-dt">🪟 Windows</button>
</div>
<div class="content">
  <div class="pane active" id="pane-chat">
    <iframe src="/ui/chat" id="chatFrame"></iframe>
  </div>
  <div class="pane" id="pane-agent">
    <div class="pane-inner">
      <div class="stats-grid" id="agentStats"></div>
      <div class="card">
        <h2>🌀 OODA 循环 <span class="auto-refresh" id="oodaRefreshTag"></span>
          <span style="flex:1"></span>
          <button class="action-btn start-btn" id="btnAgentStart" onclick="controlAgent('start')" title="启动Agent循环">▶ 启动</button>
          <button class="action-btn stop-btn" id="btnAgentStop" onclick="controlAgent('stop')" title="停止Agent循环" style="display:none">⏹ 停止</button>
        </h2>
        <div class="ooda-box" id="oodaBox"></div>
      </div>
      <div class="card">
        <h2>📋 最近任务</h2>
        <div id="agentTaskList"></div>
      </div>
    </div>
  </div>
  <div class="pane" id="pane-monitor">
    <div class="pane-inner">
      <div class="dl-banner">
        <span class="dlicon">💻</span>
        <span class="dltxt">
          <b>meshctx Desktop v1.5</b> — Windows原生客户端，下载即用<br>
          <span style="font-size:10px;color:var(--muted);">自动构建 · 每次提交均编译最新 .exe + NSIS 安装程序</span>
        </span>
        <a class="dl-btn" href="https://github.com/LucyAndLuna2023/meshctx/actions/workflows/build-windows.yml" target="_blank">⬇ 构建页</a>
      </div>
      <div class="stats-grid" id="monitorStats"></div>
      <div class="card">
        <h2>⚙ 系统资源</h2>
        <div id="sysResources" style="display:flex;gap:12px;flex-wrap:wrap;"></div>
      </div>
      <div class="card">
        <h2>❤️ 插件健康</h2>
        <div class="plugin-grid" id="pluginHealth"></div>
      </div>
      <div class="card">
        <h2>🩺 自愈链路</h2>
        <div class="heal-chain" id="healChain"></div>
      </div>
      <div class="card">
        <h2>🔧 模型就绪状态</h2>
        <div id="modelReadiness"></div>
      </div>
      <div class="card">
        <h2>⚡ 性能基准 <span style="font-size:10px;color:var(--muted);">v2.9</span></h2>
        <div id="perfBench" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:12px;"></div>
      </div>
      <div class="card">
        <h2>🧠 记忆状态 <span style="font-size:10px;color:var(--muted);">v2.9</span></h2>
        <div id="memoryViz" style="font-size:12px;color:var(--muted);">加载中...</div>
      </div>
      <div class="card">
        <h2>📊 Agent 仪表 <span style="font-size:10px;color:var(--muted);">v2.12</span></h2>
        <div id="agentMonitorDash" style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:12px;"></div>
      </div>
      <div class="card">
        <h2>⚡ 快捷操作</h2>
        <div style="display:flex;flex-wrap:wrap;gap:6px;">
          <button class="action-btn start-btn" onclick="quickSearch()" style="font-size:11px;">🔍 网页搜索</button>
          <button class="action-btn" onclick="document.querySelector('.tab[data-pane=\"sandbox-dt\"]').click()" style="font-size:11px;background:#334155;color:#e2e8f0;">🖥️ 沙箱</button>
          <button class="action-btn" onclick="document.querySelector('.tab[data-pane=\"project-dt\"]').click();refreshProjectIndex()" style="font-size:11px;background:#334155;color:#e2e8f0;">📂 索引</button>
          <button class="action-btn" onclick="document.querySelector('.tab[data-pane=\"brain\"]').click()" style="font-size:11px;background:#334155;color:#e2e8f0;">🧠 脑图</button>
        </div>
      </div>
      <div class="card">
        <h2>📜 事件时间线</h2>
        <div class="timeline" id="eventTimeline"></div>
      </div>
    </div>
  </div>
  <div class="pane" id="pane-providers">
    <div class="pane-inner">
      <div class="card">
        <h2>🔑 API 供应商管理
          <span style="flex:1"></span>
          <button class="action-btn start-btn" onclick="exportConfig()" style="font-size:10px;margin-right:4px;">📥 导出</button>
          <button class="action-btn" onclick="document.getElementById('importFileInput').click()" style="font-size:10px;">📤 导入</button>
          <input type="file" id="importFileInput" accept=".json" onchange="importConfig(this)" style="display:none;">
        </h2>
        <div style="font-size:11px;color:var(--muted);margin-bottom:12px;">管理API密钥 · 测试连通性 · 一键切换 · 配置自动同步环境变量</div>
        <div id="providerList"></div>
      </div>
      <div class="card">
        <h2>📄 项目上下文 (.meshctx.md) <span style="font-size:10px;color:var(--muted);">v1.5.20 多项目</span></h2>
        <div style="margin-bottom:10px;">
          <select id="projectSelector" onchange="switchProject(this.value)" 
            style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:12px;width:100%;min-width:200px;">
            <option value="">(自动检测...</option>
          </select>
        </div>
        <div id="meshctxMdStatus" style="font-size:12px;"></div>
        <div id="meshctxMdPreview" style="font-size:11px;color:var(--muted);margin-top:8px;max-height:120px;overflow-y:auto;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:8px;display:none;"></div>
      </div>
      <div class="card">
        <h2>💬 会话历史</h2>
        <div style="margin-bottom:8px;">
          <input type="text" id="convSearch" placeholder="搜索会话标题..." oninput="searchConversations()" 
            style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:6px 10px;font-size:12px;width:100%;font-family:inherit;">
        </div>
        <div id="convHistoryList" style="max-height:300px;overflow-y:auto;font-size:12px;"></div>
      </div>
      <div class="card">
        <h2>📨 飞书通知 <span style="font-size:10px;color:var(--muted);">v2.8 新</span>
          <span style="flex:1"></span>
          <button class="action-btn start-btn" onclick="testFeishu()" style="font-size:10px;">🧪 测试</button>
          <button class="action-btn" onclick="saveFeishu()" style="font-size:10px;">💾 保存</button>
        </h2>
        <div style="font-size:11px;color:var(--muted);margin-bottom:12px;">配置飞书机器人Webhook，接收部署/健康/错误实时通知</div>
        <div class="form-group"><label>Webhook URL</label><input id="feishuUrl" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxx" style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:12px;"></div>
        <div class="form-group"><label>签名密钥 (可选)</label><input id="feishuSecret" type="password" placeholder="HMAC签名密钥" style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:12px;"></div>
        <div id="feishuStatus" style="font-size:11px;margin-top:6px;"></div>
      </div>
      <div class="card">
        <h2>📡 多通道通知 <span style="font-size:10px;color:var(--muted);">v2.14</span></h2>
        <div style="font-size:11px;color:var(--muted);margin-bottom:8px;">Telegram · Discord · Slack — 一键广播</div>
        <div class="form-group"><label>Telegram Bot Token</label><input id="tgToken" placeholder="123:abc..." style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:12px;"></div>
        <div class="form-group"><label>Telegram Chat ID</label><input id="tgChatId" placeholder="-100xxx" style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:12px;"></div>
        <div class="form-group"><label>Discord Webhook</label><input id="dcWebhook" placeholder="https://discord.com/api/webhooks/..." style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:12px;"></div>
        <div class="form-group"><label>Slack Webhook</label><input id="slWebhook" placeholder="https://hooks.slack.com/services/..." style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:12px;"></div>
        <button class="action-btn start-btn" onclick="saveMultiNotify()" style="font-size:10px;">💾 保存</button>
        <button class="action-btn" onclick="testMultiNotify()" style="font-size:10px;background:#334155;color:#e2e8f0;">🧪 测试广播</button>
        <div id="multiNotifyStatus" style="font-size:11px;margin-top:6px;"></div>
      </div>
      <div class="card">
        <h2>🔧 MCP 服务器管理
          <span style="flex:1"></span>
          <button class="action-btn start-btn" onclick="showAddMcpForm()" style="font-size:10px;">+ 添加</button>
        </h2>
        <div id="mcpServerList"></div>
      </div>
    </div>
  </div>
   <!-- v1.5.23 会话历史浏览器 -->
   <div class="pane" id="pane-history">
     <div class="pane-inner">
       <div class="card">
         <h2>📜 会话历史浏览器 <span style="font-size:10px;color:var(--muted);">v1.5.23</span></h2>
         <div style="display:flex;gap:8px;margin-bottom:12px;">
           <input id="historySearch" placeholder="搜索会话..." style="flex:1;background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:6px 12px;border-radius:6px;font-size:12px;" onkeyup="renderHistory()">
           <button class="action-btn" onclick="renderHistory()" style="font-size:11px;">🔍 搜索</button>
         </div>
         <div id="historySessions" style="display:flex;flex-direction:column;gap:6px;max-height:400px;overflow-y:auto;"></div>
       </div>
     </div>
   </div>
   
  <div class="pane" id="pane-lab">
    <div class="pane-inner">
      <div class="card">
        <h2>🔮 预测引擎
          <span style="flex:1"></span>
          <button class="action-btn start-btn" onclick="trainPredictor()" title="从最近事件中学习模式">🧠 训练</button>
        </h2>
        <div id="predictorPanel"></div>
      </div>
      <div class="card">
        <h2>🧠 元认知状态</h2>
        <div id="metaPanel"></div>
      </div>
      <div class="card">
        <h2>📈 系统能力基准
          <span style="flex:1"></span>
          <button class="action-btn start-btn" onclick="runBenchmark()" title="跑一次基准测试">⚡ 基准测试</button>
        </h2>
        <div id="benchPanel"></div>
      </div>
    </div>
  </div>
  <!-- 🧠 Brain Monitor v2.0 -->
  <div class="pane" id="pane-brain">
    <div class="pane-inner">
      <h2>🧠 Super Brain Monitor <span style="font-size:10px;color:var(--muted);">v2.0 实时</span></h2>
      <div id="brainMonitor" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:12px;"></div>
    </div>
  </div>
  <!-- 🔌 Plugins v2.3 -->
  <div class="pane" id="pane-plugins-dt">
    <div class="pane-inner">
      <h2>🔌 Plugin Marketplace <span style="font-size:10px;color:var(--muted);">v2.3</span></h2>
      <div id="pluginList" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;margin-top:12px;"></div>
    </div>
  </div>
  <!-- 🖥️ Sandbox v2.8 -->
  <div class="pane" id="pane-sandbox-dt">
    <div class="pane-inner">
      <h2>🖥️ Code Sandbox <span style="font-size:10px;color:var(--muted);">v2.8</span></h2>
      <p style="color:var(--muted);margin-bottom:12px;">安全执行 Python / Bash / JavaScript 代码</p>
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <select id="sandboxLang" style="background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;">
          <option value="python">Python</option>
          <option value="bash">Bash</option>
          <option value="javascript">JavaScript</option>
        </select>
        <input id="sandboxTimeout" type="number" value="30" min="1" max="120" style="width:60px;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px;border-radius:4px;" title="超时(秒)">
      </div>
      <textarea id="sandboxCode" style="width:100%;height:150px;background:var(--bg);color:var(--green);border:1px solid var(--border);padding:10px;border-radius:4px;font-family:monospace;font-size:13px;resize:vertical;" placeholder="print('Hello MeshCtx!')"></textarea>
      <div style="margin-top:8px;display:flex;gap:8px;">
        <button class="btn btn-primary" onclick="runSandbox()">▶ 执行</button>
        <button class="btn" style="background:#334155;color:#94a3b8;" onclick="document.getElementById('sandboxCode').value=''">清空</button>
      </div>
      <div id="sandboxResult" style="margin-top:12px;background:#0f172a;border:1px solid var(--border);border-radius:6px;padding:12px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:400px;overflow-y:auto;display:none;"></div>
    </div>
  </div>
  <!-- 📂 Project Index v2.8 -->
  <div class="pane" id="pane-project-dt">
    <div class="pane-inner">
      <h2>📂 Project Indexer <span style="font-size:10px;color:var(--muted);">v2.8</span></h2>
      <p style="color:var(--muted);margin-bottom:12px;">搜索当前项目代码，获取智能上下文</p>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <input id="projectQuery" style="flex:1;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:8px 12px;border-radius:4px;" placeholder="搜索函数/类/文件...">
        <button class="btn btn-primary" onclick="searchProject()">🔍 搜索</button>
        <button class="btn" style="background:#334155;color:#94a3b8;" onclick="refreshProjectIndex()">🔄 刷新索引</button>
      </div>
      <div id="projectStats" style="color:var(--muted);font-size:12px;margin-bottom:8px;"></div>
      <div id="projectResults" style="display:grid;gap:8px;"></div>
    </div>
  </div>
  <!-- 🪟 Windows Admin v2.10.1 -->
  <div class="pane" id="pane-win-dt">
    <div class="pane-inner">
      <h2>🪟 Windows 管理 <span style="font-size:10px;color:var(--muted);">v2.10.1</span></h2>
      <p style="color:var(--muted);margin-bottom:8px;">服务管理 · 进程监控 · PowerShell · 系统信息</p>
      
      <!-- Quick Buttons -->
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;">
        <button class="action-btn start-btn" onclick="winLoadServices()" style="font-size:11px;">🔧 服务</button>
        <button class="action-btn" onclick="winLoadProcesses()" style="font-size:11px;background:#334155;color:#e2e8f0;">📊 进程</button>
        <button class="action-btn" onclick="winLoadSystem()" style="font-size:11px;background:#334155;color:#e2e8f0;">💻 系统</button>
        <button class="action-btn" onclick="winLoadSoftware()" style="font-size:11px;background:#334155;color:#e2e8f0;">📦 软件</button>
      </div>
      
      <!-- PowerShell Console -->
      <div class="card" style="margin-bottom:8px;">
        <h3>💻 PowerShell</h3>
        <div style="display:flex;gap:6px;margin-bottom:6px;">
          <input id="winPsCmd" style="flex:1;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-family:monospace;font-size:12px;" placeholder="Get-Service | Where-Object {$_.Status -eq 'Running'}">
          <button class="btn btn-primary" onclick="winExec()">▶ 执行</button>
        </div>
        <div id="winPsResult" style="background:#0f172a;border:1px solid var(--border);border-radius:6px;padding:10px;font-family:monospace;font-size:11px;white-space:pre-wrap;max-height:300px;overflow-y:auto;display:none;"></div>
      </div>
      
      <!-- Dynamic Content -->
      <div id="winContent"></div>
    </div>
  </div>
</div>
<script>
// ═══ v2.9.0 Desktop Dashboard — 富数据+自动刷新 ═══
var REFRESH_SEC = 5, _timer = null, _data = null, _refreshPulse = false;
var _phaseMap = {O:'Observe',Or:'Orient',D:'Decide',A:'Act'};

// ═══ Performance Monitor v2.9 ═══
function renderPerf(){
  var el = document.getElementById('perfBench');
  if(!el) return;
  fetch('/api/project/index').then(function(r){return r.json()}).then(function(d){
    var items = [
      {label:'项目文件', value:d.total_files, unit:'个', color:'#38bdf8'},
      {label:'代码行数', value:(d.total_lines/1000).toFixed(1)+'K', unit:'行', color:'#22c55e'},
      {label:'语言', value:d.languages?Object.keys(d.languages).length:0, unit:'种', color:'#8b5cf6'},
      {label:'索引速度', value:(d.scan_duration_ms||0).toFixed(0), unit:'ms', color:'#f59e0b'},
    ];
    var html = '';
    items.forEach(function(it){
      html += '<div style=\"text-align:center;padding:8px;background:#0f172a;border-radius:6px;\">'+
        '<div style=\"font-size:20px;font-weight:700;color:'+it.color+';\">'+it.value+'</div>'+
        '<div style=\"font-size:10px;color:var(--muted);\">'+it.label+'</div>'+
        '</div>';
    });
    el.innerHTML = html;
  }).catch(function(e){
    el.innerHTML = '<span style=\"color:var(--muted);font-size:11px;\">索引未就绪</span>';
  });
}

// ═══ Quick Actions v2.9 ═══
function quickSearch(){
  var q = prompt('🔍 网页搜索:');
  if(!q) return;
  document.querySelector('.tab[data-pane="chat"]').click();
  var iframe = document.getElementById('chatFrame');
  if(iframe && iframe.contentWindow){
    iframe.contentWindow.postMessage({type:'meshctx-quick-ask', message:'/search '+q}, '*');
  }
}

// ═══ Windows Admin Panel v2.10.1 ═══
function winExec(){
  var cmd = document.getElementById('winPsCmd').value.trim();
  if(!cmd){alert('请输入PowerShell命令');return;}
  var el = document.getElementById('winPsResult');
  el.style.display = 'block';
  el.style.color = '#94a3b8';
  el.textContent = '⏳ 执行中...';
  fetch('/api/win/execute', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({command:cmd, timeout:30})
  }).then(function(r){return r.json()}).then(function(d){
    var out = (d.stdout||'') + '\n' + (d.stderr?'[STDERR] '+d.stderr+'\n':'');
    out += '[Exit: '+d.exit_code+' | '+d.duration_ms+'ms]';
    el.textContent = out;
    el.style.color = d.success ? '#22c55e' : '#fca5a5';
  }).catch(function(e){
    el.textContent = '失败: '+e.message;
    el.style.color = '#fca5a5';
  });
}
function winLoadServices(){
  var el = document.getElementById('winContent');
  el.innerHTML = '<span style="color:var(--muted);">⏳ 加载服务列表...</span>';
  fetch('/api/win/services').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>🔧 Windows 服务</h3><div style="max-height:400px;overflow-y:auto;">';
    (d.services||[]).forEach(function(s){
      var color = s.status==='Running'?'#22c55e':s.status==='Stopped'?'#fca5a5':'#f59e0b';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px;">'+
        '<span><span style="color:'+color+';font-weight:600;">'+s.status+'</span> '+s.name+'</span>'+
        '<span style="color:var(--muted);">'+s.display_name+'</span></div>';
    });
    html += '</div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML='<span style="color:#fca5a5;">加载失败: '+e.message+'</span>';});
}
function winLoadProcesses(){
  var el = document.getElementById('winContent');
  el.innerHTML = '<span style="color:var(--muted);">⏳ 加载进程列表...</span>';
  fetch('/api/win/processes').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>📊 进程 Top 30</h3><div style="max-height:400px;overflow-y:auto;">';
    html += '<table style="width:100%;font-size:11px;border-collapse:collapse;"><tr style="color:var(--muted);"><th style="text-align:left;">PID</th><th style="text-align:left;">名称</th><th>CPU</th><th>内存</th></tr>';
    (d.processes||[]).forEach(function(p){
      html += '<tr style="border-bottom:1px solid var(--border);">'+
        '<td>'+p.pid+'</td><td>'+p.name+'</td>'+
        '<td style="text-align:right;">'+p.cpu+'</td>'+
        '<td style="text-align:right;">'+p.memory_mb+'MB</td></tr>';
    });
    html += '</table></div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML='<span style="color:#fca5a5;">加载失败: '+e.message+'</span>';});
}
function winLoadSystem(){
  var el = document.getElementById('winContent');
  fetch('/api/win/system').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>💻 系统信息</h3>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;">';
    for(var k in d){
      html += '<div style="color:var(--muted);">'+k+'</div><div style="font-weight:600;">'+d[k]+'</div>';
    }
    html += '</div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML='<span style="color:#fca5a5;">加载失败: '+e.message+'</span>';});
}
function winLoadSoftware(){
  var el = document.getElementById('winContent');
  el.innerHTML = '<span style="color:var(--muted);">⏳ 扫描已安装软件...</span>';
  fetch('/api/win/software').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>📦 已安装软件</h3><div style="max-height:400px;overflow-y:auto;">';
    (d.software||[]).slice(0,30).forEach(function(s){
      html += '<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border);">'+
        '<span style="font-weight:600;">'+s.name+'</span>'+
        (s.version?' <span style="color:var(--muted);">v'+s.version+'</span>':'')+
        (s.publisher?' <span style="color:var(--muted);font-size:10px;">- '+s.publisher+'</span>':'')+
        '</div>';
    });
    html += '</div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML='<span style="color:#fca5a5;">加载失败: '+e.message+'</span>';});
}

// ═══ Agent Monitor v2.12.5 ═══
function renderAgentMonitor(){
  var el = document.getElementById('agentMonitorDash');
  if(!el) return;
  fetch('/api/agent/monitor').then(function(r){return r.json()}).then(function(d){
    var items = [
      {label:'消息', value:d.chat?.messages||0, color:'#38bdf8'},
      {label:'Token', value:(d.chat?.tokens||0), color:'#22c55e'},
      {label:'沙箱', value:d.tools?.sandbox||0, color:'#8b5cf6'},
      {label:'搜索', value:d.tools?.search||0, color:'#f59e0b'},
      {label:'Win', value:d.tools?.windows||0, color:'#06b6d4'},
      {label:'文件', value:d.tools?.file_reads||0, color:'#ec4899'},
    ];
    var html = '';
    items.forEach(function(it){
      html += '<div style="text-align:center;padding:6px;background:#0f172a;border-radius:6px;">'+
        '<div style="font-size:18px;font-weight:700;color:'+it.color+';">'+it.value+'</div>'+
        '<div style="font-size:9px;color:var(--muted);">'+it.label+'</div></div>';
    });
    el.innerHTML = html;
  }).catch(function(e){
    el.innerHTML = '<span style="color:var(--muted);font-size:11px;">监控未就绪</span>';
  });
}

// ═══ Memory Visualization v2.9 ═══
function renderMemory(){
  var el = document.getElementById('memoryViz');
  if(!el) return;
  fetch('/api/system/summary').then(function(r){return r.json()}).then(function(d){
    var mem = d.memory || {};
    var items = [
      {label:'工作记忆(L0)', value:mem.l0_count||0, color:'#38bdf8', max:100},
      {label:'短期记忆(L1)', value:mem.l1_count||0, color:'#22c55e', max:500},
      {label:'长期记忆(L2)', value:mem.l2_count||0, color:'#8b5cf6', max:2000},
      {label:'归档记忆(L3)', value:mem.l3_count||0, color:'#f59e0b', max:10000},
    ];
    var html = '';
    items.forEach(function(it){
      var pct = Math.min(100, (it.value/it.max)*100);
      html += '<div style="margin-bottom:8px;">'+
        '<div style="display:flex;justify-content:space-between;margin-bottom:2px;">'+
        '<span>'+it.label+'</span><span style="color:'+it.color+';">'+it.value+'</span></div>'+
        '<div style="background:#1e293b;border-radius:4px;height:6px;overflow:hidden;">'+
        '<div style="background:'+it.color+';width:'+pct+'%;height:100%;border-radius:4px;transition:width 0.5s;"></div></div></div>';
    });
    el.innerHTML = html || '<span style="color:var(--muted);">记忆数据获取中...</span>';
  }).catch(function(e){
    el.innerHTML = '<span style="color:var(--muted);">记忆系统未就绪</span>';
  });
}

// Tab切换
document.querySelectorAll('.tabbar .tab').forEach(function(t){
  t.onclick = function(){
    try {
      document.querySelectorAll('.tabbar .tab').forEach(function(x){x.classList.remove('active')});
      document.querySelectorAll('.content .pane').forEach(function(x){x.classList.remove('active')});
      t.classList.add('active');
      var p = document.getElementById('pane-'+t.dataset.pane);
      if(p){ p.classList.add('active'); }
      // 如果还没加载数据，先获取
      if(!_data) { fetchSummary(); return; }
      renderAll(_data);
    } catch(e) {
      console.error('Tab switch error:', e);
      // 降级：至少切换面板
    }
  };
});

// 自动刷新
function startAutoRefresh(){
  fetchSummary();
  _timer = setInterval(fetchSummary, REFRESH_SEC*1000);
  // v2.15.3: WebSocket实时推送
  connectWebSocket();
}

function connectWebSocket(){
  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var wsUrl = proto + '//' + location.host + '/ws/metrics';
  try {
    var ws = new WebSocket(wsUrl);
    ws.onmessage = function(e){
      try {
        var d = JSON.parse(e.data);
        if(d.type === 'agent_metrics') updateLiveMetrics(d);
      } catch(ex) {}
    };
    ws.onclose = function(){ setTimeout(connectWebSocket, 5000); };
    ws.onerror = function(){ /* fallback to polling */ };
  } catch(ex) { /* WebSocket not supported */ }
}

function updateLiveMetrics(d){
  var el = document.getElementById('liveTag');
  if(el){
    var phase = _phaseMap[d.phase] || 'RUN';
    el.textContent = '● LIVE ' + phase + ' | ' + (d.chat?.messages||0) + 'msgs';
  }
  // Update agent monitor card if visible
  var dash = document.getElementById('agentMonitorDash');
  if(dash && dash.children.length > 0){
    setTimeout(function(){ renderAgentMonitor(); }, 500);
  }
  // Check for updates periodically
  if(!window._updateChecked){
    window._updateChecked = true;
    fetch('/api/update/check').then(function(r){return r.json()}).then(function(ud){
      if(ud.update_available){
        var bar = document.getElementById('updateBar');
        if(bar) bar.style.display = 'block';
      }
    });
  }
}
function fetchSummary(){
  // v1.5.15: 标题闪烁
  var origTitle = document.title;
  document.title = '● meshctx Desktop';
  setTimeout(function(){ document.title = origTitle; }, 600);
  // v1.5.11: 刷新脉冲动画
  if(_refreshPulse){
    document.getElementById('liveTag').style.transform = 'scale(1.2)';
    setTimeout(function(){ document.getElementById('liveTag').style.transform = ''; }, 200);
  }
  _refreshPulse = true;
  fetch('/api/system/summary').then(function(r){return r.json()}).then(function(d){
    _data = d;
    renderAll(d);
    updateLiveTag();
  }).catch(function(e){
    console.error('Summary fetch error:', e);
    document.getElementById('liveTag').textContent = '⚠ 离线';
    document.getElementById('sysDot').style.background = 'var(--danger)';
  });
}
function updateLiveTag(){
  var el = document.getElementById('liveTag');
  var t = new Date().toTimeString().slice(0,8);
  el.textContent = '● LIVE '+t;
  el.style.color = 'var(--accent2)';
  document.getElementById('sysDot').style.background = 'var(--accent2)';
}

// ═══ 模型切换 ═══
function loadModels(){
  fetch('/api/models').then(function(r){return r.json()}).then(function(d){
    var sel = document.getElementById('quickModel');
    sel.innerHTML = '';
    (d.models||[]).forEach(function(m){
      var opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = (m.default?'⭐ ':'') + m.id;
      if(m.default) opt.selected = true;
      sel.appendChild(opt);
    });
  }).catch(function(e){console.error(e);});
}
function switchQuickModel(){
  var id = document.getElementById('quickModel').value;
  if(!id) return;
  localStorage.setItem('meshctx_desktop_model', id);
}
loadModels();

// ═══ 全量渲染 ═══
function renderAll(d){
  renderAgent(d);
  renderMonitor(d);
  renderProviders();
  renderLab(d);
  renderBrain();  // v2.0 Brain Monitor
  renderPlugins(); // v2.3 Plugin Market
  renderPerf();    // v2.9 Perf Bench
  renderMemory();  // v2.9 Memory Viz
  renderAgentMonitor(); // v2.12.5 Agent Monitor
  loadMeshctxMd();
  loadConversations();
}
function colorByStatus(s){
  if(s==='healthy'||s==='active'||s==='running') return 'v-green';
  if(s==='degraded'||s==='warning') return 'v-warn';
  if(s==='critical'||s==='error'||s==='failed') return 'v-red';
  return '';
}
function tagByStatus(s){
  if(s==='healthy'||s==='ready'||s==='active') return 'tag-ok';
  if(s==='degraded'||s==='warning'||s==='unstable') return 'tag-warn';
  if(s==='critical'||s==='error') return 'tag-err';
  return 'tag-info';
}

// ── Agent Tab ──
function renderAgent(d){
  var ag = d.agents||{}, oo = ag.ooda||{}, tasks = ag.recent_tasks||[];
  document.getElementById('agentStats').innerHTML =
    '<div class="stat-card"><div class="value '+colorByStatus(oo.status)+'">'+ (ag.active||0) +'</div><div class="label">活跃任务</div></div>'+
    '<div class="stat-card"><div class="value">'+ (ag.total||0) +'</div><div class="label">已完成</div></div>'+
    '<div class="stat-card"><div class="value '+((ag.success_rate||0)>=0.8?'v-green':(ag.success_rate||0)>=0.5?'v-warn':'v-red')+'">'+ ((ag.success_rate||0)*100).toFixed(0) +'%</div><div class="label">成功率</div></div>'+
    '<div class="stat-card"><div class="value">'+ (oo.cycle_count||0) +'</div><div class="label">OODA循环</div></div>';

  // OODA可视化
  var phases = ['O','Or','D','A'];
  var curPhase = oo.phase||'idle';
  var oodaHTML = '';
  for(var i=0; i<phases.length; i++){
    var p=phases[i], isActive = (p===curPhase || (curPhase==='idle' && p==='O'));
    oodaHTML += '<div class="ooda-step '+p+(isActive?' active':'')+'"'+(isActive?' style="animation:phasePulse 2s ease-in-out infinite;"':'')+'><div class="letter">'+(p.length===1?p:'Oo')+'</div><div class="name">'+_phaseMap[p]+'</div></div>';
    if(i<3) oodaHTML += '<div class="ooda-arrow">→</div>';
  }
  document.getElementById('oodaBox').innerHTML = oodaHTML;
  document.getElementById('oodaRefreshTag').textContent = '循环#'+(oo.cycle_count||0)+' · '+curPhase;
  // 按钮状态
  var btnStart = document.getElementById('btnAgentStart');
  var btnStop = document.getElementById('btnAgentStop');
  var isRunning = (oo.status==='active' || oo.status==='running');
  if(btnStart && btnStop){
    btnStart.style.display = isRunning ? 'none' : '';
    btnStop.style.display = isRunning ? '' : 'none';
  }

  // 任务列表
  var taskHTML = '';
  if(tasks.length>0){
    for(var i=0; i<Math.min(tasks.length,8); i++){
      var tk = tasks[i];
      taskHTML += '<div class="row"><span style="color:var(--muted);font-family:monospace;font-size:10px;">'+tk.id+'</span><span style="flex:1">'+(tk.description||tk.id||'')+'</span><span class="tag '+tagByStatus(tk.status)+'">'+(tk.status||'pending')+'</span></div>';
    }
  } else {
    taskHTML = '<div class="empty">😴 暂无任务记录</div>';
  }
  document.getElementById('agentTaskList').innerHTML = taskHTML;
}

// ── Monitor Tab ──
function renderMonitor(d){
  var h = d.health||{}, plugins = h.plugins||{}, events = h.recent_events||[];
  var perf = d.performance||{}, models = d.models||{}, kernel = d.kernel||{};

  // 状态层级: healthy/degraded/unstable/critical
  var statusCount = {healthy:0,degraded:0,unstable:0,critical:0,unknown:0};
  Object.values(plugins).forEach(function(p){ statusCount[p.status||'unknown'] = (statusCount[p.status||'unknown']||0)+1; });

  var hs = d.health_score || 100;
  var hsColor = hs >= 80 ? 'var(--accent2)' : hs >= 50 ? '#ffa940' : 'var(--danger)';
  document.getElementById('monitorStats').innerHTML =
    '<div class="stat-card" style="grid-column:1/-1;background:linear-gradient(90deg,'+hsColor+'22,'+hsColor+'05);border:1px solid '+hsColor+'44;">'+
      '<div class="value" style="color:'+hsColor+';font-size:28px;">'+hs+'</div>'+
      '<div class="label">🩺 系统健康评分</div>'+
      '<div style="font-size:9px;color:var(--muted);">'+ (hs>=80?'优秀':hs>=50?'一般':'需关注') +'</div>'+
    '</div>'+
    '<div class="stat-card"><div class="value '+colorByStatus(h.overall)+'">'+ (statusCount.healthy||0) +'/'+Object.keys(plugins).length+'</div><div class="label">插件健康</div></div>'+
    '<div class="stat-card"><div class="value">'+ (models.ready||0) +'/'+(models.total||0)+'</div><div class="label">模型就绪</div></div>'+
    '<div class="stat-card"><div class="value">'+ (perf.total_requests||0) +'</div><div class="label">总请求</div></div>'+
    '<div class="stat-card"><div class="value">'+ ((perf.avg_latency_ms||0).toFixed(0)) +'ms</div><div class="label">平均延迟</div></div>';

  // v1.5.6: 系统资源
  var res = d.resources || {};
  if(res.cpu !== undefined){
    var cpuC = res.cpu > 80 ? 'var(--danger)' : res.cpu > 60 ? '#ffa940' : 'var(--accent2)';
    var memC = res.memory_percent > 80 ? 'var(--danger)' : res.memory_percent > 60 ? '#ffa940' : 'var(--accent2)';
    var resHtml = '<div style="flex:1;min-width:120px;text-align:center;background:var(--bg);border-radius:8px;padding:8px">';
    resHtml += '<div style="font-size:22px;font-weight:700;color:'+cpuC+';">'+res.cpu+'%</div>';
    resHtml += '<div style="font-size:10px;color:var(--muted);">CPU</div></div>';
    resHtml += '<div style="flex:1;min-width:120px;text-align:center;background:var(--bg);border-radius:8px;padding:8px">';
    resHtml += '<div style="font-size:22px;font-weight:700;color:'+memC+';">'+res.memory_percent+'%</div>';
    resHtml += '<div style="font-size:10px;color:var(--muted);">内存 '+res.memory_used_gb+'/'+res.memory_total_gb+' GB</div></div>';
    document.getElementById('sysResources').innerHTML = resHtml;
  }

  // 插件健康卡片
  var pHtml = '';
  var pNames = Object.keys(plugins);
  if(pNames.length>0){
    for(var i=0; i<pNames.length; i++){
      var pn = pNames[i], p = plugins[pn];
      pHtml += '<div class="plugin-card"><div class="row"><span class="dot '+colorByStatus(p.status).replace('v-','')+'"></span><span class="pname">'+pn+'</span></div>'+
        '<div class="pmeta">状态: <span class="tag '+tagByStatus(p.status)+'">'+p.status+'</span> · 失败: '+(p.failures||0)+' · 重启: '+(p.restarts||0)+'</div>'+
        '<div class="pmeta">心跳: '+((p.heartbeat_age||0)>10?'⚠ '+p.heartbeat_age+'s':'✓ '+p.heartbeat_age+'s')+' · 熔断: '+p.circuit+'</div></div>';
    }
  } else {
    pHtml = '<div class="empty">🔌 暂无插件数据</div>';
  }
  document.getElementById('pluginHealth').innerHTML = pHtml;
  
  // v1.5.4: 自愈链路
  var healPlugins = h.plugins || {};
  var chainNames = ['healer','predictor','metacognition','gateway','websocket'];
  var chainHtml = '';
  for(var i=0;i<chainNames.length;i++){
    var cn = chainNames[i];
    var hp = healPlugins[cn] || {};
    var ok = hp.status==='healthy';
    chainHtml += '<span class=heal-node'+(ok?' ok':' warn')+'>';
    chainHtml += '<span class=heal-dot></span>'+cn;
    if(!ok) chainHtml += ' ⚠';
    if(i<chainNames.length-1) chainHtml += ' →';
    chainHtml += '</span>';
  }
  document.getElementById('healChain').innerHTML = chainHtml;

  // 模型就绪状态 (紧凑表)
  var mHtml = '';
  var mList = models.list||[];
  if(mList.length>0){
    var cols = 3;
    for(var i=0; i<Math.min(mList.length,12); i++){
      var m = mList[i];
      if(i%cols===0) mHtml += '<div class="row">';
      mHtml += '<span class="dot '+(m.ready?'on':'off')+'"></span><span style="font-size:11px;margin-right:12px;">'+m.id+'</span><span class="meta">'+m.provider+'</span>';
      if(i%cols===cols-1 || i===mList.length-1) mHtml += '</div>';
    }
  } else {
    mHtml = '<div class="empty">🤖 暂无已配置模型</div>';
  }
  document.getElementById('modelReadiness').innerHTML = mHtml;

  // 事件时间线
  var eHtml = '';
  if(events.length>0){
    for(var i=0; i<Math.min(events.length,15); i++){
      var ev = events[i];
      var t = new Date(ev.time*1000).toTimeString().slice(0,8);
      var et = ev.type || 'info';
      var etColor = et==='error'?'#f87171':et==='warning'?'#fbbf24':'#60a5fa';
      eHtml += '<div class="tl-item"><span class="tl-time">'+t+'</span><span class="tl-type" style="background:'+etColor+'22;color:'+etColor+';padding:1px 6px;border-radius:8px;font-size:9px;font-weight:600;">'+et+'</span><span class="tl-detail">'+ev.detail+'</span></div>';
    }
  } else {
    eHtml = '<div class="empty">📭 暂无事件记录</div>';
  }
  document.getElementById('eventTimeline').innerHTML = eHtml;

  // v1.5.2: 绘制请求趋势图
  var metrics = d.metrics_history || {};
  var reqs = metrics.requests || [];
  var lats = metrics.latency || [];
  if (reqs.length > 0) {
    var maxReq = Math.max.apply(null, reqs) || 1;
    var chartHTML = '<div style="display:flex;align-items:flex-end;gap:3px;height:60px;padding:4px 0;">';
    var showN = Math.min(reqs.length, 30);
    var start = reqs.length - showN;
    for (var ri = start; ri < reqs.length; ri++) {
      var h = Math.max(4, (reqs[ri]/maxReq)*56);
      var c = lats[ri] > 200 ? 'var(--danger)' : lats[ri] > 100 ? 'var(--warn)' : 'var(--accent2)';
      chartHTML += '<div style="width:8px;height:'+h+'px;background:'+c+';border-radius:2px;flex-shrink:0;" title="'+reqs[ri]+' req, '+lats[ri]+'ms"></div>';
    }
    chartHTML += '</div><div style="font-size:10px;color:var(--muted);display:flex;justify-content:space-between;"><span>'+reqs.length+'数据点</span><span>max '+maxReq+' req</span></div>';
    document.getElementById('eventTimeline').insertAdjacentHTML('beforebegin', '<div class="card"><h2>📈 请求趋势 (30点)</h2>'+chartHTML+'</div>');
  }
}

// ── Lab Tab ──
function renderLab(d){
  var pred = d.predictor||{}, ag = d.agents||{};

  // 预测面板
  var predHTML = '<div class="stats-grid" style="margin-bottom:10px">'+
    '<div class="stat-card"><div class="value">'+ (pred.patterns_learned||0) +'</div><div class="label">学习模式</div></div>'+
    '<div class="stat-card"><div class="value">'+ (ag.total||0) +'</div><div class="label">任务积累</div></div>'+
    '<div class="stat-card"><div class="value '+( (ag.success_rate||0)>=0.8?'v-green':(ag.success_rate||0)>=0.5?'v-warn':'v-red') +'">'+ ((ag.success_rate||0)*100).toFixed(0) +'%</div><div class="label">智能成功率</div></div>'+
    '</div>';

  var topPreds = pred.top_predictions||[];
  if(topPreds.length>0){
    predHTML += '<div style="font-size:11px;color:var(--muted);margin-bottom:6px;">📊 最新预测:</div>';
    for(var i=0; i<topPreds.length; i++){
      var pp = topPreds[i];
      var conf = parseFloat(pp.confidence)||0;
      var barColor = conf>=0.7?'var(--accent2)':conf>=0.4?'var(--warn)':'var(--danger)';
      predHTML += '<div class="row"><span style="flex:1">'+pp.task+'</span><span class="meta">'+pp.confidence+'</span>'+
        '<div class="progress-bar" style="width:80px;"><div class="progress-fill" style="width:'+(conf*100)+'%;background:'+barColor+'"></div></div></div>';
    }
  }
  if(pred.last_trained){
    predHTML += '<div style="font-size:10px;color:var(--muted);margin-top:4px;">🕐 最后训练: '+new Date(pred.last_trained*1000).toLocaleString()+'</div>';
  }
  document.getElementById('predictorPanel').innerHTML = predHTML;

  // 元认知面板 — 从summary数据派生
  var metaHTML = '<div class="row"><span style="flex:1">🧠 自省循环</span><span class="tag tag-ok">活跃</span></div>'+
    '<div class="row"><span style="flex:1">🔄 OODA状态</span><span>'+ ((ag.ooda||{}).status||'unknown') +' · 相位: '+((ag.ooda||{}).phase||'idle')+'</span></div>'+
    '<div class="row"><span style="flex:1">📊 任务成功率</span><span>'+ ((ag.success_rate||0)*100).toFixed(0) +'%</span></div>'+
    '<div class="row"><span style="flex:1">🎯 模型丰富度</span><span>'+ ((d.models||{}).total||0) +' 模型 · '+( (d.models||{}).ready||0) +' 就绪</span></div>';
  document.getElementById('metaPanel').innerHTML = metaHTML;

  // 基准面板
  var benchHTML = '<div class="row"><span style="flex:1">🎯 模型支持</span><span>'+ ((d.models||{}).total||0) +'+ 模型</span></div>'+
    '<div class="row"><span style="flex:1">🧩 插件系统</span><span>'+ ((d.kernel||{}).plugins||[]).length +' 插件</span></div>'+
    '<div class="row"><span style="flex:1">⚡ 连接池复用</span><span class="tag tag-ok">启用</span></div>'+
    '<div class="row"><span style="flex:1">🛡️ 自愈引擎</span><span class="tag tag-ok">'+ ((d.health||{}).overall||'enabled') +'</span></div>'+
    '<div class="row"><span style="flex:1">🔄 故障转移</span><span class="tag tag-ok">自动</span></div>'+
    '<div class="row"><span style="flex:1">📦 版本</span><span>v2.6 · 673测试 · '+ (d.uptime||0) +'s 运行</span></div>';
  document.getElementById('benchPanel').innerHTML = benchHTML;
}

// ═══ Brain Monitor v2.1: 实时API ═══
function renderBrain(){
  fetch('/api/brain/status').then(function(r){return r.json()}).then(function(d){
    var html = '';
    var regions = d.regions || [];
    for(var i=0; i<regions.length; i++){
      var r = regions[i];
      var act = r.activation || 0.5;
      html += '<div class="stat-card" style="border-left:3px solid '+r.color+';">'+
        '<div style="font-size:20px;">'+r.icon+'</div>'+
        '<div style="font-size:13px;font-weight:600;">'+r.name+'</div>'+
        '<div style="font-size:10px;color:var(--muted);">激活: '+(act*100).toFixed(0)+'%</div>'+
        '<div class="progress-bar" style="margin-top:6px;">'+
          '<div class="progress-fill" style="width:'+(act*100)+'%;background:'+r.color+';"></div>'+
        '</div></div>';
    }
    html += '<div class="stat-card" style="border-left:3px solid #a78bfa;grid-column:1/-1;">'+
      '<div style="display:flex;justify-content:space-between;align-items:center;">'+
      '<span>🧿 Φ (IIT意识度量)</span>'+
      '<span style="font-size:24px;font-weight:700;color:#a78bfa;">'+(d.phi||0).toFixed(2)+'</span></div>'+
      '<div style="font-size:10px;color:var(--muted);">状态: '+(d.state||'unknown')+' · 9脑区</div></div>';
    document.getElementById('brainMonitor').innerHTML = html;
  }).catch(function(e){
    document.getElementById('brainMonitor').innerHTML = '<div class="stat-card" style="grid-column:1/-1;text-align:center;color:var(--muted);">🧠 等待后端连接...</div>';
  });
}

// ═══ Plugin Marketplace v2.3 ═══
function renderPlugins(){
  fetch('/api/plugins').then(function(r){return r.json()}).then(function(d){
    var plugins = d.plugins || [];
    var html = '';
    for(var i=0; i<plugins.length; i++){
      var p = plugins[i];
      var badge = p.builtin ? '<span style="background:#8b5cf6;color:#fff;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:4px;">内置</span>' : '';
      var installBtn = p.builtin 
        ? (p.installs > 0 ? '<span style="font-size:10px;color:#22c55e;">✅ 已激活</span>' : '<button class="action-btn start-btn" style="font-size:10px;" onclick="installPlugin(\''+p.name+'\')">⚡ 激活</button>')
        : '<button class="action-btn start-btn" style="font-size:10px;" onclick="installPlugin(\''+p.name+'\')">📥 安装</button>';
      html += '<div class="stat-card" style="border-left:3px solid '+(p.builtin?'#8b5cf6':'#06b6d4')+';">'+
        '<div style="display:flex;justify-content:space-between;align-items:start;">'+
        '<div><span style="font-size:20px;">'+p.icon+'</span> <strong>'+p.name+'</strong>'+badge+'</div>'+
        '<span style="font-size:10px;color:var(--muted);">v'+p.version+'</span></div>'+
        '<p style="font-size:11px;color:var(--muted);margin:4px 0;">'+p.description+'</p>'+
        '<div style="display:flex;gap:4px;margin-top:6px;">'+
        installBtn+
        '<button class="action-btn stop-btn" style="font-size:10px;" onclick="uninstallPlugin(\''+p.name+'\')">🗑</button>'+
        '<span style="font-size:9px;color:var(--muted);align-self:center;">'+p.installs+' installs</span></div></div>';
    }
    document.getElementById('pluginList').innerHTML = html || '<div class="stat-card" style="grid-column:1/-1;text-align:center;color:var(--muted);">暂无插件</div>';
  });
}
function installPlugin(name){
  fetch('/api/plugins/install/'+name, {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    alert(d.status==='ok'?'✅ '+name+' 安装成功!':d.message||'失败');
    renderPlugins();
  });
}
function uninstallPlugin(name){
  if(!confirm('卸载 '+name+'?')) return;
  fetch('/api/plugins/uninstall/'+name, {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    alert(d.status==='ok'?'🗑 '+name+' 已卸载':d.message);
    renderPlugins();
  });
}

// ═══ Agent控制 ═══
function controlAgent(action){
  var btnStart = document.getElementById('btnAgentStart');
  var btnStop = document.getElementById('btnAgentStop');
  if(action==='start'){
    btnStart.textContent = '⏳ 启动中...'; btnStart.disabled = true;
    fetch('/agent/start', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
      btnStart.style.display = 'none'; btnStop.style.display = '';
      btnStart.textContent = '▶ 启动'; btnStart.disabled = false;
      fetchSummary();
    }).catch(function(e){
      btnStart.textContent = '▶ 启动'; btnStart.disabled = false;
      console.error(e);
    });
  } else if(action==='stop'){
    btnStop.textContent = '⏳ 停止中...'; btnStop.disabled = true;
    fetch('/agent/stop', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
      btnStop.style.display = 'none'; btnStart.style.display = '';
      btnStop.textContent = '⏹ 停止'; btnStop.disabled = false;
      fetchSummary();
    }).catch(function(e){
      btnStop.textContent = '⏹ 停止'; btnStop.disabled = false;
      console.error(e);
    });
  }
}

// ═══ 预测器训练 ═══
function trainPredictor(){
  var btn = event.target;
  btn.textContent = '⏳ 训练中...'; btn.disabled = true;
  fetch('/predictor/learn', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    btn.textContent = '✅ 完成';
    setTimeout(function(){ btn.textContent = '🧠 训练'; btn.disabled = false; fetchSummary(); }, 1500);
  }).catch(function(e){
    btn.textContent = '❌ 失败';
    setTimeout(function(){ btn.textContent = '🧠 训练'; btn.disabled = false; }, 2000);
    console.error(e);
  });
}

// ═══ 快速提问 v1.5.9 ═══
function quickAsk(e){
  e.preventDefault();
  var inp = document.getElementById('quickInput');
  var msg = inp.value.trim();
  if(!msg) return;
  // 切换到Chat tab
  document.querySelectorAll('.tabbar .tab').forEach(function(t){t.classList.remove('active')});
  document.querySelectorAll('.content .pane').forEach(function(p){p.classList.remove('active')});
  var chatTab = document.querySelector('.tab[data-pane="chat"]');
  var chatPane = document.getElementById('pane-chat');
  if(chatTab) chatTab.classList.add('active');
  if(chatPane) chatPane.classList.add('active');
  // 通过postMessage发送给chat iframe
  var iframe = document.getElementById('chatFrame');
  if(iframe && iframe.contentWindow){
    iframe.contentWindow.postMessage({type:'meshctx-quick-ask', message:msg}, '*');
  }
  inp.value = '';
}

// ═══ 主题切换 v1.8.2: 自动跟随系统 ═══
(function(){
  var saved = localStorage.getItem('meshctx_theme');
  if(!saved){
    // 自动检测系统主题偏好
    var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    saved = prefersDark ? 'dark' : 'light';
    localStorage.setItem('meshctx_theme', saved);
  }
  if(saved==='light') document.body.classList.add('light');
  if(saved==='light') document.getElementById('themeBtn').textContent = '☀️';
  // 监听系统主题变化
  if(window.matchMedia){
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e){
      var current = localStorage.getItem('meshctx_theme');
      if(!current || current === 'auto'){
        if(e.matches) document.body.classList.remove('light');
        else document.body.classList.add('light');
      }
    });
  }
})();
function toggleTheme(){
  var body = document.body;
  var btn = document.getElementById('themeBtn');
  body.classList.toggle('light');
  var isLight = body.classList.contains('light');
  localStorage.setItem('meshctx_theme', isLight ? 'light' : 'dark');
  btn.textContent = isLight ? '☀️' : '🌓';
}

// ═══ 基准测试 v1.5.6 ═══
function runBenchmark(){
  var btn = event.target;
  var panel = document.getElementById('benchPanel');
  btn.textContent = '⏳ 测试中...'; btn.disabled = true;
  panel.innerHTML = '<div class=stat><span>⏳</span><span>正在运行基准测试...</span></div>';
  fetch('/api/benchmark/run', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.status==='ok'){
      panel.innerHTML = [
        '<div class=stat><span>'+d.latency_ms+'ms</span><span>延迟 (TTFB)</span></div>',
        '<div class=stat><span>'+d.tokens_per_sec+' tok/s</span><span>推理速度</span></div>',
        '<div class=stat><span>'+d.output_tokens+'</span><span>输出tokens</span></div>',
        '<div class=stat><span>'+d.input_tokens+'</span><span>输入tokens</span></div>',
        '<div style="font-size:10px;color:var(--muted);margin-top:6px;"><b>模型:</b> '+d.model+'<br><b>回复:</b> '+d.response_preview+'</div>'
      ].join('');
    }else{
      panel.innerHTML = '<div class=stat><span>❌</span><span>'+d.error+'</span></div>';
    }
    btn.textContent = '⚡ 基准测试'; btn.disabled = false;
  }).catch(function(e){
    panel.innerHTML = '<div class=stat><span>❌</span><span>请求失败</span></div>';
    btn.textContent = '⚡ 基准测试'; btn.disabled = false;
  });
}

// ═══ 模型切换器 v1.5.5 ═══
function fetchModels(){
  fetch('/api/models').then(function(r){return r.json()}).then(function(d){
    var sel = document.getElementById('quickModel');
    sel.innerHTML = '';
    var models = d.models || [];
    for(var i=0;i<models.length;i++){
      var m = models[i];
      var opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = (m.current?'● ':'') + m.provider_name + ' / ' + m.model_name + (m.usable?' ✓':(m.has_key?' ⚠':' 🔒'));
      if(m.current) opt.selected = true;
      if(!m.usable) { opt.disabled = true; opt.style.color = '#64748b'; }
      sel.appendChild(opt);
    }
    sel.title = d.total + ' 模型 · ' + d.configured + ' 已配置';
  }).catch(function(e){ console.error('加载模型列表失败:', e); });
}
function switchQuickModel(){
  var modelId = document.getElementById('quickModel').value;
  if(!modelId) return;
  fetch('/api/model/switch', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({model_id:modelId})
  }).then(function(r){return r.json()}).then(function(d){
    var live = document.getElementById('liveTag');
    live.textContent = '✅ 已切换: ' + d.current;
    setTimeout(function(){ live.textContent = 'LIVE'; }, 3000);
    fetchModels(); // 刷新选中状态
  }).catch(function(e){
    alert('切换失败: ' + e);
  });
}

// ═══ v1.5.16 供应商管理 ═══
function renderProviders(){
  fetch('/api/providers').then(function(r){return r.json()}).then(function(d){
    var list = d.providers || [];
    var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:8px;">';
    for(var i=0;i<list.length;i++){
      var p = list[i];
      var dotColor = p.has_key ? 'var(--accent2)' : 'var(--border)';
      var testBadge = '';
      if(p.test_status==='ok') testBadge = '<span class="tag tag-ok">✓ 连通</span>';
      else if(p.test_status==='fail') testBadge = '<span class="tag tag-err">✗ 失败</span>';
      else if(p.test_status==='error') testBadge = '<span class="tag tag-err">⚠ 错误</span>';
      html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;">'+
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'+
          '<span style="width:8px;height:8px;border-radius:50%;background:'+dotColor+';flex-shrink:0;"></span>'+
          '<span style="font-weight:600;font-size:13px;flex:1;">'+p.name+'</span>'+
          testBadge+
        '</div>'+
        '<div style="font-size:10px;color:var(--muted);margin-bottom:6px;">'+
          p.models_configured+'/'+p.models_total+' 模型 · '+
          (p.has_key ? 'Key: '+p.key_masked : '未配置')+
        '</div>'+
        '<div style="display:flex;gap:4px;">'+
          '<button onclick="showKeyInput(\''+p.id+'\')" style="font-size:10px;padding:3px 8px;cursor:pointer;background:var(--accent);color:#000;border:none;border-radius:4px;">🔑 设置</button>'+
          (p.has_key ? '<button onclick="testProvider(\''+p.id+'\')" style="font-size:10px;padding:3px 8px;cursor:pointer;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;">🔍 测试</button>' : '')+
          (p.has_key ? '<button onclick="deleteProvider(\''+p.id+'\')" style="font-size:10px;padding:3px 8px;cursor:pointer;background:none;color:var(--danger);border:1px solid var(--danger);border-radius:4px;">🗑</button>' : '')+
        '</div>'+
      '</div>';
    }
    html += '</div>';
    document.getElementById('providerList').innerHTML = html;
  }).catch(function(e){ document.getElementById('providerList').innerHTML = '<span class=error-block>加载失败</span>'; });
  // v1.5.17: 同时加载MCP服务器
  loadMcpServers();
}

function showKeyInput(pid){
  var name = {'deepseek':'DeepSeek','openai':'OpenAI','anthropic':'Anthropic','bailian':'阿里百炼'}[pid]||pid;
  var key = prompt('输入 '+name+' API Key (留空删除):');
  if(key===null) return;
  fetch('/api/providers', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({provider:pid, key:key})
  }).then(function(r){return r.json()}).then(function(d){
    renderProviders();
    fetchModels(); // 刷新模型就绪状态
    fetchSummary();
  }).catch(function(e){ alert('保存失败: '+e); });
}

function testProvider(pid){
  var btn = event.target;
  btn.textContent = '⏳...'; btn.disabled = true;
  fetch('/api/providers/'+pid+'/test', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if(d.success){
      btn.textContent = '✅ OK'; btn.style.color = 'var(--accent2)';
    } else {
      btn.textContent = '❌ '+d.status; btn.style.color = 'var(--danger)';
    }
    setTimeout(function(){ btn.textContent = '🔍 测试'; btn.disabled = false; btn.style.color = ''; renderProviders(); }, 2000);
  }).catch(function(e){
    btn.textContent = '⚠ 错误'; btn.disabled = false;
    setTimeout(function(){ btn.textContent = '🔍 测试'; renderProviders(); }, 2000);
  });
}

function deleteProvider(pid){
  if(!confirm('确认删除 '+pid+' 的API Key?')) return;
  fetch('/api/providers/'+pid, {method:'DELETE'}).then(function(r){return r.json()}).then(function(d){
    renderProviders(); fetchModels(); fetchSummary();
  });
}

// ═══ v1.5.23 会话历史浏览器 ═══
function renderHistory(){
  var search = document.getElementById('historySearch') ? document.getElementById('historySearch').value : '';
  var url = '/api/sessions/archive?limit=50';
  if(search) url += '&search=' + encodeURIComponent(search);
  fetch(url).then(function(r){return r.json();}).then(function(d){
    var el = document.getElementById('historySessions');
    if(!el) return;
    if(!d.sessions || d.sessions.length === 0){
      el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px;">暂无存档会话<br><span style="font-size:11px;">Chat对话完成后自动存档</span></div>';
      return;
    }
    var html = '';
    d.sessions.forEach(function(s){
      var date = s.created_at ? new Date(s.created_at*1000).toLocaleDateString('zh-CN') : '';
      var preview = (s.first_message||'').substring(0,60);
      var color = s.last_role === 'assistant' ? '#38bdf8' : '#94a3b8';
      html += '<div class="history-item" onclick="viewSession(''+s.id+'')" style="background:#1e293b;border-radius:8px;padding:10px;cursor:pointer;transition:all 0.2s;" onmouseover="this.style.background=\'#334155\'" onmouseout="this.style.background=\'#1e293b\'">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">';
      html += '<span style="color:'+color+';font-size:13px;font-weight:600;">'+preview+'</span>';
      html += '<span style="color:var(--muted);font-size:10px;">'+s.message_count+'条 · '+date+'</span>';
      html += '</div>';
      html += '<div style="color:var(--muted);font-size:11px;">'+(s.last_content||'').substring(0,80)+'</div>';
      html += '<div style="color:#6366f1;font-size:10px;margin-top:3px;">🤖 '+(s.model||'默认')+'</div>';
      html += '</div>';
    });
    el.innerHTML = html;
  }).catch(function(e){
    var el = document.getElementById('historySessions');
    if(el) el.innerHTML = '<div style="color:#fca5a5;">加载失败: '+e.message+'</div>';
  });
}

function viewSession(sid){
  fetch('/api/sessions/archive/'+sid).then(function(r){return r.json();}).then(function(d){
    var html = '<div style="background:#0f172a;border-radius:12px;padding:16px;max-width:800px;margin:0 auto;">';
    html += '<h3 style="color:#38bdf8;margin-bottom:12px;">📜 会话详情 ('+d.count+'条消息)</h3>';
    d.messages.forEach(function(m){
      var role = m.role === 'user' ? '👤 You' : '🤖 AI';
      var bg = m.role === 'user' ? '#1e293b' : '#312e81';
      var content = (m.content||'').substring(0,300);
      html += '<div style="background:'+bg+';border-radius:8px;padding:10px;margin:6px 0;font-size:12px;">';
      html += '<strong style="color:'+(m.role===\'user\'?\'#e2e8f0\':\'#a5b4fc\')+';margin-bottom:4px;display:block;">'+role+'</strong>';
      html += '<div style="color:#cbd5e1;">'+content+'</div>';
      html += '</div>';
    });
    html += '<button onclick="document.getElementById(\'sessionDetail\').innerHTML=\'\'" style="margin-top:10px;background:#334155;color:#e2e8f0;border:none;border-radius:6px;padding:6px 16px;cursor:pointer;">关闭</button>';
    html += '</div>';
    var detail = document.getElementById('sessionDetail');
    if(!detail){
      detail = document.createElement('div');
      detail.id = 'sessionDetail';
      detail.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;';
      detail.onclick = function(e){if(e.target===detail)detail.innerHTML='';};
      document.body.appendChild(detail);
    }
    detail.innerHTML = html;
    showToast('📜 查看会话: '+d.count+'条消息');
  }).catch(function(e){
    showToast('❌ 加载会话失败: '+e.message);
  });
}

// ═══ v1.5.21 配置导出/导入 ═══
async function exportConfig(){
  try {
    var res = await fetch('/api/config/export');
    var d = await res.json();
    var blob = new Blob([JSON.stringify(d, null, 2)], {type:'application/json'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    var ts = new Date().toISOString().replace(/[:.]/g,'-').slice(0,19);
    a.href = url;
    a.download = 'meshctx-config-'+ts+'.json';
    a.click();
    URL.revokeObjectURL(url);
    showToast('✅ 配置已导出 (Key已脱敏)');
  }catch(e){
    showToast('❌ 导出失败: '+e.message);
  }
}

async function importConfig(input){
  var file = input.files[0];
  if(!file) return;
  try {
    var text = await file.text();
    var data = JSON.parse(text);
    var res = await fetch('/api/config/import', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    var d = await res.json();
    if(d.success){
      showToast('✅ 导入完成: '+d.imported+'项, 跳过'+d.skipped+'项');
      loadProviders();
      loadMcpServers();
    }else{
      showToast('❌ 导入失败');
    }
  }catch(e){
    showToast('❌ 导入失败: '+e.message);
  }
  input.value = '';
}

function showToast(msg){
  var t = document.getElementById('meshctx-toast');
  if(!t){
    t = document.createElement('div');
    t.id = 'meshctx-toast';
    t.style.cssText = 'position:fixed;bottom:20px;right:20px;background:rgba(0,0,0,0.85);color:#fff;padding:10px 20px;border-radius:8px;z-index:9999;font-size:13px;animation:fadeOut 3s forwards;';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.animation = 'none';
  t.offsetHeight;
  t.style.animation = 'fadeOut 3s forwards';
}

// ═══ v1.5.20 .meshctx.md 多项目上下文 ═══
function loadMeshctxMd(){
  var statusEl = document.getElementById('meshctxMdStatus');
  var previewEl = document.getElementById('meshctxMdPreview');
  var selector = document.getElementById('projectSelector');
  
  // 加载项目列表
  fetch('/api/context/projects').then(function(r){return r.json()}).then(function(pd){
    if(pd.projects && pd.projects.length > 0){
      selector.innerHTML = '<option value="">(自动检测)</option>';
      pd.projects.forEach(function(p){
        var sel = p.path === pd.active ? ' selected' : '';
        selector.innerHTML += '<option value="'+p.path+'"'+sel+'>'+p.title+' ('+p.name+')</option>';
      });
    }
  }).catch(function(e){ console.log('项目列表加载失败:', e); });
  
  // 加载当前上下文
  fetch('/api/context/meshctx-md').then(function(r){return r.json()}).then(function(d){
    if(d.found){
      statusEl.innerHTML = '<div style="display:flex;align-items:center;gap:8px;">'+
        '<span class="dot on"></span>'+
        '<span style="color:var(--accent2);font-weight:600;">✅ .meshctx.md 已加载</span>'+
        '<span style="color:var(--muted);font-size:10px;">'+ (d.path||'').split('/').slice(-3).join('/') +'</span>'+
        '</div>';
      if(previewEl){
        previewEl.style.display = 'block';
        previewEl.textContent = (d.content||'').substring(0, 800) + ((d.content||'').length > 800 ? '...' : '');
      }
    } else {
      statusEl.innerHTML = '<div style="display:flex;align-items:center;gap:8px;color:var(--muted);">'+
        '<span class="dot off"></span>'+
        '<span>📄 未检测到 .meshctx.md — 创建此文件自动注入上下文</span>'+
        '</div>'+
        '<div style="margin-top:6px;"><button onclick="createMeshctxMd()" style="background:#2563eb;color:#fff;border:none;border-radius:4px;padding:3px 10px;font-size:11px;cursor:pointer;">+ 创建模板</button></div>';
      if(previewEl) previewEl.style.display = 'none';
    }
  }).catch(function(e){ statusEl.innerHTML = '<span class=error-block>加载失败: '+e.message+'</span>'; });
}

function switchProject(path){
  fetch('/api/context/project/activate', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path:path||''})
  }).then(function(r){return r.json()}).then(function(d){
    loadMeshctxMd();
  }).catch(function(e){ console.log('项目切换失败:', e); });
}

function createMeshctxMd(){
  var content = '# 项目名称\n\n## 技术栈\n- Python 3.10+\n- FastAPI\n\n## 项目简介\n简要描述你的项目...\n\n## 关键约定\n- 使用TDD\n- 70测试必须全过';
  navigator.clipboard.writeText(content).then(function(){
    var el = document.getElementById('meshctxMdStatus');
    el.innerHTML += '<br><span style="color:#22c55e;">✅ 模板已复制! 创建 .meshctx.md 后刷新</span>';
  });
}
  }).catch(function(e){ document.getElementById('meshctxMdStatus').innerHTML = '<span class=error-block>加载失败</span>'; });
}

// ═══ v1.5.16 会话历史 ═══
function loadConversations(search){
  var url = '/api/conversations/history?limit=20';
  if(search) url += '&search='+encodeURIComponent(search);
  fetch(url).then(function(r){return r.json()}).then(function(d){
    var convs = d.conversations || [];
    var html = '';
    if(convs.length===0){
      html = '<div class="empty">📭 '+(search?'无匹配会话':'暂无会话记录')+'</div>';
    } else {
      html += '<div style="font-size:10px;color:var(--muted);margin-bottom:8px;">共 '+d.total+' 个会话</div>';
      for(var i=0;i<convs.length;i++){
        var c = convs[i];
        html += '<div class="row" style="cursor:pointer;padding:8px 4px;flex-wrap:wrap;" onclick="window.open(\'/ui/chat\',\'_blank\')">'+
          '<span style="flex:1;font-weight:500;">💬 '+c.title+'</span>'+
          '<span style="font-size:10px;color:var(--muted);">'+c.message_count+' 条消息</span>'+
          '<span style="font-size:9px;color:var(--muted);margin-left:auto;">'+(c.project_name||'')+'</span>'+
          '</div>';
      }
    }
    document.getElementById('convHistoryList').innerHTML = html;
  }).catch(function(e){ document.getElementById('convHistoryList').innerHTML = '<span class=error-block>加载失败</span>'; });
}

function searchConversations(){
  var q = document.getElementById('convSearch').value;
  loadConversations(q);
}

// ═══ v1.5.17 MCP服务器管理 ═══
function loadMcpServers(){
  fetch('/api/mcp-servers').then(function(r){return r.json()}).then(function(d){
    var servers = d.servers || [];
    var html = '';
    if(servers.length===0){
      html = '<div class="empty">🔌 暂无MCP服务器 — 点击"+ 添加"配置</div>';
    } else {
      for(var i=0;i<servers.length;i++){
        var s = servers[i];
        var statusColor = s.status==='connected'?'var(--accent2)':s.status==='error'?'var(--danger)':'var(--border)';
        var statusIcon = s.status==='connected'?'✓':s.status==='error'?'✗':'?';
        var enabled = s.enabled !== false;
        html += '<div style="background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:6px;">'+
          '<div style="display:flex;align-items:center;gap:8px;">'+
            '<span style="width:8px;height:8px;border-radius:50%;background:'+statusColor+';flex-shrink:0;"></span>'+
            '<span style="font-weight:600;font-size:13px;flex:1;">'+s.name+'</span>'+
            '<span style="font-size:10px;color:'+statusColor+';">'+statusIcon+' '+s.status+'</span>'+
            '<span class="tag '+(enabled?'tag-ok':'tag-err')+'" style="font-size:9px;cursor:pointer;" onclick="toggleMcp(\''+s.id+'\')">'+(enabled?'启用':'禁用')+'</span>'+
            '<button onclick="deleteMcp(\''+s.id+'\')" style="font-size:10px;background:none;color:var(--danger);border:1px solid var(--danger);border-radius:4px;cursor:pointer;padding:2px 6px;">🗑</button>'+
          '</div>'+
          '<div style="font-size:10px;color:var(--muted);margin-top:4px;font-family:monospace;">'+s.command+' '+(s.args||[]).join(' ')+'</div>'+
          (s.last_tested ? '<div style="font-size:9px;color:var(--muted);">上次测试: '+new Date(s.last_tested*1000).toLocaleString()+'</div>' : '')+
        '</div>';
      }
    }
    document.getElementById('mcpServerList').innerHTML = html;
  }).catch(function(e){ document.getElementById('mcpServerList').innerHTML = '<span class=error-block>加载失败</span>'; });
}

function showAddMcpForm(){
  var name = prompt('MCP服务器名称:');
  if(!name) return;
  var command = prompt('命令 (如 npx 或 python):');
  if(!command) return;
  var argsStr = prompt('参数 (空格分隔, 可选):','');
  var args = argsStr ? argsStr.trim().split(/\\s+/) : [];
  
  fetch('/api/mcp-servers', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name, command:command, args:args})
  }).then(function(r){return r.json()}).then(function(d){
    if(d.success) loadMcpServers();
    else alert('添加失败: '+JSON.stringify(d));
  }).catch(function(e){ alert('请求失败: '+e); });
}

function toggleMcp(sid){
  fetch('/api/mcp-servers/'+sid+'/toggle', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    loadMcpServers();
  });
}

function deleteMcp(sid){
  if(!confirm('确认删除此MCP服务器?')) return;
  fetch('/api/mcp-servers/'+sid, {method:'DELETE'}).then(function(r){return r.json()}).then(function(d){
    loadMcpServers();
  });
}

// ═══ 启动 ═══
fetchModels();
startAutoRefresh();

// ═══ Feishu Webhook v2.9 ═══
function saveFeishu(){
  var url = document.getElementById('feishuUrl').value.trim();
  var secret = document.getElementById('feishuSecret').value.trim();
  if(!url){ alert('请输入Webhook URL'); return; }
  localStorage.setItem('meshctx_feishu_url', url);
  localStorage.setItem('meshctx_feishu_secret', secret);
  document.getElementById('feishuStatus').innerHTML = '<span style="color:#22c55e;">✅ 已保存</span>';
  setTimeout(function(){ document.getElementById('feishuStatus').innerHTML = ''; }, 2000);
}
function testFeishu(){
  var url = document.getElementById('feishuUrl').value.trim();
  var secret = document.getElementById('feishuSecret').value.trim();
  if(!url){ alert('请先输入Webhook URL'); return; }
  var statusEl = document.getElementById('feishuStatus');
  statusEl.innerHTML = '<span style="color:#94a3b8;">⏳ 发送测试消息...</span>';
  fetch('/api/feishu/test', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({webhook_url:url, secret:secret})
  }).then(function(r){return r.json()}).then(function(d){
    if(d.success){
      statusEl.innerHTML = '<span style="color:#22c55e;">✅ 测试成功！请查看飞书群消息</span>';
      saveFeishu();
    }else{
      statusEl.innerHTML = '<span style="color:#fca5a5;">❌ 发送失败，请检查Webhook地址</span>';
    }
  }).catch(function(e){
    statusEl.innerHTML = '<span style="color:#fca5a5;">❌ 请求失败: '+e.message+'</span>';
  });
}
// Load saved feishu config on init
(function(){
  var savedUrl = localStorage.getItem('meshctx_feishu_url');
  var savedSecret = localStorage.getItem('meshctx_feishu_secret');
  if(savedUrl) document.getElementById('feishuUrl').value = savedUrl;
  if(savedSecret) document.getElementById('feishuSecret').value = savedSecret;
})();

// ═══ Multi-Notify v2.14 ═══
function saveMultiNotify(){
  ['tgToken','tgChatId','dcWebhook','slWebhook'].forEach(function(id){
    var val = document.getElementById(id).value.trim();
    if(val) localStorage.setItem('meshctx_'+id, val);
  });
  document.getElementById('multiNotifyStatus').innerHTML = '<span style="color:#22c55e;">✅ 已保存</span>';
  setTimeout(function(){ document.getElementById('multiNotifyStatus').innerHTML = ''; }, 2000);
}
function testMultiNotify(){
  var el = document.getElementById('multiNotifyStatus');
  el.innerHTML = '<span style="color:#94a3b8;">⏳ 发送中...</span>';
  var body = {text: '✅ MeshCtx v2.14 多通道通知测试成功!'};
  var tg = document.getElementById('tgToken').value.trim();
  var tcid = document.getElementById('tgChatId').value.trim();
  var dc = document.getElementById('dcWebhook').value.trim();
  var sl = document.getElementById('slWebhook').value.trim();
  if(tg&&tcid){ body.telegram_token = tg; body.telegram_chat_id = tcid; }
  if(dc) body.discord_webhook = dc;
  if(sl) body.slack_webhook = sl;
  fetch('/api/notify/broadcast', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body)
  }).then(function(r){return r.json()}).then(function(d){
    if(d.success) el.innerHTML = '<span style="color:#22c55e;">✅ 广播成功: '+JSON.stringify(d.results)+'</span>';
    else el.innerHTML = '<span style="color:#fca5a5;">❌ 发送失败</span>';
    saveMultiNotify();
  });
}
(function(){
  ['tgToken','tgChatId','dcWebhook','slWebhook'].forEach(function(id){
    var val = localStorage.getItem('meshctx_'+id);
    if(val) document.getElementById(id).value = val;
  });
})();

// ═══ Sandbox v2.8.1 SSE ═══
function runSandbox(){
  var lang = document.getElementById('sandboxLang').value;
  var code = document.getElementById('sandboxCode').value;
  var timeout = parseInt(document.getElementById('sandboxTimeout').value) || 30;
  if(!code.trim()){ alert('请输入代码'); return; }
  var resultEl = document.getElementById('sandboxResult');
  resultEl.style.display = 'block';
  resultEl.style.color = '#94a3b8';
  resultEl.textContent = '⏳ 执行中...\n';
  
  // Use SSE streaming
  fetch('/api/sandbox/execute/stream', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({code:code, language:lang, timeout:timeout})
  }).then(function(response){
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    resultEl.textContent = '';
    
    function read(){
      reader.read().then(function(result){
        if(result.done){
          resultEl.style.color = '#22c55e';
          return;
        }
        var text = decoder.decode(result.value, {stream:true});
        var lines = text.split('\n');
        for(var i=0;i<lines.length;i++){
          if(lines[i].startsWith('data: ')){
            try{
              var d = JSON.parse(lines[i].substring(6));
              if(d.type==='stdout' && d.line !== undefined){
                resultEl.textContent += d.line + '\n';
              }else if(d.type==='stderr' && d.line){
                resultEl.textContent += '[STDERR] ' + d.line + '\n';
              }else if(d.type==='done'){
                resultEl.textContent += '\n[退出码: '+d.exit_code+' | 耗时: '+d.duration_ms+'ms | '+d.method+']';
                resultEl.style.color = d.exit_code===0 ? '#22c55e' : '#fca5a5';
              }else if(d.type==='error'){
                resultEl.textContent += '\n[ERROR] ' + d.message;
                resultEl.style.color = '#fca5a5';
              }
            }catch(e){}
          }
        }
        resultEl.scrollTop = resultEl.scrollHeight;
        read(); // Continue reading
      });
    }
    read();
  }).catch(function(e){
    resultEl.textContent = '执行失败: ' + e.message;
    resultEl.style.color = '#fca5a5';
  });
}

// ═══ Project Indexer v2.8 ═══
function searchProject(){
  var q = document.getElementById('projectQuery').value.trim();
  if(!q){alert('请输入搜索词');return;}
  fetch('/api/project/search?q=' + encodeURIComponent(q) + '&top_k=10').then(function(r){return r.json()}).then(function(d){
    var results = d.results || [];
    var html = '';
    for(var i=0;i<results.length;i++){
      var r = results[i];
      html += '<div class="stat-card" style="border-left:3px solid #06b6d4;">'+
        '<strong style="color:#38bdf8;">'+r.path+'</strong>'+
        '<span style="font-size:10px;color:var(--muted);margin-left:8px;">'+r.language+' · '+r.line_count+'行 · '+(r.size/1024).toFixed(1)+'KB</span>'+
        '<p style="font-size:11px;color:var(--muted);margin-top:4px;">'+r.summary+'</p>';
      if(r.symbols && r.symbols.length){
        html += '<div style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;">';
        r.symbols.slice(0,8).forEach(function(s){
          html += '<span style="background:#1e293b;color:#a5b4fc;font-size:10px;padding:2px 6px;border-radius:3px;">'+s+'</span>';
        });
        html += '</div>';
      }
      html += '</div>';
    }
    document.getElementById('projectResults').innerHTML = html || '<div class="stat-card" style="text-align:center;color:var(--muted);">未找到匹配文件</div>';
  });
}

function refreshProjectIndex(){
  var statsEl = document.getElementById('projectStats');
  statsEl.textContent = '⏳ 扫描中...';
  fetch('/api/project/index').then(function(r){return r.json()}).then(function(d){
    var langs = [];
    for(var l in d.languages) langs.push(l+':'+d.languages[l]);
    statsEl.innerHTML = '📊 <b>'+d.total_files+'</b> 文件 · <b>'+(d.total_size/1024/1024).toFixed(1)+'MB</b> · <b>'+d.total_lines.toLocaleString()+'</b> 行 · '+langs.join(', ');
    document.getElementById('projectResults').innerHTML = '';
  }).catch(function(e){
    statsEl.textContent = '❌ 扫描失败: ' + e.message;
  });
}

</script>
</body>
</html>"""


# ── DictLoader 初始化 ───────────────────────────────────────────
_jinja_env = Environment(loader=DictLoader(_TEMPLATES), autoescape=False)

def _render(template_name: str, context: dict) -> HTMLResponse:
    """渲染 Jinja2 模板（从内嵌 DictLoader）"""
    template = _jinja_env.get_template(template_name)
    html = template.render(**context)
    return HTMLResponse(html)

router = APIRouter(prefix="/ui", tags=["Web UI"])


# ── 工具函数 ─────────────────────────────────────────────────

def _engine(request: Request):
    """获取 memory_engine 实例"""
    return request.app.state.memory_engine


def _continuity_label(score: float) -> str:
    if score >= 0.7:
        return "优秀"
    elif score >= 0.5:
        return "良好"
    elif score >= 0.3:
        return "一般"
    return "断裂"


def _continuity_color(score: float) -> str:
    if score >= 0.7:
        return "#22c55e"
    elif score >= 0.5:
        return "#eab308"
    elif score >= 0.3:
        return "#f97316"
    return "#ef4444"


def _format_dt(dt):
    """格式化日期时间"""
    if dt is None:
        return "-"
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)[:19]


def _truncate(s: str, n: int = 60) -> str:
    if len(s) <= n:
        return s
    return s[:n] + "..."


# ── 仪表板首页 ───────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    engine = _engine(request)
    projects = engine.list_projects()

    project_data = []
    total_conversations = 0
    total_memories = 0
    total_agents = 0
    total_sessions = 0

    for p in projects:
        try:
            continuity = engine.detect_continuity(p.id)
        except Exception:
            continuity = {"continuity_score": 0, "is_continuous": False,
                          "conversation_count": 0, "memory_count": 0,
                          "active_session_count": 0, "total_session_count": 0,
                          "last_active": None}
        convs = engine.list_conversations(p.id)
        total_conversations += len(convs)
        memories = engine.get_memories(p.id)
        total_memories += len(memories)
        sessions = engine.get_agent_sessions(project_id=p.id)
        total_sessions += len(sessions)
        project_data.append({
            "project": p,
            "continuity": continuity,
            "conv_count": len(convs),
            "mem_count": len(memories),
            "session_count": len(sessions),
        })

    agents = list(engine.agents.values())
    total_agents = len(agents)

    safe_project_data = []
    for d in project_data:
        p = d["project"]
        safe_project_data.append({
            "project": {"id": p.id, "name": p.name, "description": p.description,
                       "status": p.status, "created_at": _format_dt(p.created_at),
                       "updated_at": _format_dt(p.updated_at)},
            "continuity": d["continuity"],
            "conv_count": d["conv_count"],
            "mem_count": d["mem_count"],
            "session_count": d["session_count"],
        })

    return _render("dashboard.html", {
        "request": request,
        "title": "meshctx 管理面板",
        "project_data": safe_project_data,
        "total_projects": len(projects),
        "total_conversations": total_conversations,
        "total_memories": total_memories,
        "total_agents": total_agents,
        "total_sessions": total_sessions,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
        "format_dt": _format_dt,
    })


# ── 项目管理 ─────────────────────────────────────────────────

@router.get("/projects", response_class=HTMLResponse)
async def project_list(request: Request):
    engine = _engine(request)
    projects = engine.list_projects()

    enriched = []
    for p in projects:
        convs = engine.list_conversations(p.id)
        mems = engine.get_memories(p.id)
        try:
            cont = engine.detect_continuity(p.id)
        except Exception:
            cont = {"continuity_score": 0, "last_active": None}
        enriched.append({
            "project": p,
            "conv_count": len(convs),
            "mem_count": len(mems),
            "continuity": cont,
        })

    enriched.sort(key=lambda x: x["project"].updated_at, reverse=True)

    return _render("projects.html", {
        "request": request,
        "title": "项目管理",
        "projects": enriched,
        "format_dt": _format_dt,
        "truncate": _truncate,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
    })


@router.post("/projects/create")
async def create_project_ui(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
):
    engine = _engine(request)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    engine.create_project(name, description, tag_list)
    return RedirectResponse(url="/ui/projects", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    engine = _engine(request)
    project = engine.get_project(project_id)
    if not project:
        return HTMLResponse("<h2>项目不存在</h2>", status_code=404)

    conversations = engine.list_conversations(project_id)
    memories = engine.get_memories(project_id)
    sessions = engine.get_agent_sessions(project_id=project_id)

    try:
        continuity = engine.detect_continuity(project_id)
    except Exception:
        continuity = {"continuity_score": 0, "is_continuous": False}

    conv_data = []
    for c in conversations:
        msgs = engine.get_messages(c.id, limit=200)
        active_sessions = [s for s in sessions if s.conversation_id == c.id and s.ended_at is None]
        conv_data.append({
            "conversation": c,
            "message_count": len(msgs),
            "active_sessions": active_sessions,
        })

    conv_data.sort(key=lambda x: x["conversation"].updated_at, reverse=True)

    return _render("project_detail.html", {
        "request": request,
        "title": f"项目: {project.name}",
        "project": project,
        "conversations": conv_data,
        "memories": memories,
        "continuity": continuity,
        "agent_sessions": sessions,
        "format_dt": _format_dt,
        "truncate": _truncate,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
    })


@router.post("/projects/{project_id}/delete")
async def delete_project_ui(request: Request, project_id: str):
    engine = _engine(request)
    engine.delete_project(project_id)
    return RedirectResponse(url="/ui/projects", status_code=303)


# ── 会话查看 ─────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}", response_class=HTMLResponse)
async def conversation_view(request: Request, conversation_id: str):
    engine = _engine(request)
    conv = engine.get_conversation(conversation_id)
    if not conv:
        return HTMLResponse("<h2>会话不存在</h2>", status_code=404)

    messages = engine.get_messages(conversation_id, limit=200)
    project = engine.get_project(conv.project_id)

    return _render("conversation.html", {
        "request": request,
        "title": f"会话: {conv.title}",
        "conversation": conv,
        "project": project,
        "messages": messages,
        "format_dt": _format_dt,
        "truncate": _truncate,
    })


# ── 记忆浏览 ─────────────────────────────────────────────────

@router.get("/memories", response_class=HTMLResponse)
async def memories_overview(request: Request):
    """所有项目的记忆总览"""
    engine = _engine(request)
    projects = engine.list_projects()
    all_memories = []

    for p in projects:
        mems = engine.get_memories(p.id)
        for m in mems:
            all_memories.append({
                "memory": m,
                "project_name": p.name,
            })

    all_memories.sort(key=lambda x: x["memory"].importance, reverse=True)

    return _render("memories.html", {
        "request": request,
        "title": "记忆浏览",
        "memories": all_memories,
        "projects": projects,
        "format_dt": _format_dt,
        "truncate": _truncate,
    })


@router.post("/memories/{memory_id}/delete")
async def delete_memory_ui(request: Request, memory_id: str):
    engine = _engine(request)
    engine.delete_memory(memory_id)
    return RedirectResponse(url="/ui/memories", status_code=303)


# ── 连续性检测仪表板 ──────────────────────────────────────────

@router.get("/continuity", response_class=HTMLResponse)
async def continuity_dashboard(request: Request):
    """所有项目的连续性检测仪表板"""
    engine = _engine(request)
    projects = engine.list_projects()

    data = []
    for p in projects:
        try:
            cont = engine.detect_continuity(p.id)
        except Exception:
            cont = {"continuity_score": 0, "is_continuous": False,
                    "conversation_count": 0, "memory_count": 0,
                    "active_session_count": 0, "total_session_count": 0,
                    "last_active": None}
        data.append({
            "project": p,
            "continuity": cont,
        })

    data.sort(key=lambda x: x["continuity"]["continuity_score"], reverse=True)

    continuous_count = sum(1 for d in data if d["continuity"]["is_continuous"])

    return _render("continuity.html", {
        "request": request,
        "title": "连续性检测",
        "data": data,
        "continuous_count": continuous_count,
        "total_count": len(data),
        "format_dt": _format_dt,
        "continuity_label": _continuity_label,
        "continuity_color": _continuity_color,
    })

# ── Chat 页面 ───────────────────────────────────────────

@router.get("/desktop", response_class=HTMLResponse)
async def desktop_page(request: Request):
    return _render("desktop.html", {"request": request, "title": "Desktop"})

@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return _render("chat.html", {"request": request, "title": "Chat"})

@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    flash = ""
    if request.query_params.get("saved") == "1":
        flash = "success"
    elif request.query_params.get("error") == "1":
        flash = "error"
    
    # 合并内置模型 + 已配置模型
    configured = []
    seen_ids = set()
    try:
        from src.model_registry import get_registry, BUILTIN_MODELS
        reg = get_registry()
        
        # 读取config.yaml获取已配置模型详情
        from pathlib import Path
        cp = Path.home() / ".meshctx" / "config.yaml"
        config = {}
        if cp.exists():
            import yaml as _yaml2
            with open(cp) as f:
                config = _yaml2.safe_load(f) or {}
        entries = config.get("models", {}).get("entries", {})
        default_id = config.get("models", {}).get("default", "")
        
        # 1. 内置模型 (BUILTIN_MODELS)
        # Build reverse lookup: (provider, model) -> config entry
        provider_model_to_entry = {}
        for mid, einfo in entries.items():
            pm_key = (einfo.get("provider", ""), einfo.get("model", ""))
            provider_model_to_entry[pm_key] = (mid, einfo)
        
        for mid, info in BUILTIN_MODELS.items():
            seen_ids.add(mid)
            # Exact ID match or fuzzy (provider+model) match
            is_configured = mid in entries
            config_entry = None
            
            if is_configured:
                config_entry = entries[mid]
            else:
                # Fuzzy match: same provider+model but different ID format
                pm_key = (info.get("provider", ""), info.get("model", ""))
                if pm_key in provider_model_to_entry:
                    config_mid, config_entry = provider_model_to_entry[pm_key]
                    is_configured = True
            
            entry = {
                "id": mid,
                "model": info.get("model", mid),
                "provider": info.get("provider", "?"),
                "base_url": info.get("base_url", ""),
                "ready": is_configured,
                "is_default": (default_id == mid),
                "builtin": True,
            }
            if is_configured and config_entry:
                raw_key = config_entry.get("key", "")
                if raw_key:
                    entry["key_full"] = raw_key
                    entry["key_masked"] = raw_key[:6] + "****" + raw_key[-4:] if len(raw_key) > 10 else "****"
            configured.append(entry)
        
        # 2. 用户自定义模型 (不在BUILTIN_MODELS中)
        for mid, einfo in entries.items():
            if mid in seen_ids:
                # Already shown as builtin, just update
                for item in configured:
                    if item["id"] == mid:
                        item["ready"] = True
                        raw_key = einfo.get("key", "")
                        if raw_key:
                            item["key_full"] = raw_key
                            item["key_masked"] = raw_key[:6] + "****" + raw_key[-4:] if len(raw_key) > 10 else "****"
                        item["base_url"] = einfo.get("base_url", item.get("base_url", ""))
                        break
            else:
                # Custom model not in builtins
                raw_key = einfo.get("key", "")
                configured.append({
                    "id": mid,
                    "model": einfo.get("model", mid),
                    "provider": einfo.get("provider", "?"),
                    "base_url": einfo.get("base_url", ""),
                    "ready": True,
                    "is_default": (default_id == mid),
                    "builtin": False,
                    "key_full": raw_key,
                    "key_masked": raw_key[:6] + "****" + raw_key[-4:] if len(raw_key) > 10 else ("****" if raw_key else ""),
                })
    except:
        pass
    
    # 排序: 默认最前 → 已配置 → 按provider
    configured.sort(key=lambda m: (
        not m.get("is_default", False),
        not m.get("ready", False),
        m.get("provider", ""),
    ))
    
    # 未配置模型默认折叠(仅显示前20)
    unconfigured_count = sum(1 for m in configured if not m.get("ready"))
    show_all = request.query_params.get("all") == "1"
    has_more = False
    if not show_all and unconfigured_count > 20:
        ready = [m for m in configured if m.get("ready")]
        unready = [m for m in configured if not m.get("ready")][:20]
        configured = ready + unready
        has_more = True
    
    return _render("setup.html", {
        "request": request, "title": "Setup",
        "flash": flash, "configured": configured,
        "has_more_unconfigured": has_more,
        "total_unconfigured": unconfigured_count,
    })


@router.post("/setup/save")
async def save_api_key(
    request: Request,
    provider: str = Form(...),
    api_key: str = Form(...),
    base_url: str = Form(""),
    model_name: str = Form(""),
):
    """保存 API Key 并自动重载配置 — 无需重启"""
    from pathlib import Path

    config_path = Path.home() / ".meshctx" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}

    provider_defaults = {
        "deepseek": {"model_id": "deepseek:chat", "model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY"},
        "bailian": {"model_id": "bailian:qwen-flash", "model": "qwen-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "key_env": "BAILIAN_API_KEY"},
        "siliconflow": {"model_id": "siliconflow:qwen-flash", "model": "Qwen/Qwen2.5-7B-Instruct", "base_url": "https://api.siliconflow.cn/v1", "key_env": "SILICONFLOW_API_KEY"},
    }
    defaults = provider_defaults.get(provider, provider_defaults["deepseek"])
    actual_model = model_name or defaults["model"]
    actual_url = base_url or defaults["base_url"]
    model_id = defaults["model_id"]  # 使用内置目录中的标准ID

    config.setdefault("models", {})
    config["models"].setdefault("entries", {})
    config["models"]["default"] = model_id
    # v1.8: 加密存储 API Key
    encrypted_key = api_key
    try:
        from src.core.crypto import encrypt_key
        encrypted_key = encrypt_key(api_key)
    except:
        pass
    config["models"]["entries"][model_id] = {
        "key": encrypted_key,
        "model": actual_model,
        "base_url": actual_url,
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    # 设置环境变量立即可用，ConfigWatcher会自动检测文件变更并重载
    os.environ[defaults["key_env"]] = api_key

    return RedirectResponse(url="/ui/setup?saved=1", status_code=303)


@router.post("/setup/delete")
async def delete_api_key(
    request: Request,
    model_id: str = Form(...),
):
    """删除指定模型的API密钥"""
    from pathlib import Path
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    if not config_path.exists():
        return RedirectResponse(url="/ui/setup?error=1", status_code=303)
    
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    
    entries = config.get("models", {}).get("entries", {})
    if model_id in entries:
        del entries[model_id]
        # 如果删除的是默认模型，清除默认
        if config.get("models", {}).get("default") == model_id:
            config["models"]["default"] = next(iter(entries), "") if entries else ""
    
    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    
    # 清除环境变量
    from src.model_registry import _registry
    import src.model_registry as mr
    mr._registry = None
    
    return RedirectResponse(url="/ui/setup?deleted=1", status_code=303)


# ── v2.17 系统仪表盘 ─────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><title>Dashboard - MeshCtx</title>
<style>
:root{--bg:#0b0e1a;--card-bg:rgba(255,255,255,0.04);--border:rgba(255,255,255,0.08);--text:#e0e4f0;--muted:#8090b0;--accent:#6c5ce7;--green:#22c55e;--red:#f85149;--yellow:#fbbf24}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#0b0e1a,#1a1f35);color:var(--text);min-height:100vh;padding:24px}
nav{display:flex;gap:12px;margin-bottom:24px}
nav a{color:var(--muted);text-decoration:none;padding:8px 16px;border-radius:8px;font-size:14px}
.container{max-width:1000px;margin:0 auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:20px;text-align:center}
.card .v{font-size:36px;font-weight:700;margin:8px 0}
.card .l{font-size:12px;color:var(--muted)}
.green{color:var(--green)} .red{color:var(--red)} .yellow{color:var(--yellow)} .purple{color:var(--accent)}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:16px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--border)}
th{color:var(--muted)}
</style></head><body>
<div class="container">
<nav><a href="/ui/chat">Chat</a><a href="/ui/setup">Setup</a><a href="/ui/plugins">Plugins</a><a href="/ui/dashboard" style="color:var(--accent);background:rgba(108,92,231,0.15);">Dashboard</a></nav>
<h2 style="margin-bottom:16px;">📊 System Dashboard</h2>
<div class="grid" id="stats"></div>
<div class="card" style="margin-bottom:16px;text-align:left">
<h3 style="margin-bottom:8px">🛡️ Watchdog</h3>
<div id="wdStatus" style="font-size:12px;color:var(--muted)">Loading...</div>
</div>
<h3 style="margin-top:8px;">API Endpoints</h3>
<table><thead><tr><th>Endpoint</th><th>Latency</th><th>Status</th></tr></thead><tbody id="epTable"></tbody></table>
<div id="pluginStatus" style="margin-top:16px;"></div>
</div>
<script>
async function load(){
  var r=await fetch('/api/system/status');
  var d=await r.json();
  var s='';
  s+=card('Version',d.version,'purple');
  s+=card('Models',d.models.configured+'/'+d.models.builtin,'green');
  s+=card('Plugins',d.plugins.available,'yellow');
  s+=card('Sessions',d.sessions.total,'green');
  s+=card('Python',d.server.python,'purple');
  document.getElementById('stats').innerHTML=s;
  
  // Ping endpoints
  var eps=['/api/version','/api/health','/api/models','/api/plugins/market','/api/feishu/status'];
  var rows='';
  for(var i=0;i<eps.length;i++){
    var t0=performance.now();
    var ok=false;
    try{var r2=await fetch(eps[i]);ok=r2.ok}catch(e){}
    var ms=(performance.now()-t0).toFixed(0);
    rows+='<tr><td>'+eps[i]+'</td><td>'+ms+'ms</td><td style="color:'+(ok?'var(--green)':'var(--red)')+'">'+(ok?'OK':'FAIL')+'</td></tr>';
  }
  document.getElementById('epTable').innerHTML=rows;
  
  // Plugin status
  var r3=await fetch('/api/plugins/market');
  var pd=await r3.json();
  var ps='<h3>Plugins</h3><table><tr><th>Name</th><th>Status</th><th>Installs</th></tr>';
  pd.plugins.forEach(function(p){
    ps+='<tr><td>'+p.icon+' '+p.name+'</td><td style="color:'+(p.status=='active'?'var(--green)':'var(--yellow)')+'">'+p.status+'</td><td>'+p.installs+'</td></tr>';
  });
  ps+='</table>';
  document.getElementById('pluginStatus').innerHTML=ps;
  
  // Watchdog
  try{
    var wd=await fetch('/api/watchdog/status');
    var w=await wd.json();
    var ws='<div style="display:flex;gap:12px;flex-wrap:wrap">';
    ws+=badge('Running',w.running?'✅':'❌',w.running?'green':'red');
    ws+=badge('Uptime',w.uptime_human,'purple');
    ws+=badge('Checks',w.stats.checks_total,'yellow');
    ws+=badge('Fixed',w.stats.issues_fixed,'green');
    for(var k in w.subsystems){
      var s=w.subsystems[k];
      ws+=badge(k,s.status,s.status=='ok'?'green':'yellow');
    }
    ws+='</div>';
    if(w.recent_alerts&&w.recent_alerts.length){
      ws+='<div style="margin-top:8px;font-size:11px;color:var(--muted)">Recent alerts: '+w.recent_alerts.length+'</div>';
    }
    document.getElementById('wdStatus').innerHTML=ws;
  }catch(e){}
}
function badge(label,value,color){return '<span style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:4px 12px;text-align:center"><div style="font-size:10px;color:var(--muted)">'+label+'</div><div class="'+color+'" style="font-size:16px;font-weight:700">'+value+'</div></span>'}
function card(label,value,color){return '<div class="card"><div class="l">'+label+'</div><div class="v '+color+'">'+value+'</div></div>'}
load();
setInterval(load, 30000);

// WebSocket real-time watchdog (every 15s)
try {
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var ws = new WebSocket(protocol + '//' + location.host + '/ws/dashboard');
    ws.onmessage = function(e) {
        var d = JSON.parse(e.data);
        if (d.type === 'watchdog') {
            var w = d.data;
            var wsHtml = '<div style="display:flex;gap:12px;flex-wrap:wrap">';
            wsHtml += badge('Running', w.running?'✅':'❌', w.running?'green':'red');
            wsHtml += badge('Uptime', w.uptime, 'purple');
            wsHtml += badge('Checks', w.checks, 'yellow');
            wsHtml += badge('Alerts', w.alerts, w.alerts>0?'red':'green');
            for (var k in w.subsystems) {
                var s = w.subsystems[k];
                wsHtml += badge(k, s.status, s.status=='ok'?'green':'yellow');
            }
            wsHtml += '</div>';
            document.getElementById('wdStatus').innerHTML = wsHtml;
        }
    };
    ws.onerror = function() { /* WebSocket fallback to poll */ };
} catch(e) {} // Auto-refresh every 30s
</script></body></html>""")

# ── v2.17 插件市场 ─────────────────────────────────────

@router.get("/plugins", response_class=HTMLResponse)
async def plugins_page(request: Request):
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><title>Plugins - MeshCtx</title>
<style>
:root{--bg:#0b0e1a;--card-bg:rgba(255,255,255,0.04);--border:rgba(255,255,255,0.08);--text:#e0e4f0;--muted:#8090b0;--accent:#6c5ce7}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:linear-gradient(135deg,#0b0e1a,#1a1f35);color:var(--text);min-height:100vh;padding:24px}
nav{display:flex;gap:12px;margin-bottom:24px}
nav a{color:var(--muted);text-decoration:none;padding:8px 16px;border-radius:8px;font-size:14px}
nav a:hover{background:rgba(108,92,231,0.15);color:var(--accent)}
.container{max-width:860px;margin:0 auto}
body.light{background:#f8fafc;color:#1e293b}
body.light .card{background:#fff;border-color:#e2e8f0}
body.light nav a{color:#64748b}
body.light input,body.light select{background:#fff;border-color:#e2e8f0;color:#1e293b}
.card{background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:16px}
.btn{padding:8px 20px;border-radius:8px;border:none;font-weight:600;cursor:pointer;font-size:13px}
.btn-primary{background:linear-gradient(135deg,#6c5ce7,#5a4bd1);color:#fff}
input,select{padding:8px 12px;background:#1e293b;border:1px solid #334155;color:var(--text);border-radius:8px}
</style></head><body>
<div class="container">
<nav><a href="/ui/chat">Chat</a><a href="/ui/setup">Setup</a><a href="/ui/plugins" style="color:var(--accent);background:rgba(108,92,231,0.15);">Plugins</a></nav>
<h2>Plugins</h2>
<p style="color:var(--muted);margin-bottom:16px">Community plugins for MeshCtx</p>
<div style="display:flex;gap:8px;margin-bottom:16px">
<input id="pluginSearch" placeholder="Search..." style="flex:1" oninput="loadPlugins()">
<select id="pluginCat" onchange="loadPlugins()"><option value="">All</option></select>
</div>
<div id="pluginList" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px">
<div style="text-align:center;color:var(--muted);padding:40px">Loading...</div>
</div>
</div>
<script>
var _installed = {};
async function loadInstalled(){
  try{var r=await fetch('/api/plugins/installed');var d=await r.json();_installed=d.installed||{};}catch(e){}
}
async function loadPlugins(){
var q=document.getElementById('pluginSearch').value;
var cat=document.getElementById('pluginCat').value;
var list=document.getElementById('pluginList');
list.innerHTML='<div style="text-align:center;color:var(--muted);padding:40px">Loading...</div>';
try{
var r=await fetch('/api/plugins/market?search='+encodeURIComponent(q)+'&category='+encodeURIComponent(cat));
var d=await r.json();
if(!d.plugins.length){list.innerHTML='<div style="text-align:center;color:var(--muted);padding:40px">No plugins</div>';return}
list.innerHTML=d.plugins.map(function(p){
var isInstalled = _installed[p.name] !== undefined;
var isBuiltin = p.builtin;
var btnHtml;
if(isBuiltin && isInstalled){btnHtml='<span style="font-size:11px;color:#22c55e;">✅ 已激活</span>'}
else if(isInstalled){btnHtml='<button class="btn" style="font-size:11px;padding:4px 12px;background:#22c55e;color:#fff;" onclick="uninstallPlugin(&quot;'+p.name+'&quot;,this)">✅ 已安装</button>'}
else if(isBuiltin){btnHtml='<button class="btn btn-primary" style="font-size:11px;padding:4px 12px" onclick="installPlugin(&quot;'+p.name+'&quot;,this)">⚡ 激活</button>'}
else{btnHtml='<button class="btn btn-primary" style="font-size:11px;padding:4px 12px" onclick="installPlugin(&quot;'+p.name+'&quot;,this)">📥 安装</button>'}
return '<div class="card"><div style="display:flex;justify-content:space-between;align-items:start"><div><span style="font-size:24px">'+p.icon+'</span> <strong>'+p.name+'</strong> <span style="font-size:10px;color:var(--muted)">v'+p.version+'</span></div><span style="font-size:10px;background:#1e293b;padding:2px 6px;border-radius:4px">'+(p.builtin?'内置':'社区')+'</span></div><p style="font-size:12px;color:var(--muted);margin:8px 0">'+p.description+'</p><div style="display:flex;justify-content:space-between;align-items:center"><span style="font-size:10px;color:var(--muted)">'+p.author+'</span>'+btnHtml+'</div></div>';
}).join('');
var sel=document.getElementById('pluginCat');
var cur=sel.value;
sel.innerHTML='<option value="">All</option>'+d.categories.map(function(c){return '<option value="'+c+'">'+c+'</option>'}).join('');
sel.value=cur;
}catch(e){list.innerHTML='<div style="color:#f85149;padding:20px">Error: '+e.message+'</div>'}
}
async function installPlugin(name,btn){
btn.textContent='Installing...';btn.disabled=true;
try{
var r=await fetch('/api/plugins/install',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});
if(r.ok){_installed[name]={}; btn.textContent='✅ 已安装';btn.style.background='#22c55e';btn.style.color='#fff'}
else{var d=await r.json();alert(d.detail||'Failed');btn.textContent='📥 安装';btn.disabled=false}
}catch(e){alert(e.message);btn.textContent='📥 安装';btn.disabled=false}
}
async function uninstallPlugin(name,btn){
if(!confirm('确定卸载 '+name+'?'))return;
btn.textContent='卸载中...';btn.disabled=true;
try{
var r=await fetch('/api/plugins/uninstall',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})});
if(r.ok){delete _installed[name];loadPlugins();}
else{var d=await r.json();alert(d.detail||'Failed');btn.textContent='✅ 已安装';btn.disabled=false}
}catch(e){alert(e.message);btn.textContent='✅ 已安装';btn.disabled=false}
}
(async function(){await loadInstalled();loadPlugins();})();
</script></body></html>""")

# ── v1.5.13 下载页面 ─────────────────────────────────────

@router.get("/download", response_class=HTMLResponse)
async def download_page(request: Request):
    html = r"""{% extends "base.html" %}
{% block content %}
<h2>💻 下载 meshctx Desktop v1.8.2</h2>
<div class="card" style="margin-top:16px;">
  <h3>🪟 Windows 原生客户端</h3>
  <p style="color:var(--muted);">独立 .exe 程序，无需 Python，支持46+ AI模型，下载即用</p>
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin:16px 0;">
    <div style="flex:1;min-width:200px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center;">
      <p>📦 <b>便携版 meshctx.exe</b><br><span style="font-size:11px;color:var(--muted);">~211MB · 解压即用</span></p>
      <a class="btn btn-primary" href="https://meshctx.com/meshctx-v1.8.2.exe" style="display:inline-block;text-decoration:none;padding:10px 20px;margin-top:8px;">⬇ 下载便携版</a>
    </div>
    <div style="flex:1;min-width:200px;background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center;">
      <p>💿 <b>安装版 meshctx-setup.exe</b><br><span style="font-size:11px;color:var(--muted);">~210MB · NSIS安装程序</span></p>
      <a class="btn btn-primary" href="https://meshctx.com/meshctx-setup-v1.8.2.exe" style="display:inline-block;text-decoration:none;padding:10px 20px;margin-top:8px;">⬇ 下载安装版</a>
    </div>
  </div>
  <p style="font-size:11px;color:var(--muted);">SHA256: <code style="word-break:break-all;font-size:10px;">95d766ea...</code>&nbsp;·&nbsp;<a href="https://meshctx.com/sha256.txt" target="_blank">校验文件</a></p>
  <p style="font-size:11px;color:var(--muted);">⚙ Win10/11 x64 · 首次运行可能触发SmartScreen → "更多信息"→"仍要运行"</p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>🌐 Web直接使用</h3>
  <p>💬 <a href="/ui/chat">Chat</a> · 📊 <a href="/ui/desktop">Desktop</a> · ⚙ <a href="/ui/setup">Setup</a></p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>📋 命令行安装 (高级)</h3>
  <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);">powershell -c "Invoke-WebRequest https://meshctx.com/meshctx-setup-v1.8.2.exe -OutFile meshctx-setup.exe; Start-Process meshctx-setup.exe"</pre>
</div>
{% endblock %}"""
    _TEMPLATES["download.html"] = html
    return _render("download.html", {"request": request, "title": "Download"})


# ── 模型列表页面 ────────────────────────────────────────────

_TEMPLATES["models.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>🤖 模型列表</h2>
<div style="display:flex;gap:12px;margin:16px 0;flex-wrap:wrap;">
    <div class="stat-card"><div class="value" id="totalModels">-</div><div class="label">模型总数</div></div>
    <div class="stat-card"><div class="value" id="configuredModels">-</div><div class="label">已配置</div></div>
    <div class="stat-card"><div class="value" id="usableModels">-</div><div class="label">可用</div></div>
    <div class="stat-card"><div class="value" id="currentModel">-</div><div class="label">当前默认</div></div>
</div>
<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <input id="modelSearch" placeholder="搜索模型..." style="max-width:300px;" oninput="filterModels()">
        <a href="/ui/setup" class="btn btn-primary">+ 配置模型</a>
    </div>
    <table>
        <thead><tr><th>模型ID</th><th>提供商</th><th>状态</th><th>Key环境变量</th></tr></thead>
        <tbody id="modelTableBody"><tr><td colspan="4" style="text-align:center;color:var(--muted);">加载中...</td></tr></tbody>
    </table>
</div>
<script>
async function loadModels(){
    try{
        var res = await fetch('/api/models');
        var data = await res.json();
        document.getElementById('totalModels').textContent = data.total || 0;
        document.getElementById('configuredModels').textContent = data.configured || 0;
        document.getElementById('usableModels').textContent = data.usable || 0;
        document.getElementById('currentModel').textContent = data.current || '-';
        window._models = data.models || [];
        renderModels(window._models);
    }catch(e){
        document.getElementById('modelTableBody').innerHTML = '<tr><td colspan="4" style="color:#f85149;">加载失败: '+e.message+'</td></tr>';
    }
}
function renderModels(models){
    var tbody = document.getElementById('modelTableBody');
    if(!models.length){
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted);">暂无模型</td></tr>';
        return;
    }
    tbody.innerHTML = models.map(function(m){
        var status = m.usable ? '<span style="color:#22c55e;">🟢 可用</span>' : (m.configured ? '<span style="color:#eab308;">🟡 已配置</span>' : '<span style="color:#64748b;">⚫ 未配置</span>');
        var isCurrent = m.current ? ' ⭐' : '';
        return '<tr><td><strong>'+m.id+'</strong>'+isCurrent+'<br><span style="font-size:10px;color:var(--muted);">'+m.model_name+'</span></td><td>'+m.provider_name+'</td><td>'+status+'</td><td><code style="font-size:10px;background:#1e293b;padding:2px 6px;border-radius:4px;">'+m.key_env+'</code></td></tr>';
    }).join('');
}
function filterModels(){
    var q = document.getElementById('modelSearch').value.toLowerCase();
    var filtered = (window._models||[]).filter(function(m){
        return m.id.toLowerCase().includes(q) || m.provider_name.toLowerCase().includes(q) || m.model_name.toLowerCase().includes(q);
    });
    renderModels(filtered);
}
loadModels();
</script>
{% endblock %}"""


@router.get("/models", response_class=HTMLResponse)
async def models_page(request: Request):
    return _render("models.html", {"request": request, "title": "Models"})


# ── 供应商列表页面 ───────────────────────────────────────────

_TEMPLATES["providers.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>🔌 供应商</h2>
<div style="display:flex;gap:12px;margin:16px 0;flex-wrap:wrap;">
    <div class="stat-card"><div class="value" id="totalProviders">-</div><div class="label">供应商总数</div></div>
    <div class="stat-card"><div class="value" id="configuredProviders">-</div><div class="label">已配置Key</div></div>
</div>
<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <input id="providerSearch" placeholder="搜索供应商..." style="max-width:300px;" oninput="filterProviders()">
        <a href="/ui/setup" class="btn btn-primary">+ 配置供应商</a>
    </div>
    <table>
        <thead><tr><th>供应商</th><th>状态</th><th>Key</th><th>已配置模型</th><th>上次测试</th><th>操作</th></tr></thead>
        <tbody id="providerTableBody"><tr><td colspan="6" style="text-align:center;color:var(--muted);">加载中...</td></tr></tbody>
    </table>
</div>
<script>
async function loadProviders(){
    try{
        var res = await fetch('/api/providers');
        var data = await res.json();
        document.getElementById('totalProviders').textContent = data.total || 0;
        document.getElementById('configuredProviders').textContent = data.configured || 0;
        window._providers = data.providers || [];
        renderProviders(window._providers);
    }catch(e){
        document.getElementById('providerTableBody').innerHTML = '<tr><td colspan="6" style="color:#f85149;">加载失败: '+e.message+'</td></tr>';
    }
}
function renderProviders(providers){
    var tbody = document.getElementById('providerTableBody');
    if(!providers.length){
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);">暂无供应商</td></tr>';
        return;
    }
    tbody.innerHTML = providers.map(function(p){
        var status = p.has_key ? '<span style="color:#22c55e;">🟢 已配置</span>' : '<span style="color:#64748b;">⚫ 未配置</span>';
        var testStatus = p.test_status === 'ok' ? '<span style="color:#22c55e;">✅</span>' : (p.test_status === 'fail' ? '<span style="color:#f85149;">❌</span>' : '<span style="color:var(--muted);">—</span>');
        var lastTested = p.last_tested || '-';
        return '<tr><td><strong>'+p.name+'</strong><br><span style="font-size:10px;color:var(--muted);">'+p.id+'</span></td><td>'+status+'</td><td><code style="font-size:10px;background:#1e293b;padding:2px 6px;border-radius:4px;">'+(p.key_masked||'—')+'</code></td><td>'+p.models_configured+'/'+p.models_total+'</td><td>'+testStatus+' '+lastTested+'</td><td><a href="/ui/setup" style="font-size:12px;">⚙️ 配置</a></td></tr>';
    }).join('');
}
function filterProviders(){
    var q = document.getElementById('providerSearch').value.toLowerCase();
    var filtered = (window._providers||[]).filter(function(p){
        return p.id.toLowerCase().includes(q) || p.name.toLowerCase().includes(q);
    });
    renderProviders(filtered);
}
loadProviders();
</script>
{% endblock %}"""


@router.get("/providers", response_class=HTMLResponse)
async def providers_page(request: Request):
    return _render("providers.html", {"request": request, "title": "Providers"})
