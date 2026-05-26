'use strict';

import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as http from 'http';
import * as path from 'path';

const SERVER_URL = 'http://localhost:3000';

let statusBarItem: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('MeshCtx');
    outputChannel.appendLine('MeshCtx v3.33.0 activating...');

    // Status bar
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.command = 'meshctx.status';
    statusBarItem.text = '$(hubot) MeshCtx';
    statusBarItem.tooltip = 'MeshCtx Agent Status';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('meshctx.start', startAgent),
        vscode.commands.registerCommand('meshctx.chat', openChat),
        vscode.commands.registerCommand('meshctx.explain', explainCode),
        vscode.commands.registerCommand('meshctx.fix', fixBug),
        vscode.commands.registerCommand('meshctx.dashboard', openDashboard),
        vscode.commands.registerCommand('meshctx.status', showStatus)
    );

    // Auto-start
    const config = vscode.workspace.getConfiguration('meshctx');
    if (config.get('autoStart', true)) {
        startAgent();
    }

    // Status check every 30s
    setInterval(checkStatus, 30000);
    checkStatus();

    outputChannel.appendLine('MeshCtx activated');
}

async function startAgent() {
    outputChannel.appendLine('Starting MeshCtx agent...');
    statusBarItem.text = '$(sync~spin) MeshCtx starting...';
    
    try {
        cp.exec('meshctx start', { cwd: getWorkspaceRoot() }, (err, stdout) => {
            if (err) {
                outputChannel.appendLine(`Error: ${err.message}`);
                vscode.window.showErrorMessage(`MeshCtx start failed: ${err.message}`);
                statusBarItem.text = '$(error) MeshCtx';
            } else {
                outputChannel.appendLine(stdout);
            }
        });
        
        // Wait and check
        await new Promise(r => setTimeout(r, 3000));
        await checkStatus();
        
        if (statusBarItem.text.includes('running')) {
            vscode.window.showInformationMessage('MeshCtx agent started');
        }
    } catch (e: any) {
        outputChannel.appendLine(`Start error: ${e.message}`);
    }
}

async function checkStatus() {
    try {
        const health = await httpGet('/health');
        if (health && health.status === 'healthy') {
            statusBarItem.text = `$(check) MeshCtx v${health.version}`;
            statusBarItem.backgroundColor = undefined;
        }
    } catch {
        statusBarItem.text = '$(circle-slash) MeshCtx';
    }
}

async function openChat() {
    const panel = vscode.window.createWebviewPanel(
        'meshctxChat',
        'MeshCtx Chat',
        vscode.ViewColumn.Beside,
        { enableScripts: true, retainContextWhenHidden: true }
    );

    panel.webview.html = getChatHtml();
    
    panel.webview.onDidReceiveMessage(async (message) => {
        if (message.type === 'send') {
            try {
                const resp = await httpPost('/api/chat', {
                    message: message.text,
                    model: vscode.workspace.getConfiguration('meshctx').get('model', 'deepseek-v4-pro')
                });
                panel.webview.postMessage({ type: 'response', text: resp.response || resp });
            } catch (e: any) {
                panel.webview.postMessage({ type: 'response', text: `Error: ${e.message}` });
            }
        }
    });
}

async function explainCode() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const selection = editor.document.getText(editor.selection);
    if (!selection) {
        vscode.window.showWarningMessage('Select code to explain');
        return;
    }

    outputChannel.appendLine('Explaining code...');
    statusBarItem.text = '$(loading) MeshCtx explaining...';

    try {
        const resp = await httpPost('/api/chat', {
            message: `Explain this code in detail:\n\`\`\`\n${selection}\n\`\`\``,
            model: vscode.workspace.getConfiguration('meshctx').get('model')
        });
        
        const panel = vscode.window.createWebviewPanel(
            'meshctxExplain',
            'MeshCtx: Code Explanation',
            vscode.ViewColumn.Beside,
            { enableScripts: true }
        );
        panel.webview.html = `<pre style="padding:16px;font-family:monospace;white-space:pre-wrap;">${escapeHtml(resp.response || JSON.stringify(resp))}</pre>`;
        
        statusBarItem.text = '$(check) MeshCtx';
    } catch (e: any) {
        vscode.window.showErrorMessage(`Explain failed: ${e.message}`);
        statusBarItem.text = '$(error) MeshCtx';
    }
}

async function fixBug() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;

    const selection = editor.document.getText(editor.selection) || editor.document.getText();
    outputChannel.appendLine('Analyzing for bugs...');
    statusBarItem.text = '$(loading) MeshCtx analyzing...';

    try {
        const resp = await httpPost('/api/chat', {
            message: `Find and fix bugs in this code. Return ONLY the fixed code:\n\`\`\`\n${selection}\n\`\`\``,
            model: vscode.workspace.getConfiguration('meshctx').get('model')
        });
        
        // Extract code block from response
        const text = resp.response || JSON.stringify(resp);
        const codeMatch = text.match(/```[\w]*\n([\s\S]*?)```/);
        const fixedCode = codeMatch ? codeMatch[1] : text;
        
        editor.edit(editBuilder => {
            if (editor.selection.isEmpty) {
                const fullRange = new vscode.Range(0, 0, editor.document.lineCount - 1, 0);
                editBuilder.replace(fullRange, fixedCode);
            } else {
                editBuilder.replace(editor.selection, fixedCode);
            }
        });
        
        vscode.window.showInformationMessage('Bug fix applied');
        statusBarItem.text = '$(check) MeshCtx';
    } catch (e: any) {
        vscode.window.showErrorMessage(`Fix failed: ${e.message}`);
    }
}

async function openDashboard() {
    const panel = vscode.window.createWebviewPanel(
        'meshctxDashboard',
        'MeshCtx Dashboard',
        vscode.ViewColumn.One,
        { enableScripts: true }
    );
    
    try {
        const dash = await httpGet('/dashboard/live');
        panel.webview.html = dash || '<h1>Dashboard unavailable</h1>';
    } catch {
        panel.webview.html = '<h1>Cannot reach meshctx server</h1><p>Run "MeshCtx: Start Agent" first</p>';
    }
}

async function showStatus() {
    try {
        const health = await httpGet('/health');
        const msg = health 
            ? `MeshCtx v${health.version} — ${health.status} — ${health.projects_count} projects`
            : 'MeshCtx not running';
        vscode.window.showInformationMessage(msg);
    } catch {
        vscode.window.showWarningMessage('MeshCtx not running. Start with Ctrl+Shift+P → MeshCtx: Start');
    }
}

// Helpers
function httpGet(path: string): Promise<any> {
    return new Promise((resolve, reject) => {
        http.get(`${SERVER_URL}${path}`, res => {
            let data = '';
            res.on('data', chunk => data += chunk);
            res.on('end', () => {
                try { resolve(JSON.parse(data)); } catch { resolve(data); }
            });
        }).on('error', reject);
    });
}

function httpPost(path: string, body: any): Promise<any> {
    return new Promise((resolve, reject) => {
        const data = JSON.stringify(body);
        const req = http.request(`${SERVER_URL}${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Content-Length': String(data.length) }
        }, res => {
            let resp = '';
            res.on('data', chunk => resp += chunk);
            res.on('end', () => {
                try { resolve(JSON.parse(resp)); } catch { resolve(resp); }
            });
        });
        req.on('error', reject);
        req.write(data);
        req.end();
    });
}

function getWorkspaceRoot(): string {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
}

function escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function getChatHtml(): string {
    return `<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><style>
body{font-family:-apple-system,sans-serif;background:#1e1e1e;color:#d4d4d4;margin:0;padding:16px}
#messages{height:calc(100vh - 100px);overflow-y:auto;margin-bottom:8px}
.msg{margin:4px 0;padding:8px;border-radius:8px;max-width:85%}
.user{background:#264f78;margin-left:auto;text-align:right}
.agent{background:#333;margin-right:auto}
#input{display:flex;gap:8px}
textarea{flex:1;background:#333;color:#d4d4d4;border:1px solid #555;border-radius:4px;padding:8px;resize:none;font-family:inherit}
button{background:#0078d4;color:#fff;border:none;padding:8px 16px;border-radius:4px;cursor:pointer}
</style></head>
<body>
<div id="messages"></div>
<div id="input">
  <textarea id="prompt" rows="2" placeholder="Ask MeshCtx..."></textarea>
  <button onclick="send()">Send</button>
</div>
<script>
const vscode = acquireVsCodeApi();
function addMsg(text, cls) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.textContent = text;
  document.getElementById('messages').appendChild(d);
  d.scrollIntoView();
}
function send() {
  const el = document.getElementById('prompt');
  const text = el.value.trim();
  if (!text) return;
  addMsg(text, 'user');
  el.value = '';
  vscode.postMessage({type:'send',text});
}
window.addEventListener('message', e => {
  if (e.data.type === 'response') addMsg(e.data.text, 'agent');
});
</script></body></html>`;
}

export function deactivate() {
    outputChannel?.appendLine('MeshCtx deactivated');
    outputChannel?.dispose();
}
