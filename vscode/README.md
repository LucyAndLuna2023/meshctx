# MeshCtx VS Code Extension v3.33.0

Auditable Self-Adaptive Agent — right inside VS Code.

## Features

- **Chat** (`Ctrl+Shift+M`): Talk to MeshCtx in sidebar
- **Explain Code** (`Ctrl+Shift+E`): Select code, get AI explanation
- **Fix Bug**: Auto-detect and fix bugs in your code
- **Dashboard**: Real-time agent health monitor
- **Status Bar**: Always-on agent status indicator

## Setup

1. Install meshctx server: `pip install meshctx` or download from https://meshctx.com
2. Start agent: `meshctx start`
3. Install this extension from VS Code Marketplace

## Commands

| Command | Shortcut | Description |
|---------|----------|-------------|
| MeshCtx: Start Agent | — | Launch meshctx server |
| MeshCtx: Open Chat | `Ctrl+Shift+M` | Chat with agent |
| MeshCtx: Explain Code | `Ctrl+Shift+E` | Explain selected code |
| MeshCtx: Fix Bug | — | Auto-fix selected code |
| MeshCtx: Dashboard | — | Open agent dashboard |
| MeshCtx: Show Status | — | Display agent status |

## Configuration

- `meshctx.serverUrl`: Server URL (default: http://localhost:3000)
- `meshctx.autoStart`: Auto-start on VS Code launch
- `meshctx.model`: Default model (deepseek-v4-pro)

## Requirements

- meshctx server running
- VS Code 1.85+
