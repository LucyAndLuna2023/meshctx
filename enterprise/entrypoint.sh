#!/bin/bash
set -euo pipefail

ROLE="${MESHCTX_ROLE:-rnd_architect}"
AGENT_ID="${HOSTNAME:-meshctx-agent-$(uuidgen | cut -c1-8)}"
REGISTRY_URL="${MESHCTX_REGISTRY:-redis://redis:6379/0}"
A2A_BUS_URL="${MESHCTX_A2A_BUS:-redis://redis:6379/0}"

echo "🤖 MeshCtx Agent starting: role=$ROLE id=$AGENT_ID"

# 启动 Agent (通过 meshctx 核心)
exec python3 -c "
import asyncio, os, json, yaml

# 加载角色配置
with open('agent_roles.yaml') as f:
    roles = yaml.safe_load(f)['roles']
role_cfg = roles.get('$ROLE', {})
print(f'  Role: {role_cfg.get(\"name\", \"$ROLE\")}')

# 注册到 Registry
from agent_registry import AgentRegistry, AgentInfo, AgentStatus
registry = AgentRegistry(backend=os.environ.get('MESHCTX_REGISTRY_BACKEND', 'memory'))

# 启动 A2A Bus
from a2a_protocol import A2ABus, Message, MessageType
bus = A2ABus(agent_id='$AGENT_ID', redis_url='$A2A_BUS_URL')

async def main():
    await bus.start()
    
    # 注册
    from agent_registry import AgentCapability
    agent = AgentInfo(
        agent_id='$AGENT_ID',
        role='$ROLE',
        status=AgentStatus.IDLE,
        capabilities=[AgentCapability(name=cap, proficiency=0.8)
                      for cap in role_cfg.get('tools', [])],
    )
    await registry.register(agent)
    print(f'✅ Agent registered: $AGENT_ID ($ROLE)')
    
    # 心跳循环
    while True:
        await registry.heartbeat('$AGENT_ID')
        await asyncio.sleep(10)

asyncio.run(main())
"
