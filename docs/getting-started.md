     1|# Getting Started
     2|
     3|## Installation
     4|
     5|### Prerequisites
     6|
     7|- Python 3.12+
     8|- pip
     9|    10|
    11|### Install via pip
    12|
    13|```bash
    14|pip install meshctx
    15|```
    16|
    17|### Install from source
    18|
    19|```bash
    20|git clone https://github.com/meshctx/meshctx.git
    21|cd meshctx
    22|pip install -e .
    23|```
    24|
    25|### Docker
    26|
    27|```bash
    28|docker pull meshctx/meshctx
    29|docker run -d -p 8000:8000 meshctx/meshctx
    30|```
    31|
    32|## Quick Start
    33|
    34|### 1. Start the Kernel
    35|
    36|```bash
    37|meshctx start
    38|```
    39|
    40|This starts the microkernel with:
    41|- Event bus (4 workers)
    42|- Memory plugin (L0-L4 hierarchy)
    43|- Meta-cognition plugin
    44|- Orchestrator plugin
    45|
    46|### 2. Create a Project
    47|
    48|```bash
    49|meshctx project create "My Project" "Project description"
    50|```
    51|
    52|Or via API:
    53|
    54|```bash
    55|curl -X POST http://localhost:8000/projects \
    56|  -H "Content-Type: application/json" \
    57|  -d '{"name": "My Project", "description": "Project description"}'
    58|```
    59|
    60|### 3. Start a Conversation
    61|
    62|```bash
    63|meshctx conversation start <project_id> "First conversation"
    64|```
    65|
    66|### 4. Add Messages
    67|
    68|```bash
    69|curl -X POST http://localhost:8000/messages \
    70|  -H "Content-Type: application/json" \
    71|  -d '{
    72|    "conversation_id": "<conv_id>",
    73|    "role": "user",
    74|    "content": "Remember: our goal is to build the best agent"
    75|  }'
    76|```
    77|
    78|### 5. Retrieve Memories
    79|
    80|```bash
    81|curl http://localhost:8000/projects/<project_id>/memories
    82|```
    83|
    84|### 6. Execute Intent (Multi-Agent Orchestration)
    85|
    86|```bash
    87|curl -X POST http://localhost:8000/orchestrator/execute \
    88|  -H "Content-Type: application/json" \
    89|  -d '{"intent": "Deploy the new API service"}'
    90|```
    91|
    92|## Python SDK
    93|
    94|```python
    95|from meshctx import Kernel, MemoryPlugin
    96|
    97|async def main():
    98|    kernel = Kernel()
    99|    memory = MemoryPlugin()
   100|    kernel.plugins.register(memory)
   101|    await kernel.start()
   102|
   103|    # Add a message
   104|    await kernel.bus.publish(Event(
   105|        type="message.added",
   106|        data={"content": "Important: remember this goal", "role": "user"}
   107|    ))
   108|
   109|    # Retrieve
   110|    results = memory.store.retrieve("goal", top_k=5)
   111|    for item in results:
   112|        print(f"{item.key}: {item.value}")
   113|
   114|    await kernel.stop()
   115|```
   116|
   117|## Next Steps
   118|
   119|- [Architecture Deep Dive](/docs/architecture)
   120|- [API Reference](/docs/api)
   121|- [Plugin Development](/docs/plugins)
   122|