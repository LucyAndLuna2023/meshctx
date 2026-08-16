"""
meshctx Web 管理界面
FastAPI + Jinja2 DictLoader（模板内嵌，适配 PyInstaller）
"""
import sys
import yaml
import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from pathlib import Path
from jinja2 import Environment, DictLoader, FileSystemLoader, ChoiceLoader
import logging

logger = logging.getLogger("meshctx.webui")

# ── 内嵌模板（绕过 PyInstaller 文件系统问题）───────────────────
_TEMPLATES = {}

_TEMPLATES["base.html"] = r"""<!DOCTYPE html>
<html lang="{{ __lang }}" dir="{{ 'rtl' if __lang == 'ar' else 'ltr' }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - meshctx</title>
    <style>
        /* ═══ CSS 变量：深色主题(默认) ═══ */
        :root {
            --bg: #0f172a;
            --text: #e2e8f0;
            --muted: #64748b;
            --surface: #1e293b;
            --border: #334155;
            --accent: #6c5ce7;
            --green: #22c55e;
            --red: #dc2626;
            --yellow: #fbbf24;
            --hover: #1a2332;
            --nav-hover: #334155;
            --input-bg: #0f172a;
            --header-bg: #1e293b;
            --header-h1: #6c5ce7;
            --flash-success-bg: #065f46;
            --flash-success-text: #6ee7b7;
            --flash-error-bg: #7f1d1d;
            --flash-error-text: #fca5a5;
            --link-color: #818cf8;
        }
        /* ═══ 浅色主题 ═══ */
        [data-theme="light"] {
            --bg: #f8fafc;
            --text: #0f172a;
            --muted: #64748b;
            --surface: #ffffff;
            --border: #e2e8f0;
            --accent: #6c5ce7;
            --green: #16a34a;
            --red: #dc2626;
            --yellow: #d97706;
            --hover: #f1f5f9;
            --nav-hover: #e2e8f0;
            --input-bg: #ffffff;
            --header-bg: #ffffff;
            --header-h1: #6c5ce7;
            --flash-success-bg: #dcfce7;
            --flash-success-text: #166534;
            --flash-error-bg: #fef2f2;
            --flash-error-text: #991b1b;
            --link-color: #6366f1;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; transition: background-color 0.3s ease, color 0.3s ease; }
        .header { background: var(--header-bg); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; transition: background-color 0.3s ease, border-color 0.3s ease; }
        .header h1 { font-size: 20px; color: var(--header-h1); display: flex; align-items: center; gap: 8px; }
        .header .logo-img { width: 28px; height: 28px; }
        .nav { display: flex; gap: 8px; flex-wrap: wrap; }
        .nav a { color: var(--muted); text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 14px; transition: all .2s; }
        .nav a:hover, .nav a.active { background: var(--nav-hover); color: var(--text); }
        .main { padding: 24px; max-width: 1400px; margin: 0 auto; }
        .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin-bottom: 16px; transition: background-color 0.3s ease, border-color 0.3s ease; }
        .card h2 { font-size: 18px; margin-bottom: 12px; color: var(--text); }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
        .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; text-align: center; transition: background-color 0.3s ease, border-color 0.3s ease; }
        .stat-card .value { font-size: 32px; font-weight: 700; color: var(--accent); }
        .stat-card .label { font-size: 13px; color: var(--muted); margin-top: 4px; }
        .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
        .badge-active { background: #065f46; color: #6ee7b7; }
        .badge-inactive { background: #451a03; color: #fbbf24; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; transition: border-color 0.3s ease; }
        th { color: var(--muted); font-weight: 600; }
        tr:hover { background: var(--hover); }
        .btn { display: inline-block; padding: 8px 16px; border-radius: 6px; font-size: 13px; border: none; cursor: pointer; text-decoration: none; transition: all .2s; }
        .btn-primary { background: var(--accent); color: white; }
        .btn-primary:hover { background: #5b4bd5; }
        .btn-danger { background: var(--red); color: white; }
        .btn-danger:hover { background: #b91c1c; }
        input, textarea, select { background: var(--input-bg); border: 1px solid var(--border); color: var(--text); padding: 8px 12px; border-radius: 6px; font-size: 14px; width: 100%; transition: background-color 0.3s ease, border-color 0.3s ease, color 0.3s ease; }
        input:focus, textarea:focus, select:focus, button:focus-visible { border-color: var(--accent); outline: 2px solid var(--accent); outline-offset: 2px; }
        .form-group { margin-bottom: 12px; }
        .form-group label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 4px; }
        .empty { text-align: center; color: var(--muted); padding: 40px; }
        .flash { padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; font-size: 14px; }
        .flash-success { background: var(--flash-success-bg); color: var(--flash-success-text); }
        .flash-error { background: var(--flash-error-bg); color: var(--flash-error-text); }
        a { color: var(--link-color); text-decoration: none; }
        a:hover { text-decoration: underline; }
        .cursor { display:inline-block;width:2px;height:1em;background:var(--accent);animation:blink 1s infinite;vertical-align:text-bottom;margin-left:2px; } @keyframes blink { 0%,50% {opacity:1} 51%,100% {opacity:0} }
        /* ── 代码块/终端可读性 (v2.25) ── */
        pre, code, .code-output-body, .code-output, .terminal, .console {
            color: #e6e6e6;
        }
        pre {
            background: #0d1117;
            border-radius: 6px;
            padding: 12px;
            overflow-x: auto;
            font-family: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace;
            font-size: 13px;
            line-height: 1.5;
        }
        code {
            font-family: 'SF Mono', 'Fira Code', 'Fira Mono', Menlo, Consolas, monospace;
            font-size: 13px;
        }
        :not(pre) > code {
            background: #1e293b;
            color: #e2e8f0;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 12px;
        }
        .code-output-header {
            color: #8b949e;
            font-size: 12px;
        }
        .code-output-body {
            background: #0d1117;
            color: #e6e6e6;
        }
        /* ── 浅色主题代码块覆盖 ── */
        [data-theme="light"] pre,
        [data-theme="light"] .code-output-body {
            background: #f6f8fa;
            color: #1e293b;
            border: 1px solid #d0d7de;
        }
        [data-theme="light"] code,
        [data-theme="light"] .code-output,
        [data-theme="light"] .terminal,
        [data-theme="light"] .console {
            color: #1e293b;
        }
        [data-theme="light"] :not(pre) > code {
            background: #e2e8f0;
            color: #0f172a;
        }
        [data-theme="light"] .code-output-header {
            color: #64748b;
        }
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
        /* ═══ Ctrl+K 全局命令面板 ═══ */
        .cmd-overlay {
            display: none; position: fixed; inset: 0; z-index: 9999;
            background: rgba(0,0,0,0.5); backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            align-items: flex-start; justify-content: center;
            padding-top: 15vh;
        }
        .cmd-overlay.open { display: flex; }
        .cmd-panel {
            background: #1e293b; border: 1px solid #334155;
            border-radius: 16px; width: 100%; max-width: 560px;
            box-shadow: 0 25px 60px rgba(0,0,0,0.5);
            overflow: hidden; animation: cmdSlideIn 0.15s ease-out;
        }
        @keyframes cmdSlideIn {
            from { opacity: 0; transform: translateY(-12px) scale(0.97); }
            to   { opacity: 1; transform: translateY(0) scale(1); }
        }
        .cmd-search-wrap {
            display: flex; align-items: center; gap: 10px;
            padding: 14px 18px; border-bottom: 1px solid #334155;
        }
        .cmd-search-wrap svg { flex-shrink: 0; color: #64748b; }
        .cmd-search {
            flex: 1; background: transparent; border: none; outline: none;
            color: #e2e8f0; font-size: 16px;
        }
        .cmd-search::placeholder { color: #475569; }
        .cmd-list { max-height: 360px; overflow-y: auto; padding: 8px; }
        .cmd-list::-webkit-scrollbar { width: 6px; }
        .cmd-list::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        .cmd-group { font-size: 11px; color: #64748b; padding: 8px 12px 4px; text-transform: uppercase; letter-spacing: 0.5px; }
        .cmd-item {
            display: flex; align-items: center; gap: 12px;
            padding: 10px 14px; border-radius: 8px; cursor: pointer;
            transition: background 0.1s; color: #e2e8f0; font-size: 14px;
        }
        .cmd-item:hover, .cmd-item.selected { background: #334155; }
        .cmd-item-icon { font-size: 18px; width: 24px; text-align: center; flex-shrink: 0; }
        .cmd-item-text { flex: 1; }
        .cmd-item-hint { font-size: 11px; color: #64748b; }
        .cmd-empty { text-align: center; color: #64748b; padding: 24px; font-size: 14px; }
    </style>
    <link rel="stylesheet" href="/static/lib/github-dark.min.css">
    <!-- PWA -->
    <link rel="manifest" href="/ui/manifest.json">
    <meta name="theme-color" content="#0a0a1a">
    <meta name="theme-color" media="(prefers-color-scheme: light)" content="#f8fafc">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="MeshCtx">
    <link rel="icon" type="image/svg+xml" href="/ui/icon-192.png">
    <link rel="apple-touch-icon" href="/ui/icon-192.png">
    <link rel="apple-touch-icon" sizes="192x192" href="/ui/icon-192.png">
    <link rel="apple-touch-icon" sizes="512x512" href="/ui/icon-512.png">
<script>window.__i18n = {{ __i18n_json | safe }}; window.__i18n_all = {{ __i18n_all_json | safe }}; window.__lang = '{{ __lang }}'; window.__t = function(k,lang){ var l=lang||window.__lang; return (window.__i18n_all && window.__i18n_all[l] && window.__i18n_all[l][k]) || (window.__i18n && window.__i18n[k]) || k; };</script>
</head>
<body>
<!-- Skip to main content (CRITICAL-002) -->
<a href="#main-content" style="position:absolute;top:-40px;left:0;background:var(--accent);color:white;padding:8px 16px;z-index:10000;font-size:14px;border-radius:0 0 6px 0;transition:top 0.2s;" onfocus="this.style.top='0'" onblur="this.style.top='-40px'">{{ t("skip_to_content") if t("skip_to_content") != "skip_to_content" else "Skip to main content" }}</a>
<div class="header">
    <h1><img src="/static/logo.svg" alt="" class="logo-img"> meshctx</h1>
    <div class="nav">
        <a href="/ui/" class="{% if request.url.path == '/ui/' %}active{% endif %}">{{ t("dashboard") }}</a>
        <a href="/ui/projects" class="{% if '/ui/projects' in request.url.path %}active{% endif %}">{{ t("projects") }}</a>
        <a href="/ui/memories" class="{% if '/ui/memories' in request.url.path %}active{% endif %}">{{ t("memories") }}</a>
        <a href="/ui/continuity" class="{% if '/ui/continuity' in request.url.path %}active{% endif %}">{{ t("continuity") }}</a>
        <a href="/ui/memory" class="{% if '/ui/memory' in request.url.path %}active{% endif %}">🧠 {{ t("memories") }}</a>
        <a href="/ui/chat" class="{% if '/ui/chat' in request.url.path %}active{% endif %}">{{ t("chat") }}</a>
        <a href="/ui/setup" class="{% if '/ui/setup' in request.url.path %}active{% endif %}">{{ t("setup") }}</a>
        <a href="/ui/dashboard" class="{% if '/ui/dashboard' in request.url.path %}active{% endif %}">📊 {{ t("dashboard") }}</a>
        <a href="/ui/plugins" class="{% if '/ui/plugins' in request.url.path %}active{% endif %}">🔌 {{ t("plugins") }}</a>
        <a href="/ui/files" class="{% if '/ui/files' in request.url.path %}active{% endif %}">📁 {{ t("files") }}</a>
        <a href="/docs" target="_blank" class="" style="color:#f59e0b;">📚 {{ t("api_docs") }}</a>
    </div>
    <div style="margin-left:auto;display:flex;align-items:center;gap:4px;">
        <select id="langSelect" onchange="switchLang(this.value)" 
                style="background:var(--surface);border:1px solid var(--border);color:var(--muted);padding:4px 8px;border-radius:4px;font-size:12px;cursor:pointer;">
            <option value="zh">{{ t("chinese") }}</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
            <option value="ko">한국어</option>
            <option value="fr">Français</option>
            <option value="de">Deutsch</option>
            <option value="es">Español</option>
            <option value="it">🇮🇹 Italiano</option>
            <option value="ar">🇸🇦 العربية</option>
        </select>
        <button onclick="toggleTheme()" id="themeToggle" style="background:transparent;border:1px solid var(--border);color:var(--muted);padding:4px 8px;border-radius:4px;font-size:14px;cursor:pointer;margin-left:4px;transition:border-color 0.3s ease,color 0.3s ease;" title="{{ t("toggle_theme") }}">🌙</button>
    </div>
</div>
<main class="main" id="main-content">
{% block content %}{% endblock %}
</main>
<!-- ═══ Ctrl+K 全局命令面板 ═══ -->
<div class="cmd-overlay" id="cmdOverlay" onclick="if(event.target===this)closeCmdPalette()">
    <div class="cmd-panel">
        <div class="cmd-search-wrap">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <input class="cmd-search" id="cmdSearch" type="text" placeholder="{{ t("cmd_search_placeholder") }}" aria-label="{{ t("cmd_search_placeholder") }}" autocomplete="off" oninput="filterCommands()" onkeydown="handleCmdKey(event)">
        </div>
        <div class="cmd-list" id="cmdList"></div>
    </div>
</div>
<script src="/static/lib/marked.min.js"></script>
<script src="/static/lib/highlight.min.js"></script>
<script>
marked.setOptions({breaks:true, gfm:true});
hljs.configure({languages:['python','javascript','bash','json','yaml','sql','css','html','xml','java','go','rust','cpp','typescript','shell']});

// ═══ 主题管理 ═══
var hljsLight = document.createElement('link');
hljsLight.rel = 'stylesheet';
hljsLight.id = 'hljs-theme';
hljsLight.href = '/static/lib/github.min.css';

function getSystemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function applyTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    var btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = theme === 'light' ? '☀️' : '🌙';
    // 切换 highlight.js 主题
    var existing = document.getElementById('hljs-theme');
    if (theme === 'light') {
        if (!existing) document.head.appendChild(hljsLight);
    } else {
        if (existing) existing.remove();
    }
    // 更新 meta theme-color
    var metaDark = document.querySelector('meta[name="theme-color"]:not([media])');
    if (metaDark) metaDark.content = theme === 'light' ? '#f8fafc' : '#0a0a1a';
    localStorage.setItem('meshctx_theme', theme);
}

function toggleTheme() {
    var current = document.body.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
}

// 初始化主题：localStorage > 系统偏好 > 深色
(function initTheme() {
    var saved = localStorage.getItem('meshctx_theme');
    if (saved === 'light' || saved === 'dark') {
        applyTheme(saved);
    } else {
        applyTheme(getSystemTheme());
    }
    // 监听系统主题变化
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
        if (!localStorage.getItem('meshctx_theme')) {
            applyTheme(e.matches ? 'dark' : 'light');
        }
    });
})();

// Language switcher — localStorage + cookie + server sync (QA6: cookie BEFORE fetch)
function switchLang(lang) {
    document.cookie = 'meshctx_lang=' + lang + ';path=/;max-age=31536000';
    localStorage.setItem('meshctx_lang', lang);
    window.__lang = lang;
    fetch('/api/lang/set', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({lang:lang})})
        .then(function(){ location.reload(); })
        .catch(function(){ location.reload(); });
}
(function(){
    var serverLang = window.__lang || 'zh';
    var saved = localStorage.getItem('meshctx_lang') || serverLang;
    var sel = document.getElementById('langSelect');
    if (sel) sel.value = saved;
})();
// ── Service Worker 注册 (PWA) ──
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/ui/sw.js')
        .then(function(reg) { console.log('SW registered:', reg.scope); })
        .catch(function(err) { console.log('SW registration failed:', err); });
}
// ═══ Ctrl+K 全局命令面板 ═══
var cmdCommands = [
    { group: window.__t('cmd_nav')||'导航', icon: '💬', label: 'Chat',       hint: '/ui/chat',       action: function(){ location.href='/ui/chat'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '📊', label: 'Dashboard',  hint: '/ui/dashboard',   action: function(){ location.href='/ui/dashboard'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '📁', label: 'Files',      hint: '/ui/files',       action: function(){ location.href='/ui/files'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '🧠', label: 'Memory',     hint: '/ui/memory',      action: function(){ location.href='/ui/memory'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '⚙️', label: 'Setup',      hint: '/ui/setup',       action: function(){ location.href='/ui/setup'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '🤖', label: 'Models',     hint: '/ui/models',      action: function(){ location.href='/ui/models'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '📋', label: window.__t('dashboard')||'仪表板',     hint: '/ui/',             action: function(){ location.href='/ui/'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '📦', label: window.__t('projects')||'项目',       hint: '/ui/projects',    action: function(){ location.href='/ui/projects'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '📝', label: window.__t('cmd_memories_list')||'记忆列表',   hint: '/ui/memories',    action: function(){ location.href='/ui/memories'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '🔗', label: window.__t('continuity')||'连续性',     hint: '/ui/continuity',  action: function(){ location.href='/ui/continuity'; } },
    { group: window.__t('cmd_nav')||'导航', icon: '🔌', label: window.__t('plugins')||'插件',       hint: '/ui/plugins',     action: function(){ location.href='/ui/plugins'; } },
    { group: window.__t('cmd_actions')||'操作', icon: '🌓', label: window.__t('cmd_toggle_theme')||'切换深色/浅色主题', hint: 'Toggle theme', action: function(){ toggleTheme(); closeCmdPalette(); } },
    { group: window.__t('cmd_actions')||'操作', icon: '🔄', label: window.__t('cmd_reload')||'刷新页面',   hint: 'Reload',          action: function(){ location.reload(); } },
    { group: window.__t('cmd_actions')||'操作', icon: '📚', label: window.__t('cmd_api_docs')||'API 文档',   hint: '/docs',           action: function(){ window.open('/docs','_blank'); } }
];
var cmdSelected = -1;
var cmdFiltered = [];

function openCmdPalette() {
    var overlay = document.getElementById('cmdOverlay');
    overlay.classList.add('open');
    document.getElementById('cmdSearch').value = '';
    cmdSelected = -1;
    filterCommands();
    setTimeout(function(){ document.getElementById('cmdSearch').focus(); }, 50);
}
function closeCmdPalette() {
    document.getElementById('cmdOverlay').classList.remove('open');
}
function filterCommands() {
    var q = document.getElementById('cmdSearch').value.toLowerCase().trim();
    cmdFiltered = q ? cmdCommands.filter(function(c){ return c.label.toLowerCase().indexOf(q) !== -1 || c.hint.toLowerCase().indexOf(q) !== -1 || c.group.toLowerCase().indexOf(q) !== -1; }) : cmdCommands.slice();
    cmdSelected = cmdFiltered.length > 0 ? 0 : -1;
    renderCmdList();
}
function renderCmdList() {
    var list = document.getElementById('cmdList');
    if (cmdFiltered.length === 0) {
        list.innerHTML = '<div class="cmd-empty">'+window.__t('cmd_no_results')+'</div>';
        return;
    }
    var html = '';
    var lastGroup = '';
    for (var i = 0; i < cmdFiltered.length; i++) {
        var c = cmdFiltered[i];
        if (c.group !== lastGroup) {
            html += '<div class="cmd-group">' + c.group + '</div>';
            lastGroup = c.group;
        }
        var sel = i === cmdSelected ? ' selected' : '';
        html += '<div class="cmd-item' + sel + '" data-idx="' + i + '" onmousedown="event.preventDefault();executeCmd(' + i + ')" onmouseenter="hoverCmd(' + i + ')">';
        html += '<span class="cmd-item-icon">' + c.icon + '</span>';
        html += '<span class="cmd-item-text">' + c.label + '</span>';
        html += '<span class="cmd-item-hint">' + c.hint + '</span>';
        html += '</div>';
    }
    list.innerHTML = html;
}
function hoverCmd(idx) {
    cmdSelected = idx;
    renderCmdList();
}
function handleCmdKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); closeCmdPalette(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); if (cmdFiltered.length > 0) { cmdSelected = Math.min(cmdSelected + 1, cmdFiltered.length - 1); renderCmdList(); } return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); if (cmdFiltered.length > 0) { cmdSelected = Math.max(cmdSelected - 1, 0); renderCmdList(); } return; }
    if (e.key === 'Enter')     { e.preventDefault(); if (cmdSelected >= 0 && cmdSelected < cmdFiltered.length) executeCmd(cmdSelected); return; }
}
function executeCmd(idx) {
    var c = cmdFiltered[idx];
    if (c && c.action) {
        closeCmdPalette();
        setTimeout(function(){ c.action(); }, 80);
    }
}
document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        var overlay = document.getElementById('cmdOverlay');
        if (overlay.classList.contains('open')) { closeCmdPalette(); } else { openCmdPalette(); }
    }
});

// ═══ WebSocket realtime ═══
(function() {
    var ws = null;
    var pingTimer = null;
    var reconnectTimer = null;

    function connect() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
        var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(proto + '//' + location.host + '/ws');
        ws.onopen = function() {
            pingTimer = setInterval(function() {
                if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({type:'ping'}));
            }, 30000);
        };
        ws.onmessage = function(e) {
            try {
                var msg = JSON.parse(e.data);
                if (msg.type === 'system.event' && msg.event) {
                    var toast = document.getElementById('wsToast');
                    if (!toast) {
                        toast = document.createElement('div');
                        toast.id = 'wsToast';
                        toast.style.cssText = 'position:fixed;top:16px;right:16px;background:var(--surface);color:var(--text);padding:10px 18px;border-radius:8px;border:1px solid var(--border);font-size:13px;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.3);opacity:0;transition:opacity .3s;';
                        document.body.appendChild(toast);
                    }
                    var icons = { 'model.switched': '🔄', 'agent.online': '🟢', 'agent.offline': '🔴', 'file.changed': '📝' };
                    toast.textContent = (icons[msg.event] || '📡') + ' ' + (msg.data && msg.data.model || msg.event);
                    toast.style.opacity = '1';
                    clearTimeout(toast._timeout);
                    toast._timeout = setTimeout(function(){ toast.style.opacity = '0'; }, 3000);
                }
            } catch(ex) {}
        };
        ws.onclose = function() {
            clearInterval(pingTimer);
            reconnectTimer = setTimeout(connect, 5000);
        };
        ws.onerror = function() {};
    }
    connect();
})();
  }
}

// ═══ Compare Modal Functions ═══
function cancelCompare(){
  document.getElementById('compareModal').style.display = 'none';
}
function startCompare(){
  var checks = document.querySelectorAll('#compareModelList input[type=checkbox]:checked');
  if(checks.length < 2){ alert(window.__t('请至少选择2个模型进行对比')); return; }
  var models = [];
  checks.forEach(function(c){ models.push(c.value); });
  localStorage.setItem('meshctx_compare_models', JSON.stringify(models));
  document.getElementById('compareModal').style.display = 'none';
  compareMode = true;
  var btn = document.getElementById('compareBtn');
  btn.style.background = '#22c55e';
  btn.textContent = window.__t('⚡ 对比中');
  document.getElementById('userInput').placeholder = window.__t('对比模式: 同时问')+models.length+window.__t('个模型...');
}
function closeCompare(){
  document.getElementById('compareResults').style.display = 'none';
}

async function compareSend(msg){
  var div = document.getElementById('messages');
  div.innerHTML += '<div style="margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;color:#e2e8f0;"><strong>You:</strong> ' + msg + '</div>';
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
      html += '<div style="background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px;font-size:12px;color:#e2e8f0;">'+
        '<div style="display:flex;justify-content:space-between;margin-bottom:4px;">'+
        '<strong style="color:#38bdf8;">'+r.model+'</strong>'+
        '<span style="font-size:10px;color:var(--muted);">'+r.latency_ms+'ms · '+r.tokens+'t</span></div>'+
        '<div style="color:#e2e8f0;white-space:pre-wrap;max-height:300px;overflow-y:auto;">'+r.content+'</div></div>';
    });
    html += '</div>';
    document.getElementById(loadId).outerHTML = html;
  } catch(e) {
    document.getElementById(loadId).outerHTML = window.__t('<div style="color:#fca5a5;">对比失败: ')+e.message+'</div>';
  }
}

// ── 提示词模板 ──
async function loadTemplates() {
    try {
        var res = await fetch('/api/prompts');
        var data = await res.json();
        var sel = document.getElementById('promptTemplate');
        sel.innerHTML = window.__t('<option value="">-- 选择模板 --</option>');
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
    } catch(e) { alert(window.__t('加载模板失败: ') + e.message); }
}

async function saveAsTemplate() {
    var name = prompt(window.__t('模板名称:'));
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
    } catch(e) { alert(window.__t('保存失败: ') + e.message); }
}

async function deleteTemplate() {
    var sel = document.getElementById('promptTemplate');
    var name = sel.value;
    if (!name) { alert(window.__t('请先选择模板')); return; }
    if (!confirm(window.__t('删除模板 "') + name + '"?')) return;
    try {
        var res = await fetch('/api/prompts/' + encodeURIComponent(name), {method: 'DELETE'});
        if (!res.ok) { var err = await res.json(); alert(err.detail || '删除失败'); return; }
        loadTemplates();
    } catch(e) { alert(window.__t('删除失败: ') + e.message); }
}

// ── 系统提示词 ──
function toggleSystemPrompt() {
    var area = document.getElementById('sysPromptArea');
    var btn = document.getElementById('sysPromptToggle');
    var visible = area.style.display !== 'none';
    area.style.display = visible ? 'none' : 'block';
    btn.textContent = (visible ? '⚙️ ' : '⚙️ ') + window.__t('system_prompt') + (visible ? ' ▸' : ' ▾');
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
        btn.textContent = '✅ ' + window.__t('saved');
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
    if(history.length === 0) { alert(window.__t('当前无对话可导出')); return; }
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
var chatHistoryIdx = -1;  // 历史消息索引, -1=未选择
var chatHistoryCache = []; // 缓存用户历史消息列表
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
    
    // ArrowUp: 上一条历史消息(如果输入为空或已在历史浏览中)
    if (event.key === 'ArrowUp' && !isVisible) {
        var input = document.getElementById('userInput');
        // 首次按ArrowUp时,输入必须为空(防误触)
        if (chatHistoryIdx === -1 && input.value) return;
        event.preventDefault();
        // 懒加载历史缓存
        if (chatHistoryCache.length === 0) {
            var full = JSON.parse(localStorage.getItem('meshctx_chat_' + (localStorage.getItem('meshctx_active_tab')||'default')) || '[]');
            chatHistoryCache = full.filter(function(m){ return m.role === 'user'; }).map(function(m){ return m.content; });
        }
        if (chatHistoryCache.length === 0) return;
        if (chatHistoryIdx < chatHistoryCache.length - 1) chatHistoryIdx++;
        input.value = chatHistoryCache[chatHistoryCache.length - 1 - chatHistoryIdx];
        updateTokenCount();
        return;
    }
    // ArrowDown: 下一条历史消息(与ArrowUp配对)
    if (event.key === 'ArrowDown' && chatHistoryIdx >= 0 && !isVisible) {
        event.preventDefault();
        chatHistoryIdx--;
        var input = document.getElementById('userInput');
        if (chatHistoryIdx < 0) {
            input.value = '';
            chatHistoryIdx = -1;
        } else {
            input.value = chatHistoryCache[chatHistoryCache.length - 1 - chatHistoryIdx];
        }
        updateTokenCount();
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
    // 重置历史浏览状态
    chatHistoryIdx = -1;
    chatHistoryCache = [];
    
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
        if (!fpath) { alert(window.__t('用法: /read 文件路径  或  /ls 目录路径')); return; }
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
        } catch(e) { alert(window.__t('读取失败: ') + e.message); return; }
    }
    
    // v2.7: Web搜索 /search 
    if (msg.startsWith('/search ')) {
        var query = msg.substring(8).trim();
        if (!query) { alert(window.__t('用法: /search 搜索词')); return; }
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
        } catch(e) { alert(window.__t('搜索失败: ') + e.message); return; }
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
        if (!code) { alert(window.__t('用法: /run [python|bash|js] 代码')); return; }
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
        } catch(e) { alert(window.__t('沙箱执行失败: ') + e.message); return; }
    }
    
    // v2.7: 项目上下文 /context 查询
    if (msg.startsWith('/context ')) {
        var query = msg.substring(9).trim();
        if (!query) { alert(window.__t('用法: /context 搜索词')); return; }
        try {
            var ctxRes = await fetch('/api/project/context?q=' + encodeURIComponent(query));
            var ctxData = await ctxRes.json();
            var ctxBlock = '[项目上下文: ' + query + ']\\n```\\n' + ctxData.context + '\\n```\\n';
            fullMsg = ctxBlock + '\\n用户消息: 请基于以上项目上下文回答';
            msg = '/context ' + query;
        } catch(e) { alert(window.__t('项目索引失败: ') + e.message); return; }
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
            } catch(e) { alert(window.__t('获取服务失败: ') + e.message); return; }
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
            } catch(e) { alert(window.__t('获取进程失败: ') + e.message); return; }
        } else if (action === 'system' || action === 'sys') {
            try {
                var sysRes = await fetch('/api/win/system');
                var sysData = await sysRes.json();
                fullMsg = '[Windows System Info]\n' + JSON.stringify(sysData, null, 2)
                    + '\n用户消息: 以上是Windows系统信息';
                msg = '/win system';
            } catch(e) { alert(window.__t('获取系统信息失败: ') + e.message); return; }
        } else if (action === 'exec' || action === 'ps1') {
            if (!arg) { alert(window.__t('用法: /win exec <PowerShell命令>')); return; }
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
            } catch(e) { alert(window.__t('PowerShell执行失败: ') + e.message); return; }
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
            } catch(e) { alert(window.__t('获取软件列表失败: ') + e.message); return; }
        } else {
            alert(window.__t('用法: /win services|processes|system|software|exec <PS命令>'));
            return;
        }
    }

    // v2.17: Diff 预览 /diff 文件1 文件2
    if (msg.startsWith('/diff ')) {
        var parts = msg.substring(6).trim();
        var spaceIdx = parts.indexOf(' ');
        if (spaceIdx === -1) { alert(window.__t('用法: /diff 文件1路径 文件2路径')); return; }
        var file1 = parts.substring(0, spaceIdx);
        var file2 = parts.substring(spaceIdx + 1);
        try {
            var diffRes = await fetch('/api/diff?file1=' + encodeURIComponent(file1) + '&file2=' + encodeURIComponent(file2) + '&format=compact');
            if (!diffRes.ok) { var de = await diffRes.json(); alert(window.__t('Diff失败: ') + (de.detail || de)); return; }
            var diffData = await diffRes.json();
            // 在消息区插入 diff 预览卡片
            var diffCard = document.createElement('div');
            diffCard.style.cssText = 'margin:8px 0;background:#0a1628;border:1px solid #6366f1;border-radius:10px;overflow:hidden;';
            diffCard.innerHTML = '<div style="background:#1e1b4b;padding:6px 14px;font-size:12px;color:#a5b4fc;display:flex;justify-content:space-between;align-items:center;"><span>📊 Diff: <b>' + file1 + '</b> ←→ <b>' + file2 + '</b> (' + diffData.hunks + ' hunks)</span><span style="font-size:10px;color:#818cf8;cursor:pointer;" onclick="this.parentElement.nextElementSibling.style.display=this.parentElement.nextElementSibling.style.display==\'none\'?\'\':\'none\';this.textContent=this.parentElement.nextElementSibling.style.display==\'none\'?\'展开 ▸\':\'收起 ▾\window.__t('">收起 ▾</span></div><div style="max-height:400px;overflow-y:auto;padding:4px;">') + diffData.html + '</div>';
            document.getElementById('messages').appendChild(diffCard);
            document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
            // 发送给 AI 分析
            var diffBlock = '[Diff: ' + file1 + ' ←→ ' + file2 + ' (' + diffData.hunks + ' hunks)]';
            fullMsg = diffBlock + '\n用户消息: 请分析以上diff';
            msg = '/diff ' + file1 + ' ' + file2;
        } catch(e) { alert(window.__t('Diff失败: ') + e.message); return; }
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
        } catch(e) { alert(window.__t('统计获取失败: ')+e.message); return; }
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
        userBubble.style.cssText = 'margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;color:#e2e8f0;';
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
        userBubble.style.cssText = 'margin:8px 0;padding:8px;background:#0f172a;border-radius:8px;color:#e2e8f0;';
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
    aiBubble.style.cssText = 'margin:8px 0;padding:8px;background:#1e293b;border-radius:8px;color:#e2e8f0;position:relative;';
    aiBubble.innerHTML = window.__t('<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;"><strong style="color:#38bdf8;">AI:</strong><button id="stopStreamBtn" onclick="event.stopPropagation();window._abortStream()" style="background:#dc2626;color:#fff;border:none;border-radius:4px;padding:2px 8px;font-size:10px;cursor:pointer;display:none;">⏹ 停止</button></div><span class="streamText"></span><span class="cursor">▊</span>');
    div.appendChild(aiBubble);
    const streamText = aiBubble.querySelector('.streamText');
    const cursor = aiBubble.querySelector('.cursor');
    const stopBtn = document.getElementById('stopStreamBtn');
    stopBtn.style.display = 'inline-block';
    
    // 流式状态指示器
    var statusEl = document.createElement('div');
    statusEl.className = 'stream-status';
    statusEl.style.cssText = 'color:#64748b;font-size:10px;margin-bottom:4px;';
    statusEl.textContent = window.__t('🔵 思考中...');
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
    
    // 工具调用追踪 — 在token流中检测工具调用模式
    let toolCallBuffer = '';  // 积累最近字符用以检测tool call
    let inToolCall = false;
    let currentToolName = '';
    let currentToolArgs = {};
    let toolCallDiv = null;
    
    function detectToolCallStart(text) {
        // 检测 {"tool": "xxx" 模式
        var m = text.match(/\{"tool"\s*:\s*"(\w+)"/);
        if (m) {
            return {found: true, tool: m[1], idx: text.indexOf(m[0])};
        }
        return {found: false};
    }
    
    function extractToolArgs(text) {
        var args = {};
        var re = /"(\w+)"\s*:\s*"([^"]*?)"/g;
        var m;
        while ((m = re.exec(text)) !== null) {
            if (m[1] !== 'tool') args[m[1]] = m[2];
        }
        return args;
    }

    // v2.16: 读取当前tab的系统提示词
    var sysPrompt = (allTabs[activeTab] && allTabs[activeTab].systemPrompt) || '';

    while (retryCount <= maxRetries) {
      if (streamAborted) break;
      if (retryCount > 0) {
        // 重试前等待
        var waitMs = Math.pow(2, retryCount-1) * 1000;
        streamText.innerHTML += window.__t('<div style="color:#fbbf24;font-size:11px;margin:4px 0;">⏳ 重试 ') + retryCount + '/' + maxRetries + window.__t(' (等待') + (waitMs/1000) + 's)...</div>';
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
              if(statusEl) statusEl.textContent = window.__t('✅ 完成 (') + new Date().toLocaleTimeString() + ')';
              if(cursor) cursor.style.display = 'none';
              chatHistory.push({role:'assistant', content:streamText.innerHTML});
              saveHistory();
              var raw = streamText.innerHTML;
              // v1.5.22: 渲染前处理工具调用/思考标记
              raw = raw.replace(/🔧\s*调用:\s*(\S+)/g, function(m,tool){
                return '<details style="background:#312e81;border-radius:6px;padding:6px;margin:6px 0;font-size:12px;"><summary style="cursor:pointer;color:#a5b4fc;">🔧 工具调用: '+tool+'</summary><pre style="background:#1e1b4b;color:#e6e6e6;padding:6px;border-radius:4px;overflow-x:auto;max-height:200px;"></pre></details>';
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
              } else if (parsed.token || parsed.content) {
                var token = (parsed.token !== undefined ? parsed.token : parsed.content).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                streamText.innerHTML += token;
                // 自动滚动到底部
                var msgDiv = document.getElementById('messages');
                if(msgDiv) msgDiv.scrollTop = msgDiv.scrollHeight;
                // 首token到达，更新状态
                if(statusEl && statusEl.textContent === window.__t('🔵 思考中...')) {
                    statusEl.textContent = window.__t('🟢 生成中...');
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
          streamText.innerHTML += window.__t('<span style="color:#fbbf24;">⏹ 已中断</span>');
          cursor.remove();
          break;
        }
        retryCount++;
        if (retryCount > maxRetries) {
          streamText.innerHTML += window.__t('<span style="color:#fca5a5;">❌ 失败(重试') + maxRetries + window.__t('次): ') + e.message + '</span>';
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
  if(runBtn){ runBtn.textContent = '⏳'; runBtn.disabled = true; runBtn.title=window.__t('运行中...'); }
  
  // 显示停止按钮
  var stopBtn = wrapper.querySelector('.stop-btn');
  if(stopBtn) stopBtn.style.display = 'inline-block';
  
  // 创建输出区域
  var output = document.createElement('div');
  output.className = 'code-output';
  output.innerHTML = window.__t('<div class="code-output-header"><span>▶ 输出</span><button class="output-toggle" onclick="this.parentNode.nextSibling.classList.toggle(\')collapsed\');this.textContent=this.textContent===\'展开\'?\'收起\':\'展开\window.__t('">收起</button></div><pre class="code-output-body" style="margin:0;padding:8px;white-space:pre-wrap;word-break:break-all;max-height:400px;overflow-y:auto;">⏳ 执行中...</pre>');
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
      output.querySelector('.code-output-header span').textContent = window.__t('✗ 错误');
      output.querySelector('.code-output-header span').style.color = '#fca5a5';
    } else {
      outBody.textContent = (d.output||'(无输出)') + (d.exit_code!==undefined ? '\n\n[退出码: '+d.exit_code+' | ⏱ '+elapsed+'s]' : '\n\n[⏱ '+elapsed+'s]');
      if(d.exit_code===0){
        outBody.style.color = '#22c55e';
        output.querySelector('.code-output-header span').textContent = window.__t('✓ 成功');
        output.querySelector('.code-output-header span').style.color = '#22c55e';
      } else {
        outBody.style.color = '#fbbf24';
        output.querySelector('.code-output-header span').textContent = window.__t('⚠ 警告');
        output.querySelector('.code-output-header span').style.color = '#fbbf24';
      }
    }
    // 长输出自动折叠
    if(outBody.textContent.length > 500){
      outBody.classList.add('collapsed');
      outBody.style.maxHeight = '120px';
      output.querySelector('.output-toggle').textContent = window.__t('展开');
    }
  } catch(e){
    if(e.name === 'AbortError'){
      outBody.style.color = '#fbbf24';
      outBody.textContent = window.__t('⏹ 已手动停止');
      output.querySelector('.code-output-header span').textContent = window.__t('⏹ 已停止');
    } else {
      outBody.style.color = '#fca5a5';
      outBody.textContent = window.__t('❌ 请求失败: ') + e.message;
      output.querySelector('.code-output-header span').textContent = window.__t('✗ 失败');
    }
  }
  
  if(runBtn){ runBtn.textContent = '▶'; runBtn.disabled = false; runBtn.title=window.__t('运行此代码块'); }
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
    code.style.cssText = 'flex:1;padding:8px 0;overflow-x:auto;color:#e6e6e6;';
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
"""

_TEMPLATES["models.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>{{ t('⚙️ 模型管理') }}</h2>

{% if flash == "success" %}
<div class="flash flash-success">✅ {{ t("saved_config_auto") }}</div>
{% elif flash == "error" %}
<div class="flash flash-error">❌ 操作失败。</div>
{% elif flash == "deleted" %}
<div class="flash flash-success">🗑 {{ t("deleted_ok") }}</div>
{% endif %}

<div style="display:flex;justify-content:space-between;align-items:center;margin:16px 0;">
    <h3 style="margin:0;">已配置模型 <span style="color:var(--accent);" id="modelCount">{{ configured|length }}</span></h3>
    <button class="btn btn-primary" onclick="showAddForm()" style="padding:10px 20px;">+ 添加模型</button>
</div>

<!-- v2.17: 本地模型快捷预设 -->
<div style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:6px;">
    <span style="font-size:12px;color:var(--muted);line-height:28px;">快捷预设:</span>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('ollama','qwen2.5:7b','Ollama','http://{{ ollama_host }}:11434/v1','')">🦙 Ollama</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('vllm','qwen','vLLM','http://{{ vllm_host }}:8000/v1','')">🚀 vLLM</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('localai','gpt-3.5-turbo','LocalAI','http://{{ localai_host }}:8080/v1','')">🏠 LocalAI</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('openai-compat','gpt-3.5-turbo','OpenAI兼容','https://your-api.com/v1','sk-...')">🔌 通用OpenAI</button>
    <button class="btn btn-ghost" style="font-size:11px;padding:4px 10px;" onclick="presetModel('custom','custom-model','自定义供应商','https://your-server.com','your-key')">⚙️ 完全自定义</button>
</div>

<!-- 添加/编辑表单(默认隐藏) -->
<div id="modelForm" style="display:none;margin-bottom:16px;">
    <div class="card">
        <h3 id="formTitle">添加模型</h3>
        <input type="hidden" id="editModelId">
        <div class="form-group"><label>{{ t("model_id") }}</label><input id="fid" placeholder="deepseek:chat"></div>
        <div class="form-group"><label>{{ t("provider") }}</label><input id="fprovider" placeholder="deepseek"></div>
        <div class="form-group"><label>API Key</label><input id="fkey" type="password" placeholder="sk-..."></div>
        <div class="form-group"><label>{{ t('模型名(可选)') }}</label><input id="fmodel" placeholder="auto"></div>
        <div class="form-group"><label>{{ t('Base URL(可选)') }}</label><input id="furl" placeholder="auto"></div>
        <div style="display:flex;gap:8px;">
            <button class="btn btn-primary" onclick="saveModel()">💾 {{ t("save") }}</button>
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
            <button class="btn btn-ghost" style="font-size:11px;padding:2px 8px;color:#f85149;" onclick="if(confirm(window.__t('确定删除')+'{{ m.id }}?')))deleteModel('{{ m.id }}')">✕</button>
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
    <p>{{ t('尚未配置任何模型。点击上方「+ 添加模型」开始。') }}</p>
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
    document.getElementById('formTitle').textContent = window.__t('添加模型');
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
    document.getElementById('formTitle').textContent = window.__t('编辑 ') + id;
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
    if (!body.id || !body.provider) { alert(window.__t('ID和提供商为必填')); return; }
    if (!body.key && !body.base_url) { alert(window.__t('请填写API Key或Base URL')); return; }
    
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
        else { alert(window.__t('失败: ') + (data.detail||data.message||JSON.stringify(data))); }
    } catch(e) { alert(window.__t('网络错误: ') + e.message); }
}
async function deleteModel(id) {
    try {
        var res = await fetch('/api/models/' + id, {method: 'DELETE'});
        if (res.ok) location.reload();
        else { var d = await res.json(); alert(window.__t('失败: ') + (d.detail||'')); }
    } catch(e) { alert(window.__t('错误: ') + e.message); }
}
async function setDefault(id) {
    try {
        var res = await fetch('/api/models/' + id + '/default', {method: 'PATCH'});
        if (res.ok) location.reload();
        else { var d = await res.json(); alert(window.__t('失败: ') + (d.detail||'')); }
    } catch(e) { alert(window.__t('错误: ') + e.message); }
}
async function cleanUnconfigured() {
    if (!confirm(window.__t('确定删除所有未配置Key的模型吗？此操作不可撤销。'))) return;
    try {
        var res = await fetch('/api/models/clean-unconfigured', {method: 'POST'});
        var d = await res.json();
        alert(window.__t('已清理 ') + (d.deleted || 0) + window.__t(' 个未配置模型'));
        location.reload();
    } catch(e) { alert(window.__t('错误: ') + e.message); }
}
function configureModel(id) {
    showAddForm();
    document.getElementById('fid').value = id;
    document.getElementById('fid').disabled = false;
    document.getElementById('editModelId').value = id;
    document.getElementById('formTitle').textContent = window.__t('配置 API Key — ') + id;
    document.getElementById('fkey').focus();
}
async function testModel(id) {
    var tr = document.querySelector('tr[data-id="' + id + '"]');
    if (tr) tr.style.background = '#1a2a1a';
    try {
        var res = await fetch('/api/models/' + id + '/test', {method: 'POST'});
        var d = await res.json();
        if (d.status === 'ok') alert('✅ ' + id + window.__t(' 连接成功'));
        else alert('❌ ' + id + ': ' + (d.message||'失败'));
    } catch(e) { alert(window.__t('错误: ') + e.message); }
    if (tr) tr.style.background = '';
}
async function testFromForm() {
    var id = document.getElementById('fid').value.trim();
    if (!id) { alert(window.__t('请先输入模型ID')); return; }
    document.getElementById('testResult').innerHTML = window.__t('⏳ 测试中...');
    try {
        var res = await fetch('/api/models/' + id + '/test', {method: 'POST'});
        var d = await res.json();
        document.getElementById('testResult').innerHTML = d.status === 'ok' 
            ? '<span style="color:#22c55e;">✅ ' + d.message + '</span>'
            : '<span style="color:#f85149;">❌ ' + (d.message||'失败') + '</span>';
    } catch(e) { document.getElementById('testResult').innerHTML = window.__t('<span style="color:#f85149;">错误: ') + e.message + '</span>'; }
}
</script>
{% endblock %}"""

_TEMPLATES["desktop.html"] = r"""<!DOCTYPE html>
<html lang="{{ __lang }}" dir="{{ 'rtl' if __lang == 'ar' else 'ltr' }}">
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
.topbar .logo{font-size:16px;font-weight:700;color:var(--accent);white-space:nowrap;display:flex;align-items:center;gap:6px;}
.topbar .logo .v{font-size:11px;color:var(--muted);font-weight:400;}
.topbar .topbar-logo-img{width:22px;height:22px;}
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
  <span class="logo"><img src="/static/logo.svg" class="topbar-logo-img"> meshctx <span class="v">Desktop v2.15</span></span>
  <span class="status-dot" id="sysDot" title="系统状态"></span>
  <span class="live-indicator" id="liveTag"></span>
  <span class="spacer"></span>
  <form onsubmit="quickAsk(event)" style="display:flex;gap:4px;align-items:center;">
    <input type="text" id="quickInput" placeholder="{{ t('快速提问...') }}" aria-label="{{ t('快速提问') }}" style="background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:11px;width:140px;font-family:inherit;">
    <button type="submit" style="background:var(--accent);color:#000;border:none;border-radius:6px;padding:4px 8px;cursor:pointer;font-size:11px;font-weight:600;">发送</button>
  </form>
  <button onclick="toggleTheme()" title="切换明暗主题" style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:4px 8px;cursor:pointer;font-size:14px;" id="themeBtn">🌓</button>
  <a href="/ui/download" title="下载Windows客户端" style="text-decoration:none;font-size:13px;padding:4px 6px;">💻</a>
  <select id="quickModel" onchange="switchQuickModel()" title="快速切换模型">
    <option value="">{{ t("loading") }}...</option>
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
        <h2>{{ t('📋 最近任务') }}</h2>
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
        <h2>{{ t('⚙ 系统资源') }}</h2>
        <div id="sysResources" style="display:flex;gap:12px;flex-wrap:wrap;"></div>
      </div>
      <div class="card">
        <h2>{{ t('❤️ 插件健康') }}</h2>
        <div class="plugin-grid" id="pluginHealth"></div>
      </div>
      <div class="card">
        <h2>{{ t('🩺 自愈链路') }}</h2>
        <div class="heal-chain" id="healChain"></div>
      </div>
      <div class="card">
        <h2>{{ t('🔧 模型就绪状态') }}</h2>
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
        <h2>{{ t('⚡ 快捷操作') }}</h2>
        <div style="display:flex;flex-wrap:wrap;gap:6px;">
          <button class="action-btn start-btn" onclick="quickSearch()" style="font-size:11px;">🔍 网页搜索</button>
          <button class="action-btn" onclick="document.querySelector('.tab[data-pane=\"sandbox-dt\"]').click()" style="font-size:11px;background:#334155;color:#e2e8f0;">🖥️ 沙箱</button>
          <button class="action-btn" onclick="document.querySelector('.tab[data-pane=\"project-dt\"]').click();refreshProjectIndex()" style="font-size:11px;background:#334155;color:#e2e8f0;">📂 索引</button>
          <button class="action-btn" onclick="document.querySelector('.tab[data-pane=\"brain\"]').click()" style="font-size:11px;background:#334155;color:#e2e8f0;">🧠 脑图</button>
        </div>
      </div>
      <div class="card">
        <h2>{{ t('📜 事件时间线') }}</h2>
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
        <h2>{{ t('💬 会话历史') }}</h2>
        <div style="margin-bottom:8px;">
          <input type="text" id="convSearch" placeholder="{{ t('搜索会话标题...') }}" aria-label="{{ t('搜索会话标题') }}" oninput="searchConversations()" 
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
        <div class="form-group"><label>{{ t('签名密钥 (可选)') }}</label><input id="feishuSecret" type="password" placeholder="{{ t('HMAC签名密钥') }}" style="width:100%;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-size:12px;"></div>
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
           <input id="historySearch" placeholder="{{ t('搜索会话...') }}" aria-label="{{ t('搜索会话') }}" style="flex:1;background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:6px 12px;border-radius:6px;font-size:12px;" onkeyup="renderHistory()">
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
        <h2>{{ t('🧠 元认知状态') }}</h2>
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
      <textarea id="sandboxCode" style="width:100%;height:150px;background:var(--bg);color:var(--green);border:1px solid var(--border);padding:10px;border-radius:4px;font-family:monospace;font-size:13px;resize:vertical;" placeholder="print('Hello MeshCtx!')" aria-label="Code Sandbox"></textarea>
      <div style="margin-top:8px;display:flex;gap:8px;">
        <button class="btn btn-primary" onclick="runSandbox()">▶ 执行</button>
        <button class="btn" style="background:#334155;color:#94a3b8;" onclick="document.getElementById('sandboxCode').value=''">清空</button>
      </div>
      <div id="sandboxResult" style="margin-top:12px;background:#0f172a;border:1px solid var(--border);border-radius:6px;padding:12px;font-family:monospace;font-size:12px;white-space:pre-wrap;max-height:400px;overflow-y:auto;display:none;color:#e2e8f0;"></div>
    </div>
  </div>
  <!-- 📂 Project Index v2.8 -->
  <div class="pane" id="pane-project-dt">
    <div class="pane-inner">
      <h2>📂 Project Indexer <span style="font-size:10px;color:var(--muted);">v2.8</span></h2>
      <p style="color:var(--muted);margin-bottom:12px;">搜索当前项目代码，获取智能上下文</p>
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <input id="projectQuery" style="flex:1;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:8px 12px;border-radius:4px;" placeholder="{{ t('搜索函数/类/文件...') }}" aria-label="{{ t('搜索函数/类/文件') }}">
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
          <input id="winPsCmd" style="flex:1;background:var(--bg);color:var(--fg);border:1px solid var(--border);padding:6px 10px;border-radius:4px;font-family:monospace;font-size:12px;" placeholder="Get-Service | Where-Object {$_.Status -eq 'Running'}" aria-label="PowerShell Command">
          <button class="btn btn-primary" onclick="winExec()">▶ 执行</button>
        </div>
        <div id="winPsResult" style="background:#0f172a;border:1px solid var(--border);border-radius:6px;padding:10px;font-family:monospace;font-size:11px;white-space:pre-wrap;max-height:300px;overflow-y:auto;display:none;color:#e2e8f0;"></div>
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
    el.innerHTML = window.__t('<span style=\"color:var(--muted);font-size:11px;\">索引未就绪</span>');
  });
}

// ═══ Quick Actions v2.9 ═══
function quickSearch(){
  var q = prompt(window.__t('🔍 网页搜索:'));
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
  if(!cmd){alert(window.__t('请输入PowerShell命令'));return;}
  var el = document.getElementById('winPsResult');
  el.style.display = 'block';
  el.style.color = '#94a3b8';
  el.textContent = window.__t('⏳ 执行中...');
  fetch('/api/win/execute', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({command:cmd, timeout:30})
  }).then(function(r){return r.json()}).then(function(d){
    var out = (d.stdout||'') + '\n' + (d.stderr?'[STDERR] '+d.stderr+'\n':'');
    out += '[Exit: '+d.exit_code+' | '+d.duration_ms+'ms]';
    el.textContent = out;
    el.style.color = d.success ? '#22c55e' : '#fca5a5';
  }).catch(function(e){
    el.textContent = window.__t('失败: ')+e.message;
    el.style.color = '#fca5a5';
  });
}
function winLoadServices(){
  var el = document.getElementById('winContent');
  el.innerHTML = window.__t('<span style="color:var(--muted);">⏳ 加载服务列表...</span>');
  fetch('/api/win/services').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>{{ t('🔧 Windows 服务') }}</h3><div style="max-height:400px;overflow-y:auto;">';
    (d.services||[]).forEach(function(s){
      var color = s.status==='Running'?'#22c55e':s.status==='Stopped'?'#fca5a5':'#f59e0b';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px;">'+
        '<span><span style="color:'+color+';font-weight:600;">'+s.status+'</span> '+s.name+'</span>'+
        '<span style="color:var(--muted);">'+s.display_name+'</span></div>';
    });
    html += '</div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML=window.__t('<span style="color:#fca5a5;">加载失败: ')+e.message+'</span>';});
}
function winLoadProcesses(){
  var el = document.getElementById('winContent');
  el.innerHTML = window.__t('<span style="color:var(--muted);">⏳ 加载进程列表...</span>');
  fetch('/api/win/processes').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>{{ t('📊 进程 Top 30') }}</h3><div style="max-height:400px;overflow-y:auto;">';
    html += '<table style="width:100%;font-size:11px;border-collapse:collapse;"><tr style="color:var(--muted);"><th style="text-align:left;">PID</th><th style="text-align:left;">名称</th><th>CPU</th><th>{{ t('内存') }}</th></tr>';
    (d.processes||[]).forEach(function(p){
      html += '<tr style="border-bottom:1px solid var(--border);">'+
        '<td>'+p.pid+'</td><td>'+p.name+'</td>'+
        '<td style="text-align:right;">'+p.cpu+'</td>'+
        '<td style="text-align:right;">'+p.memory_mb+'MB</td></tr>';
    });
    html += '</table></div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML=window.__t('<span style="color:#fca5a5;">加载失败: ')+e.message+'</span>';});
}
function winLoadSystem(){
  var el = document.getElementById('winContent');
  fetch('/api/win/system').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>{{ t('💻 系统信息') }}</h3>';
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:12px;">';
    for(var k in d){
      html += '<div style="color:var(--muted);">'+k+'</div><div style="font-weight:600;">'+d[k]+'</div>';
    }
    html += '</div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML=window.__t('<span style="color:#fca5a5;">加载失败: ')+e.message+'</span>';});
}
function winLoadSoftware(){
  var el = document.getElementById('winContent');
  el.innerHTML = window.__t('<span style="color:var(--muted);">⏳ 扫描已安装软件...</span>');
  fetch('/api/win/software').then(function(r){return r.json()}).then(function(d){
    var html = '<div class="card"><h3>{{ t('📦 已安装软件') }}</h3><div style="max-height:400px;overflow-y:auto;">';
    (d.software||[]).slice(0,30).forEach(function(s){
      html += '<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border);">'+
        '<span style="font-weight:600;">'+s.name+'</span>'+
        (s.version?' <span style="color:var(--muted);">v'+s.version+'</span>':'')+
        (s.publisher?' <span style="color:var(--muted);font-size:10px;">- '+s.publisher+'</span>':'')+
        '</div>';
    });
    html += '</div></div>';
    el.innerHTML = html;
  }).catch(function(e){el.innerHTML=window.__t('<span style="color:#fca5a5;">加载失败: ')+e.message+'</span>';});
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
    el.innerHTML = window.__t('<span style="color:var(--muted);font-size:11px;">监控未就绪</span>');
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
    el.innerHTML = window.__t('<span style="color:var(--muted);">记忆系统未就绪</span>');
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
    document.getElementById('liveTag').textContent = window.__t('⚠ 离线');
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
  document.getElementById('oodaRefreshTag').textContent = window.__t('循环#')+(oo.cycle_count||0)+' · '+curPhase;
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
      taskHTML += '<div class="row task-row" data-task-id="'+tk.id+'" onclick="toggleTask(this,\''+tk.id+'\')" style="cursor:pointer"><span style="color:var(--muted);font-family:monospace;font-size:10px;">'+tk.id+'</span><span style="flex:1">'+(tk.description||tk.id||'')+'</span><span class="tag '+tagByStatus(tk.status)+'" id="task-status-'+tk.id+'">'+(tk.status||'pending')+'</span></div>';
    }
  } else {
    taskHTML = '<div class="empty">😴 暂无任务记录</div>';
  }
  document.getElementById('agentTaskList').innerHTML = taskHTML;
}

function toggleTask(el, taskId) {
  var statusEl = document.getElementById('task-status-'+taskId);
  if (!statusEl || statusEl.textContent === 'done' || statusEl.textContent === 'completed') return;
  fetch('/api/tasks/'+taskId+'/complete', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    if (d.status === 'ok') {
      statusEl.textContent = d.new_status || 'done';
      statusEl.className = 'tag tag-ok';
      el.style.opacity = '0.6';
      el.style.textDecoration = 'line-through';
    }
  }).catch(function(e){ console.error('Task complete error:', e); });
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
      var pn = pNames[i], p = plugins[pn] || {};
      var pName = pn || 'unknown';
      var pStatus = p.status || 'unknown';
      pHtml += '<div class="plugin-card"><div class="row"><span class="dot '+colorByStatus(pStatus).replace('v-','')+'"></span><span class="pname">'+pName+'</span></div>'+
        '<div class="pmeta">状态: <span class="tag '+tagByStatus(pStatus)+'">'+pStatus+'</span> · 失败: '+(p.failures||0)+' · 重启: '+(p.restarts||0)+'</div>'+
        '<div class="pmeta">心跳: '+((p.heartbeat_age||0)>10?'⚠ '+p.heartbeat_age+'s':'✓ '+p.heartbeat_age+'s')+' · 熔断: '+(p.circuit||'N/A')+'</div></div>';
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
    document.getElementById('eventTimeline').insertAdjacentHTML('beforebegin', '<div class="card"><h2>{{ t('📈 请求趋势 (30点)') }}</h2>'+chartHTML+'</div>');
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
    document.getElementById('brainMonitor').innerHTML = window.__t('<div class="stat-card" style="grid-column:1/-1;text-align:center;color:var(--muted);">🧠 等待后端连接...</div>');
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
    alert(d.status==='ok'?'✅ '+name+window.__t(' 安装成功!'):d.message||'失败');
    renderPlugins();
  });
}
function uninstallPlugin(name){
  if(!confirm(window.__t('卸载 ')+name+'?')) return;
  fetch('/api/plugins/uninstall/'+name, {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    alert(d.status==='ok'?'🗑 '+name+window.__t(' 已卸载'):d.message);
    renderPlugins();
  });
}

// ═══ Agent控制 ═══
function controlAgent(action){
  var btnStart = document.getElementById('btnAgentStart');
  var btnStop = document.getElementById('btnAgentStop');
  if(action==='start'){
    btnStart.textContent = window.__t('⏳ 启动中...'); btnStart.disabled = true;
    fetch('/agent/start', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
      btnStart.style.display = 'none'; btnStop.style.display = '';
      btnStart.textContent = window.__t('▶ 启动'); btnStart.disabled = false;
      fetchSummary();
    }).catch(function(e){
      btnStart.textContent = window.__t('▶ 启动'); btnStart.disabled = false;
      console.error(e);
    });
  } else if(action==='stop'){
    btnStop.textContent = window.__t('⏳ 停止中...'); btnStop.disabled = true;
    fetch('/agent/stop', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
      btnStop.style.display = 'none'; btnStart.style.display = '';
      btnStop.textContent = window.__t('⏹ 停止'); btnStop.disabled = false;
      fetchSummary();
    }).catch(function(e){
      btnStop.textContent = window.__t('⏹ 停止'); btnStop.disabled = false;
      console.error(e);
    });
  }
}

// ═══ 预测器训练 ═══
function trainPredictor(){
  var btn = event.target;
  btn.textContent = window.__t('⏳ 训练中...'); btn.disabled = true;
  fetch('/predictor/learn', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    btn.textContent = window.__t('✅ 完成');
    setTimeout(function(){ btn.textContent = window.__t('🧠 训练'); btn.disabled = false; fetchSummary(); }, 1500);
  }).catch(function(e){
    btn.textContent = window.__t('❌ 失败');
    setTimeout(function(){ btn.textContent = window.__t('🧠 训练'); btn.disabled = false; }, 2000);
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
  if(saved==='light') document.body.setAttribute('data-theme','light');else document.body.setAttribute('data-theme','dark');
  if(saved==='light') document.getElementById('themeBtn').textContent = '☀️';
  // 监听系统主题变化
  if(window.matchMedia){
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e){
      var current = localStorage.getItem('meshctx_theme');
      if(!current || current === 'auto'){
        document.body.setAttribute('data-theme', e.matches ? 'dark' : 'light');
      }
    });
  }
})();
function toggleTheme(){
  var body = document.body;
  var current = body.getAttribute('data-theme') || 'dark';
  var next = current === 'dark' ? 'light' : 'dark';
  body.setAttribute('data-theme', next);
  localStorage.setItem('meshctx_theme', next);
  var btn = document.getElementById('themeToggle');
  if (btn) btn.textContent = next === 'light' ? '☀️' : '🌙';
  var btn2 = document.getElementById('themeBtn');
  if (btn2) btn2.textContent = next === 'light' ? '☀️' : '🌙';
}

// ═══ 基准测试 v1.5.6 ═══
function runBenchmark(){
  var btn = event.target;
  var panel = document.getElementById('benchPanel');
  btn.textContent = window.__t('⏳ 测试中...'); btn.disabled = true;
  panel.innerHTML = window.__t('<div class=stat><span>⏳</span><span>正在运行基准测试...</span></div>');
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
    btn.textContent = window.__t('⚡ 基准测试'); btn.disabled = false;
  }).catch(function(e){
    panel.innerHTML = window.__t('<div class=stat><span>❌</span><span>请求失败</span></div>');
    btn.textContent = window.__t('⚡ 基准测试'); btn.disabled = false;
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
    live.textContent = window.__t('✅ 已切换: ') + d.current;
    setTimeout(function(){ live.textContent = 'LIVE'; }, 3000);
    fetchModels(); // 刷新选中状态
  }).catch(function(e){
    alert(window.__t('切换失败: ') + e);
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
  }).catch(function(e){ document.getElementById('providerList').innerHTML = window.__t('<span class=error-block>加载失败</span>'); });
  // v1.5.17: 同时加载MCP服务器
  loadMcpServers();
}

function showKeyInput(pid){
  var name = {'deepseek':'DeepSeek','openai':'OpenAI','anthropic':'Anthropic','bailian':'阿里百炼'}[pid]||pid;
  var key = prompt(window.__t('输入 ')+name+window.__t(' API Key (留空删除):'));
  if(key===null) return;
  fetch('/api/providers', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({provider:pid, key:key})
  }).then(function(r){return r.json()}).then(function(d){
    renderProviders();
    fetchModels(); // 刷新模型就绪状态
    fetchSummary();
  }).catch(function(e){ alert(window.__t('保存失败: ')+e); });
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
    setTimeout(function(){ btn.textContent = window.__t('🔍 测试'); btn.disabled = false; btn.style.color = ''; renderProviders(); }, 2000);
  }).catch(function(e){
    btn.textContent = window.__t('⚠ 错误'); btn.disabled = false;
    setTimeout(function(){ btn.textContent = window.__t('🔍 测试'); renderProviders(); }, 2000);
  });
}

function deleteProvider(pid){
  if(!confirm(window.__t('确认删除 ')+pid+window.__t(' 的API Key?'))) return;
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
      el.innerHTML = window.__t('<div style="color:var(--muted);text-align:center;padding:20px;">暂无存档会话<br><span style="font-size:11px;">Chat对话完成后自动存档</span></div>');
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
    if(el) el.innerHTML = window.__t('<div style="color:#fca5a5;">加载失败: ')+e.message+'</div>';
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
    html += '<button onclick="document.getElementById(\'sessionDetail\').innerHTML=\'\window.__t('" style="margin-top:10px;background:#334155;color:#e2e8f0;border:none;border-radius:6px;padding:6px 16px;cursor:pointer;">关闭</button>');
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
      selector.innerHTML = window.__t('<option value="">(自动检测)</option>');
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
  }).catch(function(e){ statusEl.innerHTML = window.__t('<span class=error-block>加载失败: ')+e.message+'</span>'; });
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
    el.innerHTML += window.__t('<br><span style="color:#22c55e;">✅ 模板已复制! 创建 .meshctx.md 后刷新</span>');
  });
}
  }).catch(function(e){ document.getElementById('meshctxMdStatus').innerHTML = window.__t('<span class=error-block>加载失败</span>'); });
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
  }).catch(function(e){ document.getElementById('convHistoryList').innerHTML = window.__t('<span class=error-block>加载失败</span>'); });
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
  }).catch(function(e){ document.getElementById('mcpServerList').innerHTML = window.__t('<span class=error-block>加载失败</span>'); });
}

function showAddMcpForm(){
  var name = prompt(window.__t('MCP服务器名称:'));
  if(!name) return;
  var command = prompt(window.__t('命令 (如 npx 或 python):'));
  if(!command) return;
  var argsStr = prompt(window.__t('参数 (空格分隔, 可选):'),'');
  var args = argsStr ? argsStr.trim().split(/\\s+/) : [];
  
  fetch('/api/mcp-servers', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name, command:command, args:args})
  }).then(function(r){return r.json()}).then(function(d){
    if(d.success) loadMcpServers();
    else alert(window.__t('添加失败: ')+JSON.stringify(d));
  }).catch(function(e){ alert(window.__t('请求失败: ')+e); });
}

function toggleMcp(sid){
  fetch('/api/mcp-servers/'+sid+'/toggle', {method:'POST'}).then(function(r){return r.json()}).then(function(d){
    loadMcpServers();
  });
}

function deleteMcp(sid){
  if(!confirm(window.__t('确认删除此MCP服务器?'))) return;
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
  if(!url){ alert(window.__t('请输入Webhook URL')); return; }
  localStorage.setItem('meshctx_feishu_url', url);
  localStorage.setItem('meshctx_feishu_secret', secret);
  document.getElementById('feishuStatus').innerHTML = window.__t('<span style="color:#22c55e;">✅ 已保存</span>');
  setTimeout(function(){ document.getElementById('feishuStatus').innerHTML = ''; }, 2000);
}
function testFeishu(){
  var url = document.getElementById('feishuUrl').value.trim();
  var secret = document.getElementById('feishuSecret').value.trim();
  if(!url){ alert(window.__t('请先输入Webhook URL')); return; }
  var statusEl = document.getElementById('feishuStatus');
  statusEl.innerHTML = window.__t('<span style="color:#94a3b8;">⏳ 发送测试消息...</span>');
  fetch('/api/feishu/test', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({webhook_url:url, secret:secret})
  }).then(function(r){return r.json()}).then(function(d){
    if(d.success){
      statusEl.innerHTML = window.__t('<span style="color:#22c55e;">✅ 测试成功！请查看飞书群消息</span>');
      saveFeishu();
    }else{
      statusEl.innerHTML = window.__t('<span style="color:#fca5a5;">❌ 发送失败，请检查Webhook地址</span>');
    }
  }).catch(function(e){
    statusEl.innerHTML = window.__t('<span style="color:#fca5a5;">❌ 请求失败: ')+e.message+'</span>';
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
  document.getElementById('multiNotifyStatus').innerHTML = window.__t('<span style="color:#22c55e;">✅ 已保存</span>');
  setTimeout(function(){ document.getElementById('multiNotifyStatus').innerHTML = ''; }, 2000);
}
function testMultiNotify(){
  var el = document.getElementById('multiNotifyStatus');
  el.innerHTML = window.__t('<span style="color:#94a3b8;">⏳ 发送中...</span>');
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
    if(d.success) el.innerHTML = window.__t('<span style="color:#22c55e;">✅ 广播成功: ')+JSON.stringify(d.results)+'</span>';
    else el.innerHTML = window.__t('<span style="color:#fca5a5;">❌ 发送失败</span>');
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
  if(!code.trim()){ alert(window.__t('请输入代码')); return; }
  var resultEl = document.getElementById('sandboxResult');
  resultEl.style.display = 'block';
  resultEl.style.color = '#94a3b8';
  resultEl.textContent = window.__t('⏳ 执行中...\n');
  
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
                resultEl.textContent += window.__t('\n[退出码: ')+d.exit_code+window.__t(' | 耗时: ')+d.duration_ms+'ms | '+d.method+']';
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
    resultEl.textContent = window.__t('执行失败: ') + e.message;
    resultEl.style.color = '#fca5a5';
  });
}

// ═══ Project Indexer v2.8 ═══
function searchProject(){
  var q = document.getElementById('projectQuery').value.trim();
  if(!q){alert(window.__t('请输入搜索词'));return;}
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
  statsEl.textContent = window.__t('⏳ 扫描中...');
  fetch('/api/project/index').then(function(r){return r.json()}).then(function(d){
    var langs = [];
    for(var l in d.languages) langs.push(l+':'+d.languages[l]);
    statsEl.innerHTML = '📊 <b>'+d.total_files+window.__t('</b> 文件 · <b>')+(d.total_size/1024/1024).toFixed(1)+'MB</b> · <b>'+d.total_lines.toLocaleString()+window.__t('</b> 行 · ')+langs.join(', ');
    document.getElementById('projectResults').innerHTML = '';
  }).catch(function(e){
    statsEl.textContent = window.__t('❌ 扫描失败: ') + e.message;
  });
}

</script>
</body>
</html>"""


# ── DictLoader 初始化 ───────────────────────────────────────────
from src.i18n import t as i18n_t, get_lang as i18n_get_lang, TRANSLATIONS as i18n_translations, LANGUAGES, LANGUAGE_CODES
# 内嵌模板(DictLoader)默认优先: 它是运行时权威版本, 且 PyInstaller 打包时只有它。
# 若 FileSystemLoader 在前, 磁盘上的旧 templates/*.html 会覆盖内嵌模板,
# 导致 web_ui.py 里的修复(如 i18n)不生效。(2026-08-16 实测踩坑)
# 设置 MESHCTX_CUSTOM_TEMPLATES=1 可恢复 FileSystemLoader 优先(用户自定义模板能力)。
_CUSTOM_TEMPLATES = os.environ.get('MESHCTX_CUSTOM_TEMPLATES', '').strip() in ('1', 'true', 'yes')
if _CUSTOM_TEMPLATES:
    _template_loaders = [
        FileSystemLoader(os.path.join(os.path.dirname(__file__), '..', 'templates')),
        DictLoader(_TEMPLATES),
    ]
else:
    _template_loaders = [
        DictLoader(_TEMPLATES),
        FileSystemLoader(os.path.join(os.path.dirname(__file__), '..', 'templates')),
    ]
_jinja_env = Environment(loader=ChoiceLoader(_template_loaders), autoescape=False)
_jinja_env.globals['t'] = i18n_t
_jinja_env.globals['lang'] = i18n_get_lang

# v3.115.16: 内存优化 — 缓存 i18n JSON 序列化结果 (避免每请求 json.dumps 73KB)
_i18n_json_cache = {}

def _get_i18n_json(lang: str) -> str:
    """获取语言翻译 JSON 字符串（缓存，避免每请求序列化）"""
    if lang not in _i18n_json_cache:
        _i18n_json_cache[lang] = __import__('json').dumps(
            i18n_translations.get(lang, i18n_translations.get('en', {})),
            ensure_ascii=False
        )
    return _i18n_json_cache[lang]

def _get_i18n_all_json() -> str:
    """QA6: 注入全部语言到主 SPA，支持 switchLang 无刷新切换"""
    if '_all' not in _i18n_json_cache:
        all_i18n = {}
        for lc in LANGUAGE_CODES:
            all_i18n[lc] = i18n_translations.get(lc, {})
        _i18n_json_cache['_all'] = __import__('json').dumps(all_i18n, ensure_ascii=False)
    return _i18n_json_cache['_all']

def _render(template_name: str, context: dict, request = None) -> HTMLResponse:
    """渲染 Jinja2 模板（从内嵌 DictLoader），自动检测浏览器语言"""
    lang = i18n_get_lang(request)
    # 绑定 t() 到检测到的语言（避免全局状态竞争）
    def _scoped_t(key: str) -> str:
        return i18n_translations.get(lang, i18n_translations.get('en', {})).get(key, i18n_translations.get('en', {}).get(key, key))
    context['t'] = _scoped_t
    context['__i18n_json'] = _get_i18n_json(lang)
    context['__i18n_all_json'] = _get_i18n_all_json()
    context['__lang'] = lang
    # Inject configurable local model hosts (BUG-005 fix)
    import os as _os
    context.setdefault('ollama_host', _os.environ.get('MESHCTX_OLLAMA_HOST', 'localhost'))
    context.setdefault('vllm_host', _os.environ.get('MESHCTX_VLLM_HOST', 'localhost'))
    context.setdefault('localai_host', _os.environ.get('MESHCTX_LOCALAI_HOST', 'localhost'))
    # 注入支持的语言列表供 JS 使用（缓存）
    if '_langs_json' not in _i18n_json_cache:
        _i18n_json_cache['_langs_json'] = __import__('json').dumps(
            i18n_translations.get('en', {}).get('__available_langs__',
                [{"code": lang["code"], "name": lang["name"], "native": lang["native"]} for lang in LANGUAGES])
        )
    context['__languages'] = _i18n_json_cache['_langs_json']
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
    if s is None:
        return ""
    if len(s) <= n:
        return s
    return s[:n] + "..."


# ── 仪表板首页 ───────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    engine = _engine(request)
    projects = engine.list_projects()

    # v3.115.16: N+1 optimization — single-pass grouping
    convs_by_pid = {}
    for c in engine.conversations.values():
        pid = getattr(c, 'project_id', None)
        if pid:
            convs_by_pid.setdefault(pid, []).append(c)
    mems_by_pid = {}
    for m in engine.memories.values():
        pid = getattr(m, 'project_id', None)
        if pid:
            mems_by_pid.setdefault(pid, []).append(m)
    sessions_by_pid = {}
    for s in getattr(engine, 'agent_sessions', {}).values():
        pid = getattr(s, 'project_id', None)
        if pid:
            sessions_by_pid.setdefault(pid, []).append(s)

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
        convs = convs_by_pid.get(p.id, [])
        total_conversations += len(convs)
        memories = mems_by_pid.get(p.id, [])
        total_memories += len(memories)
        sessions = sessions_by_pid.get(p.id, [])
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
        "truncate": _truncate,
    }, request)


# ── 项目管理 ─────────────────────────────────────────────────

@router.get("/projects", response_class=HTMLResponse)
async def project_list(request: Request):
    engine = _engine(request)
    projects = engine.list_projects()

    # v3.115.16: N+1 optimization — single-pass grouping instead of per-project scans
    conversations_by_project = {}
    for c in engine.conversations.values():
        pid = getattr(c, 'project_id', None)
        if pid:
            conversations_by_project.setdefault(pid, []).append(c)
    
    memories_by_project = {}
    for m in engine.memories.values():
        pid = getattr(m, 'project_id', None)
        if pid:
            memories_by_project.setdefault(pid, []).append(m)

    enriched = []
    for p in projects:
        convs = conversations_by_project.get(p.id, [])
        mems = memories_by_project.get(p.id, [])
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
    }, request)


@router.get("/projects/create")
async def create_project_page(request: Request):
    """redirect GET to projects list (creation is inline)"""
    return RedirectResponse(url="/ui/projects", status_code=303)


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
        return HTMLResponse("<h2>{{ t('项目不存在') }}</h2>", status_code=404)

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
    }, request)


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
        return HTMLResponse("<h2>{{ t('会话不存在') }}</h2>", status_code=404)

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
    }, request)


# ── 记忆浏览 ─────────────────────────────────────────────────

class _OldMemoryAdapter:
    """适配旧 Memory 模型（key/value）到模板期望的 content 属性"""
    def __init__(self, m):
        self._m = m
    @property
    def id(self): return self._m.id
    @property
    def content(self): return getattr(self._m, 'content', None) or getattr(self._m, 'value', '')
    @property
    def importance(self): return self._m.importance
    @property
    def created_at(self): return self._m.created_at
    @property
    def project_id(self): return getattr(self._m, 'project_id', '')


class _V2MemoryAdapter:
    """适配 memory_v2 MemoryEntry 到模板期望的接口"""
    def __init__(self, entry):
        self._e = entry
    @property
    def id(self): return self._e.id
    @property
    def content(self): return self._e.content
    @property
    def importance(self): return self._e.importance
    @property
    def created_at(self): return self._e.created_at
    @property
    def project_id(self): return ''


@router.get("/memories", response_class=HTMLResponse)
async def memories_overview(request: Request):
    """所有项目的记忆总览（旧引擎 + memory_v2）"""
    engine = _engine(request)
    projects = engine.list_projects()
    all_memories = []

    # 旧引擎记忆
    for p in projects:
        mems = engine.get_memories(p.id)
        for m in mems:
            all_memories.append({
                "memory": _OldMemoryAdapter(m),
                "project_name": p.name,
            })

    # memory_v2 记忆
    try:
        from src.core.memory_v2 import get_memory_manager
        mgr = get_memory_manager()
        for entry in mgr.list_by_type():
            all_memories.append({
                "memory": _V2MemoryAdapter(entry),
                "project_name": "🧠 Memory V2",
            })
    except Exception:
        logger.debug("Suppressed except Exception:: {}", exc_info=True)

    all_memories.sort(key=lambda x: x["memory"].importance, reverse=True)

    return _render("memories.html", {
        "request": request,
        "title": "记忆浏览",
        "memories": all_memories,
        "projects": projects,
        "format_dt": _format_dt,
        "truncate": _truncate,
        "continuity_color": _continuity_color,
    }, request)


@router.post("/memories/{memory_id}/delete")
async def delete_memory_ui(request: Request, memory_id: str):
    # 先尝试旧引擎删除
    engine = _engine(request)
    deleted = engine.delete_memory(memory_id)
    # 再尝试 memory_v2 删除
    if not deleted:
        try:
            from src.core.memory_v2 import get_memory_manager
            mgr = get_memory_manager()
            mgr.remove(memory_id)
        except Exception:
            logger.debug("Suppressed except Exception:: {}", exc_info=True)
    return RedirectResponse(url="/ui/memories", status_code=303)


# ── 记忆仪表板 (搜索+添加+图谱+统计) ──────────────────────

@router.get("/memory", response_class=HTMLResponse)
async def memory_dashboard(request: Request):
    """记忆仪表板: 搜索、添加、知识图谱可视化、统计"""
    return _render("memories.html", {
        "request": request,
        "title": "记忆仪表板",
    }, request)


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
    }, request)

# ── Chat 页面 ───────────────────────────────────────────

@router.get("/desktop", response_class=HTMLResponse)
async def desktop_page(request: Request):
    return _render("desktop.html", {"request": request, "title": "Desktop"}, request)

@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    # 检测当前 profile
    import os as _os, yaml as _yaml
    profile = _os.environ.get("MESHCTX_PROFILE", "").strip()
    if not profile:
        try:
            cfg_path = _os.environ.get("MESHCTX_CONFIG",
                str(__import__('pathlib').Path.home() / ".meshctx" / "config.yaml"))
            with open(cfg_path) as f:
                cfg = _yaml.safe_load(f) or {}
            p = cfg.get("profile", {})
            if isinstance(p, dict):
                profile = p.get("active", "")
            elif p:
                profile = str(p)
        except Exception:
            profile = ""
    if profile == "default":
        profile = ""
    return _render("chat.html", {"request": request, "title": "Chat", "profile": profile}, request)

def _build_model_context(request: Request):
    """构建模型配置页上下文（flash + configured 列表 + 折叠状态）。
    setup_page(向导) 与 models_page(模型管理) 复用同一逻辑。
    """
    flash = ""
    if request.query_params.get("saved") == "1":
        flash = "success"
    elif request.query_params.get("error") == "1":
        flash = "error"
    elif request.query_params.get("deleted") == "1":
        flash = "deleted"
    
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
        
        # 也检查 provider_config.json 补全遗漏的配置
        pcfg_path = Path(__file__).resolve().parent.parent / "provider_config.json"
        pcfg_keys = {}
        if pcfg_path.exists():
            try:
                import json as _json2
                pcfg_data = _json2.loads(pcfg_path.read_text())
                for pid, pinfo in pcfg_data.items():
                    if pinfo.get("key"):
                        pcfg_keys[pid] = pinfo["key"]
            except:
                logger.debug("Suppressed except:: {}", exc_info=True)
        # 对于 provider_config 中有 key 但 config.yaml 中无 entry 的 provider，
        # 自动补全该 provider 下所有内置模型的 entries
        for pid, pkey in pcfg_keys.items():
            for mid, info in BUILTIN_MODELS.items():
                if info.get("provider") == pid and mid not in entries:
                    entries[mid] = {
                        "key": pkey,
                        "provider": pid,
                        "model": info.get("model", ""),
                        "base_url": info.get("base_url", ""),
                    }
        
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
                    if raw_key.startswith("b64:"): entry["key_masked"] = "b64:****"
                    else: entry["key_masked"] = raw_key[:6] + "****" + raw_key[-4:] if len(raw_key) > 10 else "****"
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
        logger.debug("Suppressed except:: {}", exc_info=True)
    
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
    
    return flash, configured, has_more, unconfigured_count


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    flash, configured, has_more, unconfigured_count = _build_model_context(request)
    return _render("setup.html", {
        "request": request, "title": "Setup",
        "flash": flash, "configured": configured,
        "has_more_unconfigured": has_more,
        "total_unconfigured": unconfigured_count,
    }, request)


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
        logger.debug("Suppressed except:: {}", exc_info=True)
    config["models"]["entries"][model_id] = {
        "key": encrypted_key,
        "model": actual_model,
        "base_url": actual_url,
    }

    with open(config_path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

    # 设置环境变量立即可用
    os.environ[defaults["key_env"]] = api_key
    
    # 重置模型registry缓存，使新key立即生效
    try:
        from src.model_registry import reset_registry
        reset_registry()
    except:
        logger.debug("Suppressed except:: {}", exc_info=True)

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
    return _render("dashboard_inline.html", {}, request)

# ── v2.18 插件市场 (增强卡片+URL安装+社区推荐) ──────────────────

@router.get("/plugins", response_class=HTMLResponse)
async def plugins_page(request: Request):
    return _render("plugins_inline.html", {}, request)

# ── v1.5.13 下载页面

@router.get("/download", response_class=HTMLResponse)
async def download_page(request: Request):
    html = r"""{% extends "base.html" %}
{% block content %}
<h2>{{ t("install_title") }}</h2>
<div class="card" style="margin-top:16px;">
  <h3>🍎 macOS</h3>
  <p style="color:var(--muted);">macOS 15+ · Apple Silicon / Intel</p>
  <details open style="margin-top:8px;">
    <summary style="cursor:pointer;font-weight:600;color:var(--cyan);">方式1: curl 一键安装</summary>
    <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);margin-top:8px;">curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install-mac.sh | bash</pre>
  </details>
  <details style="margin-top:8px;">
    <summary style="cursor:pointer;font-weight:600;color:var(--cyan);">方式2: Homebrew</summary>
    <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);margin-top:8px;">brew tap LucyAndLuna2023/meshctx
brew install meshctx</pre>
  </details>
  <details style="margin-top:8px;">
    <summary style="cursor:pointer;font-weight:600;color:var(--cyan);">方式3: DMG 安装包</summary>
    <div style="text-align:center;padding:12px;">
      <a class="btn btn-primary" href="https://github.com/LucyAndLuna2023/meshctx/releases/latest/download/meshctx.dmg" style="display:inline-block;text-decoration:none;padding:10px 28px;">⬇ 下载 DMG</a>
      <p style="font-size:11px;color:var(--muted);margin-top:6px;">下载后拖入 Applications 即可</p>
    </div>
  </details>
  <p style="font-size:11px;color:var(--muted);margin-top:8px;">需要 Python 3.10+ · 脚本自动处理依赖</p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>🐧 Linux</h3>
  <p style="color:var(--muted);">{{ t("one_cmd_install_desc") }}</p>
  <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);">curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash</pre>
  <p style="font-size:11px;color:var(--muted);margin-top:8px;">{{ t("install_requirements") }}</p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>{{ t("windows_title") }}</h3>
  <div style="text-align:center;padding:16px;">
    <a class="btn btn-primary" href="https://github.com/LucyAndLuna2023/meshctx/releases/latest/download/meshctx-setup.exe" style="display:inline-block;text-decoration:none;padding:12px 32px;font-size:15px;">{{ t("download_windows_btn") }}</a>
    <p style="font-size:11px;color:var(--muted);margin-top:8px;">v{{ version }} · {{ t("nsis_installer") }} · Win10/11 x64</p>
  </div>
  <details style="margin-top:8px;font-size:12px;">
    <summary style="cursor:pointer;color:var(--muted);">{{ t("cli_install_title") }}</summary>
    <pre style="background:var(--bg);padding:12px;border-radius:6px;color:var(--green);margin-top:8px;">curl -fsSL https://meshctx.com/install.sh | bash</pre>
  </details>
</div>
<div class="card" style="margin-top:16px;">
  <h3>{{ t("docker_coming_soon") }}</h3>
  <p style="color:var(--muted);">docker pull meshctx/meshctx:latest</p>
</div>
<div class="card" style="margin-top:16px;">
  <h3>{{ t("config_docs_title") }}</h3>
  <p>{{ t("supports_info") }} <a href="https://github.com/LucyAndLuna2023/meshctx#-model-configuration" target="_blank">{{ t("view_config_guide") }}</a></p>
  <p style="font-size:12px;color:var(--muted);">{{ t("more_models") }}</p>
</div>
{% endblock %}"""
    _TEMPLATES["download.html"] = html
    return _render("download.html", {"request": request, "title": "Download", "version": __import__("src").__version__}, request)


# ── Chat 页面模板 ────────────────────────────────────────────

_TEMPLATES["chat.html"] = r"""{% extends "base.html" %}
{% block content %}
<style>
.chat-card {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px;
  display: flex; flex-direction: column; height: calc(100vh - 140px); min-height: 400px;
  overflow: hidden;
}
.chat-messages {
  flex: 1; overflow-y: auto; padding: 16px 20px;
  display: flex; flex-direction: column; gap: 12px;
}
.chat-input-area {
  border-top: 1px solid var(--border); padding: 12px 16px;
  display: flex; gap: 8px; align-items: flex-end;
}
.chat-input-area textarea {
  flex: 1; background: var(--bg); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px;
  font-size: 14px; font-family: inherit; resize: none; min-height: 44px; max-height: 150px;
  outline: none; line-height: 1.5;
}
.chat-input-area textarea:focus { border-color: var(--accent); }
.msg { max-width: 80%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.55; word-break: break-word; }
.msg.user { align-self: flex-end; background: var(--accent); color: #fff; border-bottom-right-radius: 4px; }
.msg.assistant { align-self: flex-start; background: var(--surface); color: var(--text); border-bottom-left-radius: 4px; }
.msg pre { background: #0f172a; padding: 10px; border-radius: 6px; overflow-x: auto; margin: 8px 0; font-size: 12px; }
.msg code { font-size: 12px; background: rgba(108,92,231,0.2); padding: 2px 5px; border-radius: 3px; }
.empty-chat { text-align: center; color: var(--muted); padding: 60px 20px; }
.empty-chat h2 { font-size: 24px; margin-bottom: 8px; }
.empty-chat p { font-size: 14px; }
</style>
<div class="chat-card">
  <div class="chat-messages" id="chatMessages">
    <div class="empty-chat">
      <h2>💬 meshctx Chat</h2>
      <p>{{ t('输入消息开始对话') }}</p>
    </div>
  </div>
  <div class="chat-input-area">
    <textarea id="userInput" rows="1" placeholder="{{ t('输入消息... (Enter 发送, Shift+Enter 换行)') }}"
          onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send();}"
          oninput="this.style.height='';this.style.height=Math.min(this.scrollHeight,150)+'px';"></textarea>
    <button onclick="send()" style="background:var(--accent);color:#fff;border:none;border-radius:8px;
          padding:10px 18px;cursor:pointer;font-weight:600;font-size:14px;white-space:nowrap;">{{ t("send") }}</button>
  </div>
</div>
<script>
var _convId = null;
var _projectId = null;
var _msgContainer = document.getElementById('chatMessages');
var _emptyState = _msgContainer.querySelector('.empty-chat');

function addMessage(role, content) {
  if (_emptyState) { _emptyState.remove(); _emptyState = null; }
  var el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = content;
  _msgContainer.appendChild(el);
  _msgContainer.scrollTop = _msgContainer.scrollHeight;
  _chatLog.push({role: role, content: content});
  _saveChatLog();
  return el;
}

// ── 会话持久化 (修复: 跳转/后退后历史丢失) ──
var _chatTab = localStorage.getItem('meshctx_active_tab') || 'default';
var _chatLog = [];
function _saveChatLog() {
  try { localStorage.setItem('meshctx_chat_' + _chatTab, JSON.stringify(_chatLog)); } catch(e) {}
}
function _restoreChatLog() {
  try {
    var saved = JSON.parse(localStorage.getItem('meshctx_chat_' + _chatTab) || '[]');
    if (!saved.length) return;
    _chatLog = saved;
    saved.forEach(function(m) {
      if (_emptyState) { _emptyState.remove(); _emptyState = null; }
      var el = document.createElement('div');
      el.className = 'msg ' + m.role;
      el.textContent = m.content;
      _msgContainer.appendChild(el);
    });
    _msgContainer.scrollTop = _msgContainer.scrollHeight;
  } catch(e) {}
}
_restoreChatLog();

async function send() {
  var input = document.getElementById('userInput');
  var text = input.value.trim();
  if (!text) return;
  input.value = ''; input.style.height = '';
  addMessage('user', text);
  
  try {
    var res = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        message: text,
        project_id: _projectId || null,
        conversation_id: _convId || null
      })
    });
    var data = await res.json();
    if (data.error) {
      addMessage('assistant', '⚠️ ' + data.error);
    } else {
      if (!_convId) _convId = data.conversation_id;
      if (!_projectId) _projectId = data.project_id;
      addMessage('assistant', data.response || data.content || '(empty response)');
    }
  } catch (err) {
    addMessage('assistant', '⚠️ 网络错误: ' + err.message);
  }
}

// v1.5.9: Desktop快速提问监听
window.addEventListener('message', function(e){
  var d = e.data;
  if(d && d.type === 'meshctx-quick-ask' && d.message){
    document.getElementById('userInput').value = d.message;
    send();
  }
});
</script>
{% endblock %}
"""


# ── 模型列表页面 ────────────────────────────────────────────

_TEMPLATES["models_list.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>{{ t('🤖 模型列表') }}</h2>
<div style="display:flex;gap:12px;margin:16px 0;flex-wrap:wrap;">
    <div class="stat-card"><div class="value" id="totalModels">-</div><div class="label">模型总数</div></div>
    <div class="stat-card"><div class="value" id="configuredModels">-</div><div class="label">{{ t("configured") }}</div></div>
    <div class="stat-card"><div class="value" id="usableModels">-</div><div class="label">{{ t("usable") }}</div></div>
    <div class="stat-card"><div class="value" id="currentModel">-</div><div class="label">{{ t("current_default") }}</div></div>
</div>
<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <input id="modelSearch" placeholder="{{ t("search_models") }}..." aria-label="{{ t("search_models") }}" style="max-width:300px;" oninput="filterModels()">
        <a href="/ui/setup" class="btn btn-primary">+ {{ t("configure_model") }}</a>
    </div>
    <table>
        <thead><tr><th>{{ t("model_id") }}</th><th>{{ t("provider") }}</th><th>{{ t("status") }}</th><th>Key{{ t("env_var") }}</th></tr></thead>
        <tbody id="modelTableBody"><tr><td colspan="4" style="text-align:center;color:var(--muted);">{{ t("loading") }}...</td></tr></tbody>
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
        document.getElementById('modelTableBody').innerHTML = '<tr><td colspan="4" style="color:#f85149;">'+window.__t('load_failed')+': '+e.message+'</td></tr>';
    }
}
function renderModels(models){
    var tbody = document.getElementById('modelTableBody');
    if(!models.length){
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--muted);">'+window.__t('no_models')+'</td></tr>';
        return;
    }
    tbody.innerHTML = models.map(function(m){
        var status = m.usable ? '<span style="color:#22c55e;">🟢 '+window.__t('usable')+'</span>' : (m.configured ? '<span style="color:#eab308;">🟡 '+window.__t('configured')+'</span>' : '<span style="color:#64748b;">⚫ '+window.__t('not_configured')+'</span>');
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
    flash, configured, has_more, unconfigured_count = _build_model_context(request)
    return _render("models.html", {
        "request": request, "title": "Models",
        "flash": flash, "configured": configured,
        "has_more_unconfigured": has_more,
        "total_unconfigured": unconfigured_count,
    }, request)


# ── 供应商列表页面 ───────────────────────────────────────────

_TEMPLATES["providers.html"] = r"""{% extends "base.html" %}
{% block content %}
<h2>🔌 {{ t("providers") }}</h2>
<div style="display:flex;gap:12px;margin:16px 0;flex-wrap:wrap;">
    <div class="stat-card"><div class="value" id="totalProviders">-</div><div class="label">{{ t("total_providers") }}</div></div>
    <div class="stat-card"><div class="value" id="configuredProviders">-</div><div class="label">{{ t("configured_keys") }}</div></div>
</div>
<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <input id="providerSearch" placeholder="{{ t("search_providers") }}..." aria-label="{{ t("search_providers") }}" style="max-width:300px;" oninput="filterProviders()">
        <a href="/ui/setup" class="btn btn-primary">+ {{ t("configure_provider") }}</a>
    </div>
    <table>
        <thead><tr><th>{{ t("provider") }}</th><th>{{ t("status") }}</th><th>Key</th><th>{{ t("configured_models") }}</th><th>{{ t("last_test") }}</th><th>{{ t("actions") }}</th></tr></thead>
        <tbody id="providerTableBody"><tr><td colspan="6" style="text-align:center;color:var(--muted);">{{ t("loading") }}...</td></tr></tbody>
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
        document.getElementById('providerTableBody').innerHTML = '<tr><td colspan="6" style="color:#f85149;">'+window.__t('load_failed')+': '+e.message+'</td></tr>';
    }
}
function renderProviders(providers){
    var tbody = document.getElementById('providerTableBody');
    if(!providers.length){
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--muted);">'+window.__t('no_providers')+'</td></tr>';
        return;
    }
    tbody.innerHTML = providers.map(function(p){
        var status = p.has_key ? '<span style="color:#22c55e;">🟢 '+window.__t('configured')+'</span>' : '<span style="color:#64748b;">⚫ '+window.__t('not_configured')+'</span>';
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
    return _render("providers.html", {"request": request, "title": "Providers"}, request)


# ── 文件管理器 ─────────────────────────────────────────────

_TEMPLATES["files.html"] = r"""{% extends "base.html" %}
{% block content %}
<style>
.fm-header{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.fm-breadcrumb{display:flex;align-items:center;gap:4px;flex-wrap:wrap;font-size:13px}
.fm-breadcrumb a{color:var(--accent);cursor:pointer;text-decoration:none}
.fm-breadcrumb span{color:var(--muted)}
.fm-file-table{width:100%;border-collapse:collapse}
.fm-file-table th{text-align:left;padding:8px 12px;font-size:11px;color:var(--muted);border-bottom:1px solid #1e293b}
.fm-file-table td{padding:8px 12px;border-bottom:1px solid #0f172a;font-size:13px}
.fm-file-table tr:hover{background:rgba(108,92,231,0.08)}
.fm-file-table tr{cursor:pointer}
.fm-icon{font-size:16px;width:24px}
.fm-editor{width:100%;min-height:400px;background:#0f172a;color:var(--text);border:1px solid #334155;border-radius:8px;padding:12px;font-family:'Consolas','Courier New',monospace;font-size:13px;resize:vertical}
.fm-toolbar{display:flex;gap:8px;margin-bottom:8px;align-items:center;flex-wrap:wrap}
.fm-toolbar button{padding:6px 14px;background:#1e293b;border:1px solid #334155;color:var(--text);border-radius:6px;cursor:pointer;font-size:12px}
.fm-toolbar button:hover{background:#334155}
.fm-toolbar button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.fm-tabs{display:flex;gap:2px;overflow-x:auto;border-bottom:1px solid #334155;padding-bottom:0;min-height:32px;align-items:flex-end}
.fm-tab{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;background:#1e293b;border:1px solid #334155;border-bottom:none;border-radius:6px 6px 0 0;font-size:11px;cursor:pointer;white-space:nowrap;color:var(--muted);max-width:200px;overflow:hidden}
.fm-tab:hover{background:#263348;color:var(--text)}
.fm-tab.active{background:#0f172a;color:#e2e8f0;border-color:#334155;font-weight:600}
.fm-tab-name{overflow:hidden;text-overflow:ellipsis;max-width:130px}
.fm-tab-close{font-size:13px;line-height:1;opacity:0.4;cursor:pointer;padding:0 2px;border-radius:3px}
.fm-tab-close:hover{opacity:1;color:#ef4444;background:#3b1515}
.fm-tab-modified{color:#f59e0b;font-weight:bold}
.fm-editor-wrap{position:relative;width:100%;min-height:400px;border:1px solid #334155;border-radius:0 8px 8px 8px;overflow:hidden;background:#0f172a}
.fm-editor-gutter{position:absolute;left:0;top:0;bottom:0;width:48px;background:#1a2235;color:#64748b;font-family:'Consolas','Courier New',monospace;font-size:13px;line-height:1.5;padding:12px 6px 12px 0;text-align:right;overflow:hidden;user-select:none;border-right:1px solid #1e293b;z-index:2;pointer-events:none}
.fm-editor-highlight{position:absolute;left:48px;top:0;right:0;bottom:0;padding:12px;margin:0;font-family:'Consolas','Courier New',monospace;font-size:13px;line-height:1.5;white-space:pre;overflow:hidden;background:transparent!important;z-index:1;border:none;border-radius:0}
.fm-editor-highlight code{background:transparent!important;padding:0!important;font-family:inherit;font-size:inherit;line-height:inherit;tab-size:4}
.fm-editor-textarea{position:absolute;left:48px;top:0;right:0;bottom:0;padding:12px;margin:0;font-family:'Consolas','Courier New',monospace;font-size:13px;line-height:1.5;color:transparent;caret-color:#e2e8f0;background:transparent;border:none;resize:none;outline:none;z-index:3;white-space:pre;overflow:auto;tab-size:4;-webkit-text-fill-color:transparent}
.fm-editor-textarea::selection{background:rgba(108,92,231,0.35);color:transparent;-webkit-text-fill-color:transparent}
.fm-editor-textarea:focus{outline:none;box-shadow:none}
.fm-editor-wrap .hljs{background:transparent!important;padding:0!important}
</style>
<div class="container">
<nav><a href="/ui/chat" data-nav="chat">Chat</a><a href="/ui/setup" data-nav="setup">Setup</a><a href="/ui/plugins" data-nav="plugins">Plugins</a><a href="/ui/files" data-nav="files" style="color:var(--accent);background:rgba(108,92,231,0.15);">📁 Files</a><a href="/ui/dashboard" data-nav="dashboard">Dashboard</a></nav>
<script>
(function(){
  var L={chat:{en:'Chat',zh:'聊天',ja:'チャット',ko:'채팅',es:'Chat',fr:'Chat',de:'Chat'},
    setup:{en:'Setup',zh:'设置',ja:'設定',ko:'설정',es:'Configuración',fr:'Configuration',de:'Einrichtung'},
    plugins:{en:'Plugins',zh:'插件',ja:'プラグイン',ko:'플러그인',es:'Plugins',fr:'Plugins',de:'Plugins'},
    files:{en:'Files',zh:'文件',ja:'ファイル',ko:'파일',es:'Archivos',fr:'Fichiers',de:'Dateien'},
    dashboard:{en:'Dashboard',zh:'仪表板',ja:'ダッシュボード',ko:'대시보드',es:'Panel',fr:'Tableau de bord',de:'Dashboard'}};
  var lang=localStorage.getItem('meshctx_lang')||document.cookie.match(/meshctx_lang=([^;]+)/)?.[1]||'en';
  document.querySelectorAll('[data-nav]').forEach(function(el){
    var k=el.getAttribute('data-nav'),v=L[k];
    if(v&&v[lang])el.textContent=(k==='files'?'📁 ':'')+v[lang];
  });
})();
</script>
<h2>📁 File Manager</h2>
<div class="fm-header">
 <div class="fm-breadcrumb" id="breadcrumb"></div>
 <span style="flex:1"></span>
 <span style="font-size:12px;color:var(--muted)" id="fileCount"></span>
</div>
<div class="fm-toolbar">
 <button onclick="goUp()">⬆ Up</button>
 <button onclick="refreshFiles()">🔄 Refresh</button>
 <button class="primary" onclick="navigator.clipboard.writeText(currentPath).then(()=>alert('Copied'))">📋 Copy Path</button>
</div>
<table class="fm-file-table">
<thead><tr><th></th><th>Name</th><th style="width:80px">Size</th><th style="width:160px">Modified</th></tr></thead>
<tbody id="fileList"><tr><td colspan="4" style="text-align:center;color:var(--muted)">Loading...</td></tr></tbody>
</table>
<div id="editorSection" style="display:none;margin-top:20px">
 <div class="fm-toolbar">
  <button class="primary" onclick="saveFile()" title="Ctrl+S">💾 Save</button>
  <button onclick="closeActiveTab()">✖ Close Tab</button>
  <span style="flex:1"></span>
  <span id="editorLang" style="font-size:11px;color:var(--muted)"></span>
 </div>
 <div class="fm-tabs" id="editorTabs"></div>
 <div class="fm-editor-wrap" id="editorWrapper">
  <div class="fm-editor-gutter" id="editorGutter">1</div>
  <pre class="fm-editor-highlight" id="editorHighlight" aria-hidden="true"><code id="editorCode"></code></pre>
  <textarea class="fm-editor-textarea" id="fileEditor" spellcheck="false" placeholder="Select a file to edit" aria-label="File Editor"></textarea>
 </div>
</div>
</div>
<script>
var currentPath = '';
var openTabs = [];          // {path, name, content, language, modified, savedContent}
var activeTabIdx = -1;

// ── Language detection from file extension ──
var EXT_LANG = {
  py:'python', js:'javascript', ts:'typescript', jsx:'javascript', tsx:'typescript',
  json:'json', html:'html', htm:'html', css:'css', scss:'scss', less:'less',
  md:'markdown', yaml:'yaml', yml:'yaml', toml:'ini', ini:'ini', cfg:'ini',
  xml:'xml', svg:'xml', sql:'sql', sh:'bash', bash:'bash', zsh:'bash',
  c:'c', h:'c', cpp:'cpp', hpp:'cpp', cc:'cpp', cxx:'cpp',
  java:'java', go:'go', rs:'rust', rb:'ruby', php:'php', swift:'swift',
  kt:'kotlin', scala:'scala', lua:'lua', r:'r', pl:'perl', dockerfile:'dockerfile',
  makefile:'makefile', cmake:'cmake', tex:'latex', diff:'diff', patch:'diff',
  txt:'plaintext', log:'plaintext', csv:'plaintext'
};
function detectLang(filename){
  if(!filename) return 'plaintext';
  var ext = filename.split('.').pop().toLowerCase();
  var base = filename.toLowerCase();
  if(base==='dockerfile') return 'dockerfile';
  if(base==='makefile') return 'makefile';
  if(base==='cmakelists.txt') return 'cmake';
  return EXT_LANG[ext] || 'plaintext';
}

// ── Tab management ──
function openFileInTab(path, content){
  // Check if already open
  for(var i=0; i<openTabs.length; i++){
    if(openTabs[i].path === path){
      switchTab(i);
      return;
    }
  }
  var fname = path.split('/').pop();
  var lang = detectLang(fname);
  openTabs.push({
    path: path, name: fname, content: content || '',
    language: lang, modified: false, savedContent: content || ''
  });
  renderTabs();
  switchTab(openTabs.length - 1);
  document.getElementById('editorSection').style.display = 'block';
}

function switchTab(idx){
  if(idx < 0 || idx >= openTabs.length) return;
  // Save current tab content before switching
  if(activeTabIdx >= 0 && activeTabIdx < openTabs.length){
    var ta = document.getElementById('fileEditor');
    if(ta){
      var cur = openTabs[activeTabIdx];
      cur.content = ta.value;
      cur.modified = (ta.value !== cur.savedContent);
    }
  }
  activeTabIdx = idx;
  var tab = openTabs[idx];
  var ta = document.getElementById('fileEditor');
  ta.value = tab.content;
  document.getElementById('editorLang').textContent = tab.language;
  updateHighlight();
  updateLineNumbers();
  renderTabs();
  ta.focus();
  // Sync scroll after render
  setTimeout(function(){ syncScroll(); }, 10);
}

function closeTab(idx){
  if(idx < 0 || idx >= openTabs.length) return;
  if(openTabs[idx].modified){
    if(!confirm('Unsaved changes in '+openTabs[idx].name+'. Close anyway?')) return;
  }
  openTabs.splice(idx, 1);
  if(openTabs.length === 0){
    activeTabIdx = -1;
    document.getElementById('fileEditor').value = '';
    document.getElementById('editorCode').textContent = '';
    document.getElementById('editorGutter').textContent = '1';
    document.getElementById('editorSection').style.display = 'none';
    renderTabs();
    return;
  }
  if(activeTabIdx >= openTabs.length) activeTabIdx = openTabs.length - 1;
  if(idx <= activeTabIdx && activeTabIdx > 0) activeTabIdx--;
  if(activeTabIdx < 0) activeTabIdx = 0;
  switchTab(activeTabIdx);
}

function closeActiveTab(){
  if(activeTabIdx >= 0) closeTab(activeTabIdx);
}

function renderTabs(){
  var html = '';
  for(var i=0; i<openTabs.length; i++){
    var t = openTabs[i];
    var cls = (i === activeTabIdx) ? ' active' : '';
    var mod = t.modified ? ' <span class="fm-tab-modified">●</span>' : '';
    html += '<div class="fm-tab'+cls+'" onclick="switchTab('+i+')">';
    html += '<span class="fm-tab-name" title="'+escHtml(t.path)+'">'+escHtml(t.name)+'</span>'+mod;
    html += '<span class="fm-tab-close" onclick="event.stopPropagation();closeTab('+i+')">✕</span>';
    html += '</div>';
  }
  document.getElementById('editorTabs').innerHTML = html;
}

// ── Syntax highlighting ──
function updateHighlight(){
  var tab = activeTabIdx >= 0 ? openTabs[activeTabIdx] : null;
  var lang = tab ? tab.language : 'plaintext';
  var code = document.getElementById('fileEditor').value;
  var codeEl = document.getElementById('editorCode');
  codeEl.textContent = code;
  codeEl.className = 'language-' + lang;
  if(lang !== 'plaintext' && typeof hljs !== 'undefined'){
    try{ hljs.highlightElement(codeEl); }catch(e){}
  }
  // Also highlight inline code blocks elsewhere if any
  if(typeof hljs !== 'undefined'){
    try{
      document.querySelectorAll('.fm-editor-highlight code').forEach(function(el){
        if(!el.dataset.highlighted){ el.dataset.highlighted='1'; hljs.highlightElement(el); }
      });
    }catch(e){}
  }
}

// ── Line numbers ──
function updateLineNumbers(){
  var code = document.getElementById('fileEditor').value;
  var lines = code.split('\n');
  var nums = '';
  for(var i=1; i<=lines.length; i++){ nums += i+'\n'; }
  if(lines.length === 0) nums = '1';
  document.getElementById('editorGutter').textContent = nums;
}

// ── Scroll sync ──
function syncScroll(){
  var ta = document.getElementById('fileEditor');
  var hl = document.getElementById('editorHighlight');
  var gutter = document.getElementById('editorGutter');
  hl.scrollTop = ta.scrollTop;
  hl.scrollLeft = ta.scrollLeft;
  gutter.scrollTop = ta.scrollTop;
}

// ── Editor input handler ──
function onEditorInput(){
  if(activeTabIdx >= 0){
    var tab = openTabs[activeTabIdx];
    var val = document.getElementById('fileEditor').value;
    tab.content = val;
    tab.modified = (val !== tab.savedContent);
    renderTabs();
  }
  updateHighlight();
  updateLineNumbers();
}

// ── Save ──
async function saveFile(){
  if(activeTabIdx < 0) return;
  var tab = openTabs[activeTabIdx];
  var content = document.getElementById('fileEditor').value;
  try{
    var r = await fetch('/api/file/write?path='+encodeURIComponent(tab.path), {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content:content})
    });
    var d = await r.json();
    if(d.ok){
      tab.savedContent = content;
      tab.modified = false;
      tab.content = content;
      renderTabs();
      showToast('Saved ✅');
    } else {
      alert('Failed: '+(d.error||'unknown'));
    }
  }catch(e){ alert('Save failed: '+e.message); }
}

// ── Toast notification ──
function showToast(msg){
  var el = document.createElement('div');
  el.textContent = msg;
  el.style.cssText = 'position:fixed;bottom:24px;right:24px;background:#065f46;color:#6ee7b7;padding:8px 18px;border-radius:8px;font-size:13px;z-index:9999;opacity:0;transition:opacity .3s';
  document.body.appendChild(el);
  requestAnimationFrame(function(){ el.style.opacity = '1'; });
  setTimeout(function(){ el.style.opacity = '0'; setTimeout(function(){ el.remove(); },300); }, 2000);
}

// ── File browser ──
async function loadPath(path){
 currentPath = path || '';
 try{
  var r = await fetch('/api/file/list?path='+encodeURIComponent(currentPath||'/opt/meshctx'));
  if(!r.ok){ document.getElementById('fileList').innerHTML='<tr><td colspan="4" style="color:var(--red)">'+escHtml((await r.json()).detail||r.statusText)+'</td></tr>'; return; }
  var d = await r.json();
  renderBreadcrumb(d.path);
  renderFiles(d.items, d.path);
  document.getElementById('fileCount').textContent = d.total+' items';
 }catch(e){
  document.getElementById('fileList').innerHTML='<tr><td colspan="4" style="color:var(--red)">Error: '+e.message+'</td></tr>';
 }
}

function renderBreadcrumb(fullPath){
 var parts = fullPath.split('/').filter(Boolean);
 var html = '<a onclick="loadPath(&quot;&quot;)">🏠 /</a>';
 var cum = '';
 for(var i=0;i<parts.length;i++){
  cum += '/'+parts[i];
  html += '<span>/</span><a onclick="loadPath(&quot;'+escHtml(cum)+'&quot;)">'+escHtml(parts[i])+'</a>';
 }
 document.getElementById('breadcrumb').innerHTML = html;
}

function renderFiles(items, parentPath){
 var html = '';
 if(!items||items.length===0){
  html='<tr><td colspan="4" style="color:var(--muted);text-align:center">Empty directory</td></tr>';
 }else{
  for(var i=0;i<items.length;i++){
   var f=items[i];
   var icon=f.is_dir?'📁':'📄';
   var size=f.is_dir?'--':formatSize(f.size);
   var mod=new Date(f.modified*1000).toLocaleString();
   var cls=f.error?'color:var(--red)':'';
   var sp=escHtml(f.path);
   html+='<tr style="'+cls+'" data-path="'+sp+'" data-isdir="'+f.is_dir+'" class="fm-row">';
   html+='<td class="fm-icon">'+icon+'</td>';
   html+='<td>'+escHtml(f.name)+(f.error?' ⚠️ '+escHtml(f.error):'')+'</td>';
   html+='<td style="font-size:12px;color:var(--muted)">'+size+'</td>';
   html+='<td style="font-size:12px;color:var(--muted)">'+mod+'</td>';
   html+='</tr>';
  }
 }
 document.getElementById('fileList').innerHTML = html;
}

// handleClick/selectFile replaced by event delegation in DOMContentLoaded
// (data-path + data-isdir attributes on .fm-row elements)

function goUp(){
 var p = currentPath || '/opt';
 var parent = p.substring(0, p.lastIndexOf('/')) || '';
 loadPath(parent);
}

function refreshFiles(){ loadPath(currentPath); }

// ── Open file (double-click) - fetch content into tab ──
async function openEditor(path){
 try{
  var r = await fetch('/api/file/read?path='+encodeURIComponent(path));
  var d = await r.json();
  if(d.error){ alert(d.error); return; }
  openFileInTab(path, d.content || '');
 }catch(e){ alert('Open failed: '+e.message); }
}

function closeEditor(){
 closeActiveTab();
}

function formatSize(bytes){
 if(bytes===0) return '0 B';
 var k=1024, sizes=['B','KB','MB','GB'];
 var i=Math.floor(Math.log(bytes)/Math.log(k));
 return parseFloat((bytes/Math.pow(k,i)).toFixed(1))+' '+sizes[i];
}

function escHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// ── Event delegation for file rows (replaces inline onclick/ondblclick) ──
document.addEventListener('DOMContentLoaded', function(){
  var table = document.getElementById('fileList');
  if(table){
    var clickTimer = null;
    table.addEventListener('click', function(e){
      var row = e.target.closest('.fm-row');
      if(!row) return;
      var path = row.getAttribute('data-path');
      var isDir = row.getAttribute('data-isdir') === 'true';
      
      // Select
      var prev = document.querySelector('.fm-file-table tr.selected');
      if(prev) prev.classList.remove('selected');
      row.classList.add('selected');
      
      // Double-click detection
      if(clickTimer){
        clearTimeout(clickTimer);
        clickTimer = null;
        // Double-click: open
        if(isDir){ loadPath(path); }
        else{ openEditor(path); }
      } else {
        clickTimer = setTimeout(function(){ clickTimer = null; }, 350);
      }
    });
  }
  
  var ta = document.getElementById('fileEditor');
  if(ta){
    ta.addEventListener('input', onEditorInput);
    ta.addEventListener('scroll', syncScroll);
    ta.addEventListener('keydown', function(e){
      // Ctrl+S / Cmd+S
      if((e.ctrlKey || e.metaKey) && e.key === 's'){
        e.preventDefault();
        saveFile();
      }
      // Tab key: insert spaces
      if(e.key === 'Tab'){
        e.preventDefault();
        var start = ta.selectionStart;
        var end = ta.selectionEnd;
        var val = ta.value;
        ta.value = val.substring(0, start) + '    ' + val.substring(end);
        ta.selectionStart = ta.selectionEnd = start + 4;
        onEditorInput();
      }
    });
  }
});

loadPath('');
</script>
{% endblock %}"""


@router.get("/files", response_class=HTMLResponse)
async def files_page(request: Request):
    return _render("files.html", {"request": request, "title": "Files"}, request)


# ── PWA 支持 ───────────────────────────────────────────────

@router.get("/manifest.json", response_class=JSONResponse)
async def manifest():
    """PWA manifest.json"""
    return {
        "name": "MeshCtx",
        "short_name": "MeshCtx",
        "description": "MeshCtx - AI Context Manager",
        "start_url": "/ui/",
        "display": "standalone",
        "background_color": "#0a0a1a",
        "theme_color": "#0a0a1a",
        "orientation": "any",
        "icons": [
            {
                "src": "/ui/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/ui/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }


@router.get("/sw.js", response_class=Response)
async def service_worker():
    """Service Worker — 网络优先 + 缓存回退"""
    sw_js = r"""
const CACHE_NAME = 'meshctx-v1';
const PRECACHE_URLS = [
    '/ui/',
    '/ui/manifest.json',
    '/ui/icon-192.png',
    '/ui/icon-512.png'
];

// Install: 预缓存核心资源
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
    );
    self.skipWaiting();
});

// Activate: 清理旧缓存
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
        ))
    );
    self.clients.claim();
});

// Fetch: 网络优先，失败时回退缓存
self.addEventListener('fetch', event => {
    // 跳过非 GET 请求和 API 请求
    if (event.request.method !== 'GET') return;
    const url = new URL(event.request.url);
    if (url.pathname.startsWith('/api/')) return;

    event.respondWith(
        fetch(event.request)
            .then(response => {
                // 缓存成功的响应
                if (response.ok && url.pathname.startsWith('/ui/')) {
                    const clone = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                }
                return response;
            })
            .catch(() => {
                // 网络失败时回退缓存
                return caches.match(event.request);
            })
    );
});
""".strip()
    return Response(content=sw_js, media_type="application/javascript")


# SVG 图标占位（192x192 和 512x512）
_ICON_SVG = r"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#1e3a5f"/>
      <stop offset="100%" style="stop-color:#0a0a1a"/>
    </linearGradient>
  </defs>
  <rect width="{size}" height="{size}" rx="{radius}" fill="url(#bg)"/>
  <text x="50%" y="50%" dominant-baseline="central" text-anchor="middle"
        font-family="-apple-system,BlinkMacSystemFont,sans-serif"
        font-weight="700" font-size="{font_size}" fill="#38bdf8">🧠</text>
</svg>"""


@router.get("/icon-192.png", response_class=Response)
async def icon_192():
    return Response(
        content=_ICON_SVG.format(size=192, radius=32, font_size=80),
        media_type="image/svg+xml"
    )


@router.get("/icon-512.png", response_class=Response)
async def icon_512():
    return Response(
        content=_ICON_SVG.format(size=512, radius=80, font_size=200),
        media_type="image/svg+xml"
    )
