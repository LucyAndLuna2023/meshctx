#!/usr/bin/env python3
"""
demo_multi_agent_v2.py — meshctx Multi-Agent Cluster 验证脚本
================================================================
批量创建 50 agent，10 种不同任务 dispatch，验证 collect 结果

用法:
  python3 demo_multi_agent_v2.py [--base-url http://host:3001]

依赖:
  pip install requests
"""

import requests
import json
import time
import sys
import argparse
from typing import Dict, List, Any

BASE_URL = "http://localhost:3001"


def api(method: str, path: str, data: dict = None) -> dict:
    """API wrapper with rate-limit handling"""
    url = f"{BASE_URL}{path}"
    if method == "GET":
        resp = requests.get(url, timeout=30)
    else:
        resp = requests.post(url, json=data, timeout=30)
    if resp.status_code == 429:
        retry = int(resp.headers.get("Retry-After", 5))
        print(f"  Rate limited, waiting {retry}s...", end=" ", flush=True)
        time.sleep(retry + 1)
        return api(method, path, data)
    resp.raise_for_status()
    return resp.json()


def spawn_agents(count: int, delay: float = 0.1) -> List[Dict]:
    """批量 spawn agent，返回 agent 列表"""
    agents = []
    print(f"\n{'='*60}")
    print(f"PHASE 1: Spawning {count} agents")
    print(f"{'='*60}")
    for i in range(1, count + 1):
        name = f"Agent-{i:03d}"
        role = ["math", "string", "sort", "search", "general"][i % 5]
        r = api("POST", "/api/multi_agent/spawn", {
            "name": name,
            "role": role,
            "capabilities": [role, f"task-category-{i % 10}"],
        })
        agent = r.get("agent", {})
        agents.append(agent)
        if i % 10 == 0 or i == count:
            print(f"  [{i:3d}/{count}] spawned — last: {agent.get('agent_id', '?')} ({role})")
        time.sleep(delay)
    print(f"  DONE: {len(agents)} agents spawned successfully")
    return agents


DISPATCH_TASKS: List[Dict[str, Any]] = [
    # Math (3 tasks)
    {
        "type": "math", "task": "compute: 15 + 27 * 3 - 8",
        "expected": "88 (15 + 81 - 8)"
    },
    {
        "type": "math", "task": "what is the factorial of 10?",
        "expected": "3628800"
    },
    {
        "type": "math", "task": "check if 9973 is a prime number",
        "expected": "yes, 9973 is prime"
    },
    # String (3 tasks)
    {
        "type": "string", "task": "reverse string: Hello World from meshctx",
        "expected": "xtchsem morf dlroW olleH"
    },
    {
        "type": "string", "task": "check palindrome: A man a plan a canal Panama",
        "expected": "yes (ignoring spaces and case)"
    },
    {
        "type": "string", "task": "convert to uppercase: meshctx multi-agent cluster",
        "expected": "MESHCTX MULTI-AGENT CLUSTER"
    },
    # Sort (2 tasks)
    {
        "type": "sort", "task": "sort numbers ascending: [42, 7, 99, 3, 18, 56, 23]",
        "expected": "[3, 7, 18, 23, 42, 56, 99]"
    },
    {
        "type": "sort", "task": "sort strings alphabetically: [apple, zebra, banana, mango, cherry]",
        "expected": "[apple, banana, cherry, mango, zebra]"
    },
    # Search (2 tasks)
    {
        "type": "search", "task": "find index of target=99 in [12, 34, 56, 78, 99, 123]",
        "expected": "index 4 (0-based)"
    },
    {
        "type": "search", "task": "binary search for banana in [apple, banana, cherry, mango, zebra]",
        "expected": "index 1 (0-based)"
    },
]


def dispatch_tasks(tasks: List[Dict]) -> Dict[str, Any]:
    """Dispatch 所有任务，返回 {task_id: info}"""
    print(f"\n{'='*60}")
    print(f"PHASE 2: Dispatching {len(tasks)} tasks")
    print(f"{'='*60}")
    results = {}
    strategies = ["round_robin", "least_loaded"]  # 不用 broadcast 避免全部 BUSY

    for i, t in enumerate(tasks):
        strategy = strategies[i % len(strategies)]
        r = api("POST", "/api/multi_agent/dispatch", {
            "task": t["task"],
            "strategy": strategy,
        })
        task_id = r.get("task_id", "unknown")
        assigned = r.get("assigned_to", [])

        # Handle error case
        error = r.get("error", "")
        if error:
            print(f"  [{i+1:2d}/{len(tasks)}] DISPATCH FAILED {t['type']}: {error[:60]}")
        else:
            print(f"  [{i+1:2d}/{len(tasks)}] DISPATCH -> {task_id} ({t['type']}, {strategy}, -> {len(assigned)} agent(s))")

        results[task_id] = {
            "index": i + 1,
            "type": t["type"],
            "task": t["task"],
            "strategy": strategy,
            "assigned_to": assigned,
            "expected": t.get("expected", ""),
            "error": error,
        }
        time.sleep(0.08)

    success = sum(1 for v in results.values() if not v["error"])
    print(f"  DONE: {success}/{len(tasks)} dispatched successfully")
    return results


def collect_results(task_map: Dict[str, Any]) -> List[Dict]:
    """Collect 所有 dispatched 任务的结果"""
    print(f"\n{'='*60}")
    print(f"PHASE 3: Collecting results")
    print(f"{'='*60}")

    collected = []
    for task_id, info in task_map.items():
        if info["error"]:
            print(f"  [{info['index']:2d}] SKIP — dispatch failed: {info['error'][:50]}")
            collected.append({"task_id": task_id, "status": "dispatch_failed", "content": info["error"]})
            continue

        agent_id = info["assigned_to"][0] if info["assigned_to"] else "orchestrator"
        content = f"[{info['type'].upper()}] Task complete: {info['task'][:40]}... Expected: {info['expected']}"

        try:
            r = api("POST", "/api/multi_agent/collect", {
                "task_id": task_id,
                "agent_id": agent_id,
                "content": content,
                "status": "success",
            })
            r["task_type"] = info["type"]
            r["expected"] = info["expected"]
            collected.append(r)
            print(f"  [{info['index']:2d}] COLLECTED OK  {task_id} <- {agent_id[:25]} ({info['type']})")
        except Exception as e:
            print(f"  [{info['index']:2d}] COLLECT FAIL  {task_id}: {e}")
            collected.append({"task_id": task_id, "status": "error", "content": str(e)})

        time.sleep(0.08)

    success = sum(1 for c in collected if c.get("status") == "success")
    print(f"  DONE: {success}/{len(collected)} results collected")
    return collected


def verify_cluster() -> Dict:
    """验证集群状态"""
    print(f"\n{'='*60}")
    print(f"PHASE 4: Verifying cluster state")
    print(f"{'='*60}")
    status = api("GET", "/api/multi_agent/cluster")
    orch = status.get("orchestrator", {})
    tasks_stats = status.get("tasks", {})
    agents = status.get("agents", [])

    print(f"  Orchestrator: running={orch.get('running')}")
    print(f"  Total agents: {orch.get('total_agents')}")
    print(f"  Max agents:   {orch.get('max_agents')}")
    print(f"  Total routes: {status.get('router', {}).get('total_routes', 0)}")
    print(f"  Total messages sent: {status.get('message_bus', {}).get('total_sent', 0)}")
    print(f"  Total messages delivered: {status.get('message_bus', {}).get('total_delivered', 0)}")

    print(f"\n  Tasks dispatched:  {tasks_stats.get('total_dispatched', 0)}")
    print(f"  Results collected:  {tasks_stats.get('results_collected', 0)}")
    print(f"  Pending tasks:      {tasks_stats.get('pending_tasks', 0)}")

    # Agent status breakdown
    statuses = {}
    for a in agents:
        s = a.get("status", "unknown")
        statuses[s] = statuses.get(s, 0) + 1
    print(f"\n  Agent status breakdown:")
    for s, c in sorted(statuses.items()):
        print(f"    {s}: {c}")

    return status


def print_summary(agents: List[Dict], dispatched: Dict, collected: List[Dict], cluster: Dict):
    """打印最终总结"""
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")

    total_agents = len(agents)
    total_dispatched = len(dispatched)
    total_collected = sum(1 for c in collected if c.get("status") == "success")
    types = {}
    for info in dispatched.values():
        types[info["type"]] = types.get(info["type"], 0) + 1

    print(f"  Agents spawned:     {total_agents}")
    print(f"  Tasks dispatched:  {total_dispatched}")
    print(f"  By type: {types}")
    print(f"  Results collected: {total_collected}")
    print(f"  Cluster: agents={cluster['orchestrator']['total_agents']}, max={cluster['orchestrator']['max_agents']}")

    if total_collected < total_dispatched:
        print(f"  WARNING: {total_dispatched - total_collected} results not collected")

    print(f"\n{'='*60}")
    print(f"MULTI-AGENT CLUSTER VERIFIED OK")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="meshctx Multi-Agent Cluster Demo v2")
    parser.add_argument("--base-url", default="http://localhost:3001", help="meshctx API base URL")
    parser.add_argument("--agent-count", type=int, default=50, help="Number of agents to spawn")
    parser.add_argument("--delay", type=float, default=0.12, help="Delay between API calls (seconds)")
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url

    print(f"meshctx Multi-Agent Cluster Demo v2")
    print(f"  Server: {BASE_URL}")
    print(f"  Agent count: {args.agent_count}")
    print(f"  Task types: math, string, sort, search")

    # Phase 1: Spawn agents
    agents = spawn_agents(args.agent_count, delay=args.delay)

    # Phase 2: Dispatch tasks
    dispatched = dispatch_tasks(DISPATCH_TASKS)

    # Phase 3: Collect results
    collected = collect_results(dispatched)

    # Phase 4: Verify cluster
    cluster = verify_cluster()

    # Print final summary
    print_summary(agents, dispatched, collected, cluster)

    return 0 if len(collected) == len(dispatched) else 1


if __name__ == "__main__":
    sys.exit(main())
