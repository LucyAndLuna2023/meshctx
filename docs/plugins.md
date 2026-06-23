# Plugin Development

meshctx plugins are first-class Python packages that extend the agent's capabilities.

## Plugin Structure

```
my-plugin/
├── __init__.py
├── plugin.py          # Plugin class
├── requirements.txt   # Plugin dependencies
└── README.md
```

## Quick Start

### 1. Create the Plugin

```python
# my_plugin/plugin.py
from meshctx.core import Plugin, PluginInfo, Event

class MyPlugin(Plugin):
    info = PluginInfo(
        name="my-plugin",
        version="1.0.0",
        description="My custom plugin",
        author="Your Name",
        dependencies=[],  # Other plugin names this depends on
    )

    async def on_load(self):
        """Called when plugin is activated"""
        # Subscribe to events
        self.kernel.bus.subscribe(
            "message.added",
            self.on_message,
            plugin_name="my-plugin"
        )

    async def on_unload(self):
        """Called when plugin is deactivated"""
        pass

    async def on_message(self, event: Event):
        """Handle incoming messages"""
        content = event.data.get("content", "")
        print(f"Received: {content}")
```

### 2. Register the Plugin

```python
from meshctx import Kernel
from my_plugin import MyPlugin

kernel = Kernel()
kernel.plugins.register(MyPlugin())
await kernel.start()
```

## Plugin Lifecycle

```
UNLOADED → LOADING → ACTIVE → UNLOADING → UNLOADED
                ↓        ↑
              ERROR ─────┘ (retry on next load)
```

- `on_load()`: Initialize resources, subscribe to events
- `on_unload()`: Clean up resources, unsubscribe
- `on_pause()`: Temporarily pause (optional)
- `on_resume()`: Resume from pause (optional)
- `on_config_update()`: Handle configuration changes (optional)

## Event System

Plugins communicate entirely through the event bus.

### Publishing Events

```python
await self.kernel.bus.publish(Event(
    type="my-plugin.result",
    source="my-plugin",
    data={"result": "done"},
    priority=EventPriority.NORMAL,
))
```

### Subscribing to Events

```python
# Exact match
self.kernel.bus.subscribe("task.completed", handler)

# Wildcard (all memory events)
self.kernel.bus.subscribe("memory.*", handler)

# Global (all events)
self.kernel.bus.subscribe("*", handler)

# With filter
self.kernel.bus.subscribe(
    "message.added",
    handler,
    filter_fn=lambda e: e.data.get("project_id") == "my-project"
)
```

### Standard Events

| Event | When | Data |
|-------|------|------|
| `system.started` | Kernel ready | version, plugins |
| `plugin.loaded` | Plugin activated | name, version |
| `message.added` | New message | content, role, project_id |
| `task.completed` | Task finished | task_id, status, duration |
| `memory.search` | Memory query | query, top_k |
| `orchestrator.execute` | Intent received | intent |

## Publishing to Marketplace

### pip (Python)

```bash
# Package your plugin
python -m build
twine upload dist/*

# Users install:
pip install meshctx-plugin-myplugin
```

### npm (TypeScript)

```bash
npm publish @meshctx/plugin-myplugin
```

## Best Practices

1. **Lightweight `on_load`**: Load quickly, defer heavy init
2. **Handle errors gracefully**: Never crash the kernel
3. **Use resource quotas**: Respect ResourceGovernor limits
4. **Document your events**: List what you publish and subscribe
5. **Version properly**: Semantic versioning (MAJOR.MINOR.PATCH)
6. **Test in isolation**: Mock the kernel for unit tests
