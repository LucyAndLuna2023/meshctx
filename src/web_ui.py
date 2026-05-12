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
        input:focus, textarea:focus { border-color: #2563eb; outline: none; }
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; font-size: 13px; color: #94a3b8; margin-bottom: 4px; }
        .empty { text-align: center; color: #64748b; padding: 40px; }
        .flash { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
        .flash-success { background: #065f46; color: #6ee7b7; }
        .flash-error { background: #7f1d1d; color: #fca5a5; }
        a { color: #38bdf8; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
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
    </div>
    <div style="margin-left:auto;display:flex;align-items:center;gap:4px;">
        <select onchange="document.cookie='meshctx_lang='+this.value+';path=/';location.reload()" 
                style="background:#1e293b;border:1px solid #334155;color:#94a3b8;padding:4px 8px;border-radius:4px;font-size:12px;cursor:pointer;">
            <option value="zh">中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
            <option value="ko">한국어</option>
        </select>
    </div>
</div>
<div class="main">
{% block content %}{% endblock %}
</div>
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
<div class="empty">📭 暂无记忆</div>
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
<div class="card" style="margin-top:16px; min-height:400px;" id="chatCard">
    <div id="messages" style="max-height:500px;overflow-y:auto;"></div>
    <div id="fileTag" style="margin-top:8px;font-size:12px;color:#38bdf8;display:none;"></div>
    <div style="display:flex;gap:8px;margin-top:16px;">
        <input id="userInput" placeholder="输入消息..." style="flex:1;" onkeydown="if(event.key==='Enter')send()">
        <button class="btn" style="background:#334155;color:#94a3b8;font-size:16px;padding:8px 12px;" onclick="document.getElementById('fileInput').click()" title="上传文件">📎</button>
        <button class="btn btn-primary" onclick="send()">发送</button>
    </div>
    <input type="file" id="fileInput" style="display:none" onchange="uploadFile()">
</div>
<script>
let uploadedContent = null;
let uploadedFilename = null;

async function uploadFile() {
    const input = document.getElementById('fileInput');
    const file = input.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    const tag = document.getElementById('fileTag');
    tag.style.display = 'block';
    tag.textContent = '⏳ 上传中: ' + file.name;
    try {
        const res = await fetch('/api/chat/upload', {method: 'POST', body: formData});
        if (!res.ok) {
            const err = await res.json();
            tag.innerHTML = '<span style="color:#fca5a5;">❌ ' + (err.detail || '上传失败') + '</span>';
            return;
        }
        const data = await res.json();
        uploadedContent = data.content;
        uploadedFilename = data.filename;
        tag.innerHTML = '📄 ' + data.filename + ' <span style="color:#64748b;">(' + (data.size > 1024 ? (data.size/1024).toFixed(1)+'KB' : data.size+'B') + ')</span> <a href="#" onclick="clearFile()" style="color:#f87171;text-decoration:none;">✕</a>';
    } catch(e) {
        tag.innerHTML = '<span style="color:#fca5a5;">❌ 上传失败: ' + e.message + '</span>';
    }
    input.value = '';
}

function clearFile() {
    uploadedContent = null;
    uploadedFilename = null;
    document.getElementById('fileTag').style.display = 'none';
    document.getElementById('fileInput').value = '';
}

async function send() {
    const input = document.getElementById('userInput');
    const msg = input.value.trim();
    if (!msg) return;
    let fullMsg = msg;
    if (uploadedContent && uploadedFilename) {
        fullMsg = '[上传文件: ' + uploadedFilename + ']\n```\n' + uploadedContent + '\n```\n\n' + msg;
    }
    const div = document.getElementById('messages');
    const displayMsg = uploadedFilename ? '[📄 ' + uploadedFilename + '] ' + msg : msg;
    div.innerHTML += `<div style="margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;"><strong>You:</strong> ${displayMsg}</div>`;
    input.value = '';
    clearFile();
    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: fullMsg, project_id: 'default'})
        });
        const data = await res.json();
        div.innerHTML += `<div style="margin:8px 0;padding:8px;background:#1e293b;border-radius:8px;"><strong style="color:#38bdf8;">AI:</strong> ${data.response || '无响应'}</div>`;
        div.scrollTop = div.scrollHeight;
    } catch(e) {
        div.innerHTML += `<div style="margin:8px 0;color:#fca5a5;">错误: ${e.message}</div>`;
    }
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
</script>
{% endblock %}"""

_TEMPLATES["setup.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>⚙️ Setup</h2>

{% if flash == "success" %}
<div class="flash flash-success">✅ API Key 已保存！配置已自动生效，无需重启。</div>
{% elif flash == "error" %}
<div class="flash flash-error">❌ 保存失败，请重试。</div>
{% endif %}

<div class="card" style="margin-top:16px;">
    <h2>🔑 配置 API 密钥</h2>
    <p style="color:#94a3b8;margin-bottom:16px;font-size:13px;">
        选择一个模型提供商，输入你的 API Key，点击保存即可。
    </p>
    <form method="POST" action="/ui/setup/save">
        <div class="form-group">
            <label>模型提供商</label>
            <select name="provider" style="background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:10px 14px;border-radius:6px;font-size:14px;width:100%;">
                <option value="deepseek">🟢 DeepSeek（推荐 — 性价比最高）</option>
                <option value="bailian">🔵 阿里云百炼（新用户免费100万Tokens）</option>
                <option value="siliconflow">🔴 硅基流动 SiliconFlow（开源模型免费额度）</option>
            </select>
        </div>
        <div class="form-group">
            <label>API Key</label>
            <input name="api_key" type="password" placeholder="sk-xxxxxxxxxxxxxxxx" required
                   style="background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:10px 14px;border-radius:6px;font-size:14px;width:100%;">
        </div>
        <details style="margin-bottom:12px;">
            <summary style="color:#64748b;font-size:13px;cursor:pointer;padding:4px 0;">📝 高级配置（可选）</summary>
            <div class="form-group" style="margin-top:8px;">
                <label>Base URL</label>
                <input name="base_url" type="text" placeholder="自动填充默认地址"
                       style="background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:10px 14px;border-radius:6px;font-size:14px;width:100%;">
            </div>
            <div class="form-group">
                <label>模型名称</label>
                <input name="model_name" type="text" placeholder="自动填充默认模型"
                       style="background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:10px 14px;border-radius:6px;font-size:14px;width:100%;">
            </div>
        </details>
        <button type="submit" class="btn btn-primary" style="width:100%;padding:12px;font-size:15px;">💾 保存配置</button>
    </form>
</div>

<div class="card" style="margin-top:16px;">
    <h3>🔗 还没有 API Key？</h3>
    <div style="display:grid;gap:12px;margin-top:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;padding:12px;background:#0f172a;border-radius:8px;">
            <div>
                <strong>🟢 DeepSeek</strong>
                <p style="font-size:12px;color:#94a3b8;">高性价比，deepseek-chat / deepseek-reasoner</p>
            </div>
            <a href="https://platform.deepseek.com/api_keys" target="_blank" class="btn btn-primary" style="font-size:12px;">获取 →</a>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:12px;background:#0f172a;border-radius:8px;">
            <div>
                <strong>🔵 阿里云百炼</strong>
                <p style="font-size:12px;color:#94a3b8;">新用户赠送100万Tokens，支持Qwen系列</p>
            </div>
            <a href="https://bailian.console.aliyun.com/" target="_blank" class="btn btn-primary" style="font-size:12px;">获取 →</a>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center;padding:12px;background:#0f172a;border-radius:8px;">
            <div>
                <strong>🔴 硅基流动 SiliconFlow</strong>
                <p style="font-size:12px;color:#94a3b8;">开源模型免费额度，Llama/Qwen/DeepSeek</p>
            </div>
            <a href="https://siliconflow.cn/" target="_blank" class="btn btn-primary" style="font-size:12px;">获取 →</a>
        </div>
    </div>
</div>

<div class="card" style="margin-top:16px;">
    <h3>📝 手动配置（高级）</h3>
    <p style="font-size:12px;color:#94a3b8;margin-bottom:8px;">编辑 <code style="background:#0f172a;padding:2px 6px;border-radius:4px;">~/.meshctx/config.yaml</code>:</p>
    <pre style="background:#0f172a;padding:12px;border-radius:8px;font-size:12px;overflow-x:auto;">models:
  default: "deepseek:deepseek-chat"
  entries:
    deepseek:deepseek-chat:
      key: "sk-your-key-here"
      model: "deepseek-chat"
      base_url: "https://api.deepseek.com/v1"</pre>
</div>
{% endblock %}"""

# ── DictLoader 初始化 ───────────────────────────────────────────
_jinja_env = Environment(loader=DictLoader(_TEMPLATES))

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
    return _render("setup.html", {"request": request, "title": "Setup", "flash": flash})


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
        "deepseek": {"model": "deepseek-chat", "base_url": "https://api.deepseek.com/v1"},
        "bailian": {"model": "qwen-plus", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "siliconflow": {"model": "Qwen/Qwen2.5-7B-Instruct", "base_url": "https://api.siliconflow.cn/v1"},
    }
    defaults = provider_defaults.get(provider, provider_defaults["deepseek"])
    actual_model = model_name or defaults["model"]
    actual_url = base_url or defaults["base_url"]
    model_id = f"{provider}:{actual_model}"

    config.setdefault("models", {})
    config["models"].setdefault("entries", {})
    config["models"]["default"] = model_id
    config["models"]["entries"][model_id] = {
        "key": api_key,
        "model": actual_model,
        "base_url": actual_url,
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    # 立即重载模型注册表，无需重启
    try:
        import src.model_registry as mr
        mr._registry = None  # 清除缓存
        from src.model_registry import get_registry
        reg = get_registry()
        available = reg.list_all()
        ready_count = sum(1 for e in available if e["ready"])
        import logging
        logging.getLogger("meshctx").info(
            f"API Key 已保存并自动重载: {ready_count}/{len(available)} 模型就绪"
        )
    except Exception:
        pass

    return RedirectResponse(url="/ui/setup?saved=1", status_code=303)
