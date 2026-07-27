"""
meshctx Web UI v2 Router (stub)

v3.115.31: All routes and templates are embedded in web_ui.py
for zero-config DictLoader deployment. This file exists as a
documented reference only.

Route map:
  /ui/        → 302 redirect to /ui/v2
  /ui/v2      → Dashboard: 2 entry cards (Chat + Projects) + Gear
  /ui/v2/chat → Chat v2: sidebar history + iframe embed
  /ui/v2/projects → Projects v2: grid cards + API loading
  /ui/v2/settings → Settings modal: model/providers/memory/system
  /ui/v2/dev  → Dev Panel: Brain/Agent/Lab/Sandbox/Processes/Monitor

Legacy routes preserved:
  /ui/classic → Old 11-tab dashboard via ?tab= query param
  /ui/chat, /ui/projects, /ui/providers, /ui/plugins, /ui/memory, etc.
"""
pass
