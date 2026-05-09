# Getting Started

## Installation

### Prerequisites

- Python 3.12+
- pip
- (Optional) Docker

### Install via pip

```bash
pip install meshctx
```

### Install from source

```bash
git clone https://github.com/meshctx/meshctx.git
cd meshctx
pip install -e .
```

### Docker

```bash
docker pull meshctx/meshctx
docker run -d -p 8000:8000 meshctx/meshctx
```

## Quick Start

### 1. Start the Kernel

```bash
meshctx start
```

This starts the microkernel with:
- Event bus (4 workers)
- Memory plugin (L0-L4 hierarchy)
- Meta-cognition plugin
- Orchestrator plugin

### 2. Create a Project

```bash
meshctx project create "My Project" "Project description"
```

Or via API:

```bash
curl -X POST http://localhost:8000/projects \
  -H "Content-Type: application/json" \
  -d '{"name": "My Project", "description": "Project description"}'
```

### 3. Start a Conversation

```bash
meshctx conversation start <project_id> "First conversation"
```

### 4. Add Messages

```bash
curl -X POST http://localhost:8000/messages \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "<conv_id>",
    "role": "user",
    "content": "Remember: our goal is to build the best agent"
  }'
```

### 5. Retrieve Memories

```bash
curl http://localhost:8000/projects/<project_id>/memories
```

### 6. Execute Intent (Multi-Agent Orchestration)

```bash
curl -X POST http://localhost:8000/orchestrator/execute \
  -H "Content-Type: application/json" \
  -d '{"intent": "Deploy the new API service"}'
```

## Python SDK

```python
from meshctx import Kernel, MemoryPlugin

async def main():
    kernel = Kernel()
    memory = MemoryPlugin()
    kernel.plugins.register(memory)
    await kernel.start()

    # Add a message
    await kernel.bus.publish(Event(
        type="message.added",
        data={"content": "Important: remember this goal", "role": "user"}
    ))

    # Retrieve
    results = memory.store.retrieve("goal", top_k=5)
    for item in results:
        print(f"{item.key}: {item.value}")

    await kernel.stop()
```

## Next Steps

- [Architecture Deep Dive](/docs/architecture)
- [API Reference](/docs/api)
- [Plugin Development](/docs/plugins)
