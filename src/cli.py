#!/usr/bin/env python3
"""
meshctx CLI v1.0 — 和 OpenClaw / Hermes 一样好用的命令行

用法:
    meshctx model scan         一键扫描环境变量, 自动配置所有模型
    meshctx model add MODEL    添加模型
    meshctx model use MODEL    切换默认模型
    meshctx model list         列出已配置
    meshctx model test "你好"  测试当前模型
    meshctx chat               开始对话
    meshctx skill list         
    meshctx start              
"""
import argparse
import asyncio
import atexit
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("meshctx.cli")

# ── 自愈: 强制优先从本安装目录加载 src 包, 防止被外部 editable install / PYTHONPATH 劫持 ──
# 2026-08-16 实测: Hermes venv 残留的 meshctx editable install 把 src 映射到开发仓库,
# 导致 meshctx chat 误加载开源 stub (STUB 降级)。此处把 cli.py 所在安装目录的父目录
# 提到 sys.path[0], 保证 import src 永远命中本安装目录的完整实现。
_SRC_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_PARENT not in sys.path:
    sys.path.insert(0, _SRC_PARENT)

# ── readline: Linux/Mac 可用，Windows 不支持 ──
try:
    import readline
    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False

_HISTORY_SAVED = False

# i18n support
try:
    from .i18n import t
except ImportError:
    def t(key: str) -> str: return key


def _get_port() -> int:
    """Get meshctx server port from env var (default 3001 — 与 install.sh 一致)"""
    return int(os.environ.get("MESHCTX_PORT", "3001"))


def _ensure_keys_loaded():
    """确保API Key已从.env加载到环境变量（CLI命令调用前）"""
    env_file = Path.home() / ".meshctx" / ".env"
    if not env_file.exists():
        return 0
    loaded = 0
    for line in env_file.read_text().strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip()
            if val and key not in os.environ:
                os.environ[key] = val
                loaded += 1
    return loaded


def _get_profile_name(config_path=None, cli_profile=None) -> str | None:
    """获取当前 profile 名称，用于 CLI 提示前缀。

    优先级: --profile CLI参数 > MESHCTX_PROFILE 环境变量 > config.yaml profile.active > config.yaml profile
    如果 profile 是 "default" 或未设置，返回 None（不显示前缀）。
    """
    import yaml

    # 1. CLI --profile 参数最高优先
    if cli_profile and cli_profile != "default":
        return cli_profile

    profile = os.environ.get("MESHCTX_PROFILE", "").strip()
    if profile:
        return profile if profile != "default" else None

    # 从 config.yaml 读取
    cfg_path = config_path or os.environ.get(
        "MESHCTX_CONFIG",
        str(Path.home() / ".meshctx" / "config.yaml")
    )
    try:
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return None

    profile = cfg.get("profile", {})
    if isinstance(profile, dict):
        profile = profile.get("active", "")
    if profile and profile != "default":
        return str(profile)
    return None


# ═══════════════════════════════════════════════════
# model 命令 — 30+模型, 一行配置
# ═══════════════════════════════════════════════════

def cmd_model(args):
    _ensure_keys_loaded()
    from src.model_registry import get_registry, BUILTIN_MODELS

    reg = get_registry(args.config)

    if args.model_action == "scan":
        print(t("i18n_scan_931ee6"))
        entries = reg.auto_configure()
        if not entries:
            print(t("i18n_common_04b72e"))
            print("  export BAILIAN_API_KEY=sk-xxx")
            print("  export DEEPSEEK_API_KEY=sk-xxx")
        else:
            print(f"{t('i18n_config_6dd3e4')}{len(entries)}{t('i18n_model_188171')}")
            for e in entries:
                print(f"   {e['id']:<30} {'✓' if e['ready'] else '⚠缺Key'}")

    elif args.model_action == "list":
        entries = reg.list_all()
        if not entries:
            print(t("i18n_scan_dc8a62"))
        else:
            print(f"\n{'模型ID':<30} {'Provider':<12} {'实际模型':<28}{t('i18n_common_3fea7c')}")
            print("-" * 85)
            for e in entries:
                s = "✓ 就绪" if e['ready'] else "⚠ 缺Key"
                print(f"{e['id']:<30} {e['provider']:<12} {e['model']:<28} {s}")

    elif args.model_action == "available":
        print(f"{t('i18n_model_6f955c')}{len(BUILTIN_MODELS)}{t('i18n_common_f4c83d')}")
        by_provider = {}
        for mid, info in BUILTIN_MODELS.items():
            p = info["provider"]
            by_provider.setdefault(p, []).append(mid)
        for provider, models in sorted(by_provider.items()):
            print(f"  [{provider}]")
            for m in models:
                print(f"    {m}  →  {BUILTIN_MODELS[m]['model']}")
            print()

    elif args.model_action == "add":
        model_id = args.model_id
        if not model_id:
            print(t("i18n_common_4fbe80"))
            print(t("i18n_common_a0fd21"))
            return
        cfg = reg.add(model_id, key=args.key or "", model=args.model or "", base_url=args.base_url or "")
        status = "✓" if cfg.get("key") else "⚠ 需要 API Key"
        print(f"{t('i18n_model_ca47bb')}{model_id} {status}")

    elif args.model_action == "test":
        client = reg.get(args.model_id)
        if not client:
            print(f"{t('i18n_model_f6895a')}{args.model_id or '默认'}{t('i18n_config_600be0')}")
            print(t("i18n_scan_61d5ac"))
            return
        prompt = args.prompt or "用一句话介绍你自己"
        print(f"{t('i18n_test_39509f')}{client.model_id} ({client.model_name})...")
        print(f"Q: {prompt}")
        resp = client.chat([{"role": "user", "content": prompt}])
        print(f"A: {resp['content']}")
        print(f"   Tokens: {resp['tokens']}")

    elif args.model_action == "use":
        # 设置默认模型(写到环境或配置)
        model_id = args.model_id
        if model_id not in reg._entries:
            print(f"{t('i18n_model_f6895a')}{model_id}{t('i18n_config_4fde74')}{model_id}'")
            return
        os.environ["MESHCTX_MODEL"] = model_id
        print(f"{t('i18n_model_24b934')}{model_id}")


# ═══════════════════════════════════════════════════
# skill 命令
# ═══════════════════════════════════════════════════

def cmd_skill(args):
    from src.skill_manager import SkillManager

    skill_dir = os.path.expanduser("~/.meshctx/skills/")
    if args.config:
        from src.config import load_config, get_skill_dir
        config = load_config(args.config)
        skill_dir = str(get_skill_dir(config))

    mgr = SkillManager(skill_dir)

    if args.skill_action == "list":
        skills = mgr.list_all()
        if not skills:
            print(t("i18n_common_490583"))
        else:
            print(f"\n{'Skill':<30} {'来源':<10} {'使用':<6} {'成功率':<8}{t('i18n_common_3bdd08')}")
            print("-" * 85)
            for s in skills:
                print(f"{s.name:<30} {s.source:<10} {s.usage_count:<6} {s.success_rate:.0%}     {s.description[:40]}")

    elif args.skill_action == "create":
        mgr.create(
            name=args.name,
            description=args.description or "",
            trigger=args.trigger or "",
            steps=args.steps.split(",") if args.steps else [],
            tools=args.tools.split(",") if args.tools else [],
        )
        print(f"{t('i18n_done_61cedf')}{args.name}")

    elif args.skill_action == "delete":
        if mgr.delete(args.name):
            print(f"{t('i18n_done_070cf9')}{args.name}")
        else:
            print(f"{t('i18n_common_6a016d')}{args.name}")

    elif args.skill_action == "auto":
        from src.model_registry import get_registry
        reg = get_registry()
        client = reg.get(None)
        pattern = {
            "task_pattern": args.name or "通用优化任务",
            "avg_quality": 0.8,
            "common_tools": args.tools.split(",") if args.tools else [],
            "frequency": 3,
        }
        skill = mgr.auto_create_from_pattern(pattern, client)
        if skill:
            print(f"{t('i18n_auto_adf2fc')}{skill.name}")


# ═══════════════════════════════════════════════════
# chat 命令
# ═══════════════════════════════════════════════════

# ═══════════════════════════════════════════════════
# gateway 交互式配置 (像 Hermes 一样通过聊天配置)
# ═══════════════════════════════════════════════════

def _cmd_gateway_setup():
    """交互式配置消息平台接入"""
    import yaml
    from pathlib import Path
    
    config_path = Path.home() / ".meshctx" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    
    print("""
╔══════════════════════════════════════════╗
║        meshctx 消息平台接入配置          ║
╠══════════════════════════════════════════╣
║  1. 企业微信 (推荐)                      ║
║  2. 飞书                                  ║
║  3. Telegram                              ║
║  0. 返回                                  ║
╚══════════════════════════════════════════╝
""")
    
    try:
        choice = input("选择平台 [1]: ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        return
    
    if choice == "0":
        return
    
    if choice == "1":
        print(t("i18n_config_7012b1"))
        print(t("i18n_common_c86ded"))
        print(t("i18n_common_8b5948"))
        print(t("i18n_common_d1fc55"))
        print(t("i18n_common_896fd3"))
        
        try:
            corp_id = input("企业ID (corp_id): ").strip()
            corp_secret = input("应用Secret (corp_secret): ").strip()
            agent_id = input("AgentId: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(t("i18n_common_2111cc"))
            return
        
        if corp_id and corp_secret:
            config.setdefault("gateway", {})["enabled"] = True
            config["gateway"]["wechat"] = {
                "corp_id": corp_id,
                "corp_secret": corp_secret,
                "agent_id": agent_id or "0",
            }
            
            with open(config_path, "w") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            
            print(f"""
✅ 企业微信已配置！
   corp_id: {corp_id[:8]}...
   配置文件: {config_path}

重启 meshctx 后生效:
   meshctx stop && meshctx start
""")
        else:
            print(t("i18n_common_e7a95b"))
    
    elif choice == "2":
        print(t("i18n_config_a34ed6"))
        try:
            app_id = input("App ID: ").strip()
            app_secret = input("App Secret: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        
        if app_id and app_secret:
            config.setdefault("gateway", {})["enabled"] = True
            config["gateway"]["feishu"] = {
                "app_id": app_id,
                "app_secret": app_secret,
            }
            with open(config_path, "w") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            print(f"{t('i18n_config_695458')}")
    
    elif choice == "3":
        print(t("i18n_config_fce0f7"))
        try:
            bot_token = input("Bot Token: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        
        if bot_token:
            config.setdefault("gateway", {})["enabled"] = True
            config["gateway"]["telegram"] = {"bot_token": bot_token}
            with open(config_path, "w") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            print(f"{t('i18n_config_d30d41')}")


def cmd_chat(args):
    """meshctx chat — 流式+工具+会话持久化+一发模式"""
    _ensure_keys_loaded()
    from src.model_registry import get_registry
    from src.chat_tools import TOOLS, execute_tool, TOOL_ICONS, trim_messages

    max_turns = getattr(args, 'max_rounds', 0) or int(os.environ.get("MESHCTX_MAX_ROUNDS", "30"))
    wall_clock = getattr(args, 'wall_clock', 0.0) or float(os.environ.get("MESHCTX_WALL_CLOCK", "1200"))

    reg = get_registry(args.config)
    model_id = args.model or os.environ.get("MESHCTX_MODEL")
    client = reg.get(model_id)
    if not client:
        print(t("i18n_scan_6de16b"))
        return

    # ── 一发模式: meshctx chat "问题" ──
    if args.message:
        _chat_one_shot(client, args.message, args)
        _auto_save_memory([_build_system_msg(args)[0], {"role": "user", "content": args.message}])
        return

    # ── 会话前缀
    SESS = _init_session_dir()
    last_marker = SESS / ".last_session"
    
    if hasattr(args, 'continue_session') and args.continue_session:
        messages = _load_session(SESS, args.continue_session)
        session_id = args.continue_session
        print(f"📂 恢复会话: {session_id}")
    elif hasattr(args, 'new_session') and args.new_session:
        messages = _build_system_msg(args)
        session_id = None
    elif last_marker.exists():
        # 自动恢复上次会话
        last_id = last_marker.read_text().strip()
        loaded = _load_session(SESS, last_id)
        if loaded:
            messages = loaded
            session_id = last_id
            print(f"📂 自动恢复上次会话: {session_id}")
        else:
            messages = _build_system_msg(args)
            session_id = None
    else:
        messages = _build_system_msg(args)
        session_id = None

    profile = _get_profile_name(args.config, getattr(args, 'profile', None))
    profile_tag = f"[{profile}] " if profile else ""

    print(f"🤖 meshctx{profile_tag} → {client.model_id}  ({client.model_name})")
    print(f"   输入 /help 查看命令  |  /quit 退出")
    print(f"   流式输出已启用  |  支持文件/命令/搜索工具\n")

    # ── readline 历史 (profile 感知) ──
    history_file = str(Path.home() / ".meshctx" / f".history_{profile or 'default'}")
    if _HAS_READLINE:
        try:
            readline.read_history_file(history_file)
        except FileNotFoundError:
            pass

        def _save_history():
            global _HISTORY_SAVED
            if not _HISTORY_SAVED:
                _HISTORY_SAVED = True
                try:
                    readline.write_history_file(history_file)
                except Exception:
                    pass
        atexit.register(_save_history)

    # ── REPL ──
    prompt = f"{profile_tag}You> " if profile_tag else "You> "
    while True:
        quit_requested = False
        try:
            if _HAS_READLINE:
                # 多行输入：空行提交，支持粘贴长文本；EOF 或 /quit 直接退出
                lines = []
                first = True
                eof_hit = False
                while True:
                    p = prompt if first else '... '
                    first = False
                    try:
                        line = input(p)
                    except EOFError:
                        eof_hit = True
                        break
                    if line == '':
                        break  # 空行提交
                    if line.strip() == "/quit":
                        quit_requested = True
                        break
                    lines.append(line)
                user = '\n'.join(lines).strip()
                if eof_hit and not lines:
                    break  # EOF：正常退出（修复管道/EOF 下的死循环）
            else:
                user = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/quit" or quit_requested:
            break

        # 斜杠命令
        if user.startswith("/"):
            if _handle_slash(user, reg, client, SESS, messages, session_id):
                if user.startswith("/model "):  # refresh client ref
                    new_client = reg.get(user.split(" ",1)[1].strip())
                    if new_client: client = new_client
                continue

        messages.append({"role": "user", "content": user})
        session_id = _chat_loop(client, messages, TOOLS, execute_tool, TOOL_ICONS, max_turns=max_turns, wall_clock=wall_clock)

        # 自动保存会话
        if session_id and len(messages) > 3:
            _save_session(SESS, session_id, messages)
            last_marker.write_text(session_id)

    # ── 对话结束：自动写入记忆体系（修复 cc0c9113: CLI 记忆从未落盘）──
    _auto_save_memory(messages)


def _chat_one_shot(client, msg, args):
    """一发模式: 问一个问题，流式回答，退出"""
    from src.chat_tools import TOOLS, execute_tool
    messages = _build_system_msg(args)
    messages.append({"role": "user", "content": msg})
    profile = _get_profile_name(args.config, getattr(args, 'profile', None))
    prefix = f"[{profile}] " if profile else ""
    print(f"{prefix}meshctx> ", end="", flush=True)
    _chat_loop(client, messages, TOOLS, execute_tool, {}, max_turns=2)
    print()


def _chat_loop(client, messages, tools_def, exec_tool, icons, max_turns=6, collect_output=False, wall_clock=None):
    """核心对话循环 — 与 UI /api/chat/stream 共用同一套 agent_loop 逻辑

    collect_output=True 时，收集最终答案与工具调用记录并返回
    (final_answer, tool_calls_list)，供 --json-output 结构化输出使用。

    wall_clock: 总处理时间上限(秒)。传入则优先；否则读环境变量
    MESHCTX_WALL_CLOCK（默认 1200）。此前该变量仅在 cmd_chat 局部定义,
    task/agent 等调用方触发 NameError（ae1dbf9 修复）— 此处统一兜底,
    同时让 cmd_chat 的 --wall-clock 参数真正传入生效。
    """
    import uuid
    import os as _os
    session_id = uuid.uuid4().hex[:8]
    _final_answer = ""
    _tool_calls = []
    if wall_clock is None:
        wall_clock = float(_os.environ.get("MESHCTX_WALL_CLOCK", "1200"))
    else:
        wall_clock = float(wall_clock)

    def _on_event(ev):
        nonlocal _final_answer, _tool_calls
        if ev["type"] == "token":
            print(ev["text"], end="", flush=True)
            if collect_output:
                _final_answer += ev["text"]
        elif ev["type"] == "round":
            print(f"\n🔍 第{ev['round'] + 1}/{ev['total']}轮搜索...", flush=True)
        elif ev["type"] == "deliver":
            print("\n📝 **Deliver** — 基于已获取的真实数据生成最终报告...\n", flush=True)
        elif ev["type"] == "tool_start":
            name, args = ev["name"], ev["args"]
            if collect_output:
                _tool_calls.append({"name": name, "args": args, "status": "start"})
            print(f"  {icons.get(name, '🔧')} {_tool_summary(name, args)}", flush=True)
        elif ev["type"] == "tool_result":
            first_line = (ev["result"] or "").split('\n')[0][:120]
            if collect_output:
                for tc in reversed(_tool_calls):
                    if tc.get("name") == ev["name"] and tc.get("status") == "start":
                        tc["status"] = "done"
                        tc["result"] = (ev["result"] or "")[:500]
                        break
            print(f"    ✅ {first_line}", flush=True)
        elif ev["type"] == "error":
            print(f"\n[错误: {ev['text']}]", flush=True)
        elif ev["type"] == "timed_out":
            print(f"\n{ev.get('text', '[已达到最大处理时间，已中止]')}", flush=True)

    async def _run():
        from src.agent_loop import run_agent_loop
        async for ev in run_agent_loop(
            client, messages,
            tools=tools_def,
            exec_tool=exec_tool,
            max_rounds=max_turns,
            wall_clock=wall_clock,
            system_prompt=None,
        ):
            _on_event(ev)

    asyncio.run(_run())
    if collect_output:
        return _final_answer.strip(), _tool_calls, session_id
    return session_id



def _tool_summary(name, args):
    """生成工具调用的1行摘要"""
    if name == "read_file":
        return f"读取: {args.get('path', '?')}"
    elif name == "write_file":
        return f"写入: {args.get('path', '?')} ({len(args.get('content',''))}字符)"
    elif name == "list_dir":
        return f"列出: {args.get('path', '.')}"
    elif name == "run_cmd":
        return f"执行: {args.get('cmd', '?')[:80]}"
    elif name == "search_files":
        return f"搜索: {args.get('pattern', '?')}"
    elif name == "web_search":
        return f"搜索: {args.get('query', '?')[:60]}"
    return f"{name}: {str(args)[:80]}"


def _build_system_msg(args):
    """构建系统提示（与 UI 共用同一份 build_system_prompt，保证两端提示词逐字一致）"""
    from src.chat_tools import build_system_prompt
    content = build_system_prompt(
        project_dir=getattr(args, 'project', None) or None,
        include_memory=True,
    )
    return [{"role": "system", "content": content}]


# ── 对话→记忆 自动写入管线（修复 cc0c9113: CLI 记忆从未落盘）──

def _extract_user_facts(messages: List[Dict]) -> List[str]:
    """规则式抽取用户明确陈述的事实/偏好（无 LLM 依赖）。

    命中模式: 记住/我叫/我是/我喜欢/我的项目/我的目标 等明确陈述。
    仅在用户消息中抽取，避免把工具调用/推理噪声写入记忆。
    """
    import re as _re
    patterns = [
        _re.compile(r'^(?:请记住|记住|记一下|记下来)[:：,，]?\s*(.{4,200})$'),
        _re.compile(r'^(?:我叫|我是|我的名字(?:是|叫)?|名字(?:是|叫)?)[:：]?\s*(.{2,100})$'),
        _re.compile(r'^(?:我喜欢|我偏好|我习惯|我常用|我使用|我在用|我负责|我是做)[:：]?\s*(.{4,200})$'),
        _re.compile(r'^我(?:的)?(?:项目|工作|团队|公司|职位|角色)[:：是]?\s*(.{2,200})$'),
        _re.compile(r'^(?:我的目标|我的计划|我打算|我要做|我需要)[:：]?\s*(.{4,200})$'),
        _re.compile(r'^(?:请务必|请注意|重要提示|关键要求)[:：,，]?\s*(.{4,200})$'),
    ]
    facts = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = (msg.get("content") or "").strip()
        if not content or len(content) > 800:
            continue
        for pat in patterns:
            m = pat.match(content)
            if m:
                fact = m.group(1).strip()
                if fact and fact not in facts:
                    facts.append(fact)
                break
    return facts


def _llm_batch_extract_memories(messages: List[Dict]) -> List[Dict]:
    """M1: 对话结束 LLM 批量抽取 — 整段对话一次抽 5-20 条结构化记忆。

    使用 config.yaml 的 deepseek 模型（key 从环境变量/`~/.meshctx/.env` 读取）。
    失败时返回空列表，由调用方回退规则式抽取。
    """
    import json as _json
    import os as _os
    try:
        # 读取模型配置（不落日志、不打印 key）
        model = "deepseek-chat"
        base_url = "https://api.deepseek.com"
        api_key = _os.environ.get("DEEPSEEK_API_KEY", "")
        env_path = _os.path.expanduser("~/.meshctx/.env")
        if _os.path.exists(env_path):
            for line in open(env_path, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k == "DEEPSEEK_API_KEY" and v:
                    api_key = v
        # 模型名/base_url 从 config.yaml 读（MESHCTX_MODEL 是内部 provider:model 格式，不能直接用于 API）
        cfg_path = _os.path.expanduser("~/.meshctx/config.yaml")
        if _os.path.exists(cfg_path):
            try:
                import yaml as _yaml
                cfg = _yaml.safe_load(open(cfg_path, encoding="utf-8")) or {}
                entries = (cfg.get("models") or {}).get("entries") or {}
                default = (cfg.get("models") or {}).get("default") or "deepseek"
                entry = entries.get(default) or entries.get("deepseek") or {}
                model = entry.get("model") or model
                if entry.get("base_url"):
                    base_url = entry["base_url"].rstrip("/")
            except Exception:
                pass
        if not api_key:
            return []
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)
        dialogue = []
        for msg in messages:
            role = msg.get("role")
            if role in ("system", "tool"):
                continue
            if role == "assistant" and msg.get("tool_calls"):
                continue
            content = (msg.get("content") or "").strip()
            if content:
                dialogue.append(f"[{role}] {content[:400]}")
        if not dialogue:
            return []
        prompt = (
            "你是记忆抽取系统。从以下对话中一次性抽取所有值得长期记住的信息，"
            "输出 JSON 数组（5-20 条）。每条字段：key(简短关键词)、value(1-2句话概括)、"
            "importance(0-1 浮点数)、category(fact/preference/decision/task/context/other)。"
            "没有值得记住的信息输出 []。只输出 JSON 数组，不要其他内容。\n\n对话:\n"
            + "\n".join(dialogue)[:8000]
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # JSON 解析（代码块/首尾 [] 兜底）
        try:
            items = _json.loads(raw)
        except Exception:
            import re as _re
            m = _re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, _re.DOTALL)
            if not m:
                start, end = raw.find("["), raw.rfind("]") + 1
                if start >= 0 and end > start:
                    m = type("_M", (), {"group": lambda self, i: raw[start:end]})()
            items = _json.loads(m.group(1)) if m else []
        if not isinstance(items, list):
            return []
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            value = str(it.get("value") or "").strip()
            if not value:
                continue
            out.append({
                "key": str(it.get("key") or "").strip()[:80],
                "value": value[:500],
                "importance": max(0.0, min(1.0, float(it.get("importance", 0.5) or 0.5))),
                "category": str(it.get("category", "other") or "other")[:40],
            })
        return out[:20]
    except Exception:
        return []


def _merge_persistent_entries(items: List[Dict]) -> int:
    """M2: 合并去重写入 persistent_memory.json（key 相等或文本相似度≥0.9 合并）。

    返回新增条数。
    """
    import difflib
    import json as _json
    from pathlib import Path as _Path
    mem_file = _Path.home() / ".meshctx" / "persistent_memory.json"
    try:
        if mem_file.exists():
            data = _json.loads(mem_file.read_text(encoding="utf-8"))
        else:
            data = {"entries": []}
        entries = list(data.get("entries", []))
        added = 0
        for it in items:
            value = it["value"]
            merged = False
            for i, ex in enumerate(entries):
                if ex == value or difflib.SequenceMatcher(None, ex, value).ratio() >= 0.9:
                    entries[i] = value  # 保留最新
                    merged = True
                    break
            if not merged:
                entries.append(value)
                added += 1
        data["entries"] = entries[-500:]
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        mem_file.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return added
    except Exception:
        return 0


def _write_structured_memories(items: List[Dict]) -> int:
    """M1/M2: 结构化记忆写入 memories/*.json（带 importance/key/last_reviewed，供 T3 检索）。

    使用 HierarchicalMemoryStore.store_with_merge 合并去重。
    返回新增条数。
    """
    import json as _json
    import time as _time
    from pathlib import Path as _Path
    try:
        from src.core.memory_hierarchy import HierarchicalMemoryStore, MemoryItem, MemoryLevel
        from src.cross_platform_engine import CrossPlatformStorage
        mem_dir = CrossPlatformStorage().base_path / "memories"
    except Exception:
        mem_dir = _Path.home() / ".meshctx" / "data" / "memories"
    try:
        mem_dir.mkdir(parents=True, exist_ok=True)
        store = HierarchicalMemoryStore()
        # 加载已有记忆（T3 兼容字段；保留原 id，避免重写后文件名漂移导致目录膨胀）
        for fp in sorted(mem_dir.glob("*.json")):
            try:
                m = _json.loads(fp.read_text(encoding="utf-8"))
                if m.get("value") or m.get("content"):
                    # 全量恢复（含 FSRS 状态: stability/difficulty/next_review/lapses 等）
                    store.store(MemoryItem.from_json_dict(m))
            except Exception:
                continue
        before = len(list(store._all_items()))
        for it in items:
            store.store_with_merge(MemoryItem(
                key=it["key"], value=it["value"], importance=it["importance"],
                level=MemoryLevel.LONG_TERM, last_reviewed=_time.time(),
                category=str(it.get("category", "other") or "other")[:40]))
        # 清理孤儿文件：删除不在当前 store 中的旧文件（防止 id 漂移累积 2^N 膨胀）
        current_ids = {_id for _id, _item in store._all_items()}
        for fp in mem_dir.glob("*.json"):
            if fp.stem not in current_ids:
                try:
                    fp.unlink()
                except OSError:
                    pass
        # P3-1: 图式化收敛自动触发（节流 <1h；纯本地无副作用，失败零阻塞）
        _maybe_auto_consolidate(store, mem_dir)
        # 写回（每文件一条，文件名 = item id；全量字段含 FSRS 状态）
        for _id, item in store._all_items():
            fp = mem_dir / f"{_id}.json"
            fp.write_text(_json.dumps(item.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return len(list(store._all_items())) - before
    except Exception:
        return 0


def _maybe_auto_consolidate(store, mem_dir) -> None:
    """P3-1: consolidate 自动触发（002 审计建议包）。

    每次对话保存末尾触发图式化收敛，内部节流：距上次收敛 <1h 跳过。
    纯本地、无副作用、失败零阻塞——保证不破坏对话保存主流程。
    """
    import time as _t
    marker = mem_dir / ".last_consolidate"
    try:
        now = _t.time()
        if marker.exists():
            try:
                last = float(marker.read_text(encoding="utf-8").strip())
            except (ValueError, OSError):
                last = 0.0
            if now - last < 3600:
                return
        stats = store.consolidate()
        marker.write_text(str(now), encoding="utf-8")
        if stats and stats.get("semantic_created"):
            try:
                from src.utils.logger import get_logger
                get_logger("meshctx.memory").info(
                    "auto-consolidate: %s semantic created, %s grouped",
                    stats.get("semantic_created"), stats.get("grouped_items"))
            except Exception:
                pass
    except Exception:
        pass


def _auto_save_memory(messages: List[Dict]) -> None:
    """对话结束后自动把对话写入记忆体系（三通道，零阻塞失败）。

    通道0 — LLM 批量抽取（M1）: 整段对话一次抽 5-20 条结构化记忆，写入
            persistent_memory.json（M2 合并去重）与 memories/*.json（带 importance）。
    通道1 — MemoryEngine(17脑区): start_conversation + add_message，
            add_message 内部 _extract_memories 自动抽取并落盘到 data/memories/。
    通道2 — persistent_memory.json 规则兜底: build_system_prompt 实际读取的持久记忆。

    根因（002 报障 cc0c9113）：save_memory 工具依赖 LLM 主动调用 → 永不触发；
    此处由 CLI 对话生命周期兜底自动保存，修复『对话→记忆』管线缺失。
    """
    if not messages or len(messages) < 2:
        return
    # 通道0: LLM 批量抽取（M1 + M2）
    try:
        items = _llm_batch_extract_memories(messages)
        if items:
            _write_structured_memories(items)
            _merge_persistent_entries(items)
    except Exception:
        pass
    # 通道1: MemoryEngine
    try:
        from src.memory_engine import MemoryEngine
        from datetime import datetime as _dt
        me = MemoryEngine(use_llm=False, use_vector_store=False)
        conv = None
        for msg in messages:
            role = msg.get("role")
            if role == "system" or role == "tool":
                continue
            if role == "assistant" and msg.get("tool_calls"):
                continue  # 跳过工具调用帧
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if conv is None:
                # start_conversation 要求 project 已存在 → 先确保 default 项目
                # （create_project 以 uuid 为 key，注册 "default" 别名便于复用）
                proj = me.projects.get("default")
                if proj is None:
                    try:
                        proj = me.create_project(name="default", description="CLI 对话默认项目")
                        me.projects["default"] = proj
                    except Exception:
                        proj = None
                conv = me.start_conversation(
                    getattr(proj, "id", None) or "default",
                    title=f"CLI 对话 {_dt.now().strftime('%Y-%m-%d %H:%M')}")
            try:
                me.add_message(conv.id, role or "user", content[:2000])
            except Exception:
                pass
    except Exception:
        pass
    # 通道2: persistent_memory.json 规则兜底
    try:
        from src.chat_tools import _save_memory
        for fact in _extract_user_facts(messages):
            try:
                _save_memory(fact)
            except Exception:
                pass
    except Exception:
        pass


def _handle_slash(cmd, reg, client, SESS, messages, session_id):
    """处理斜杠命令，返回True表示已处理"""
    if cmd == "/help":
        print("""
命令列表:
  /models       列出可用模型
  /model <id>    切换模型
  /save [name]   保存当前会话
  /load <id>     加载历史会话
  /sessions      列出所有会话
  /clear         清空当前会话
  /verbose       切换详细模式
  /gateway       模型网关设置
  /quit          退出
        """)
    elif cmd == "/models":
        entries = reg.list_all()
        for e in entries:
            status = "✓" if e['ready'] else "✗"
            print(f"  {e['id']:<25} {status}")
    elif cmd.startswith("/model "):
        new_id = cmd.split(" ", 1)[1].strip()
        new_client = reg.get(new_id)
        if new_client:
            print(f"  ✓ 切换到 {new_client.model_id} ({new_client.model_name})")
            return True
        else:
            print(f"  ✗ {new_id} 未配置")
    elif cmd == "/save" or cmd.startswith("/save "):
        import uuid
        name = cmd.split(" ", 1)[1].strip() if " " in cmd else None
        sid = session_id or uuid.uuid4().hex[:8]
        _save_session(SESS, sid, messages, name)
        print(f"  ✓ 已保存: {sid}")
    elif cmd.startswith("/load "):
        sid = cmd.split(" ", 1)[1].strip()
        loaded = _load_session(SESS, sid)
        if loaded:
            messages.clear()
            messages.extend(loaded)
            print(f"  ✓ 加载会话: {sid} ({len(messages)}条消息)")
            return True
        else:
            print(f"  ✗ 会话不存在: {sid}")
    elif cmd == "/sessions":
        _list_sessions(SESS)
    elif cmd == "/clear":
        system = messages[0] if messages[0]["role"] == "system" else None
        messages.clear()
        if system: messages.append(system)
        print("  ✓ 会话已清空")
    elif cmd == "/gateway":
        _cmd_gateway_setup()
    elif cmd == "/verbose":
        print(f"  verbose 已切换 (当前详细模式: 工具调用可见)")
    else:
        print(f"  未知命令: {cmd}  (输入 /help 查看)")
    return False


# ── 会话持久化 ──

def _init_session_dir():
    d = Path.home() / ".meshctx" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _save_session(sess_dir, sid, messages, name=None):
    import json, datetime
    file = sess_dir / f"{sid}.json"
    data = {
        "id": sid,
        "name": name or f"session-{sid}",
        "created": datetime.datetime.now().isoformat(),
        "messages": messages,
    }
    file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def _load_session(sess_dir, sid):
    import json
    file = sess_dir / f"{sid}.json"
    if not file.exists():
        return None
    data = json.loads(file.read_text())
    messages = data.get("messages", [])
    # 修复孤立 tool 消息：收集所有 assistant.tool_calls 中的 call_id
    known_ids = set()
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                known_ids.add(tc.get("id", ""))
    # 过滤掉没有对应 assistant+tool_calls 的孤立 tool 消息
    cleaned = []
    for m in messages:
        if m.get("role") == "tool" and m.get("tool_call_id") not in known_ids:
            continue
        cleaned.append(m)
    return cleaned

def _list_sessions(sess_dir):
    import json
    files = sorted(sess_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        print("  (无历史会话)")
        return
    for f in files[:10]:
        try:
            d = json.loads(f.read_text())
            print(f"  {d['id']:<10} {d['name'][:30]:<30} ({len(d['messages'])}条)")
        except Exception:
            logger.debug("cli error", exc_info=True)
            print(f"  {f.stem:<10} (损坏)")


# ═══════════════════════════════════════════════════
# agent — 自主Agent (OODA: Observe-Orient-Decide-Act)
# ═══════════════════════════════════════════════════

def cmd_agent(args):
    """自主Agent — 接收目标，自主循环直到完成"""
    _ensure_keys_loaded()
    from src.model_registry import get_registry
    from src.chat_tools import TOOLS, execute_tool, TOOL_ICONS

    reg = get_registry(args.config)
    model_id = args.model or os.environ.get("MESHCTX_MODEL")
    client = reg.get(model_id)
    if not client:
        print("模型未找到")
        return

    messages = _build_system_msg(args)
    messages.append({"role": "user", "content": f"目标: {args.goal}\n\n请制定计划，逐步执行。每步完成后汇报进展。"})

    print(f"🎯 Agent: {args.goal}")
    profile = _get_profile_name(args.config, getattr(args, 'profile', None))
    prefix = f"[{profile}] " if profile else ""
    print(f"🤖 模型: {client.model_id}  |  最大步数: {args.max_steps}")
    print(f"{'─'*50}")

    for step in range(args.max_steps):
        print(f"\n-- 第 {step+1}/{args.max_steps} 步 --")
        print(f"{prefix}meshctx> ", end="", flush=True)
        _chat_loop(client, messages, TOOLS, execute_tool, TOOL_ICONS, max_turns=3)

        # 检查是否完成
        last_content = ""
        for m in reversed(messages):
            if m["role"] == "assistant" and m.get("content"):
                last_content = m["content"]
                break
        if any(kw in last_content for kw in ["完成", "✅", "Done", "finished", "总结", "最终"]):
            print(f"\n✅ Agent 完成")
            break
    else:
        print(f"\n⚠️ 已达最大步数 {args.max_steps}，Agent 暂停")


# ═══════════════════════════════════════════════════
# task — 一次性任务
# ═══════════════════════════════════════════════════

def cmd_task(args):
    """一次性任务 — 接收描述，循环执行直到完成"""
    _ensure_keys_loaded()
    from src.model_registry import get_registry
    from src.chat_tools import TOOLS, execute_tool, TOOL_ICONS

    reg = get_registry(args.config)
    model_id = args.model or os.environ.get("MESHCTX_MODEL")
    client = reg.get(model_id)
    if not client:
        print("模型未找到")
        return

    desc = " ".join(args.description)
    messages = _build_system_msg(args)
    messages.append({"role": "user", "content": f"任务: {desc}\n\n用可用工具完成任务，直接给出结果。"})

    print(f"📋 任务: {desc}")
    profile = _get_profile_name(args.config, getattr(args, 'profile', None))
    prefix = f"[{profile}] " if profile else ""
    print(f"{prefix}meshctx> ", end="", flush=True)
    collect = bool(getattr(args, 'json_output', False))
    result = _chat_loop(client, messages, TOOLS, execute_tool, TOOL_ICONS,
                        max_turns=args.max_steps, collect_output=collect)
    print()
    if collect:
        # ── P0-1: 结构化 JSON 输出（benchmark/harness 解析用）──
        final_answer, tool_calls, session_id = result
        out = {
            "final_answer": final_answer,
            "tool_calls": tool_calls,
            "session_id": session_id,
            "model": client.model_id,
            "max_steps": args.max_steps,
        }
        print("\n---MESHCTX_JSON_OUTPUT---")
        print(json.dumps(out, ensure_ascii=False))
        print("---END_MESHCTX_JSON_OUTPUT---")


# ═══════════════════════════════════════════════════
# start / stop / status
# ═══════════════════════════════════════════════════

def cmd_start(args):
    """启动 meshctx v1.0 统一服务"""
    import uvicorn
    from src.main import app
    
    port = args.port or 3001  # 默认端口 — 与 install.sh 和 main.py 保持一致
    host = '0.0.0.0'
    from src.core import __version__
    
    print(f"""
╔══════════════════════════════════════╗
║       meshctx v{__version__} 已启动           ║
╠══════════════════════════════════════╣
║  API:     http://localhost:{port}     ║
║  Docs:    http://localhost:{port}/docs║
║  Web UI:  http://localhost:{port}/ui ║
╚══════════════════════════════════════╝
    """)
    
    uvicorn.run(app, host=host, port=port, log_level="info", timeout_keep_alive=300)


def cmd_stop(args):
    import subprocess
    r = subprocess.run(["pkill", "-f", "uvicorn.*src.main"], capture_output=True)
    print("meshctx 已停止" if r.returncode == 0 else "未找到运行中的 meshctx")


def cmd_password(args):
    """Web UI 登录密码管理（对标 OpenClaw/Hermes 开箱即用）"""
    import os
    env_path = os.path.expanduser("~/.meshctx/.env")
    action = args.password_action

    # 读取当前 .env
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            env_lines = f.readlines()

    if action == "status":
        # 先检查环境变量，再检查 .env 文件
        password = os.environ.get("MESHCTX_PASSWORD", "")
        if not password:
            for line in env_lines:
                if line.startswith("MESHCTX_PASSWORD="):
                    password = line.split("=", 1)[1].strip()
                    break
        if password:
            print(f"{t('i18n_done_ff07ab')}{len(password)}{t('i18n_common_b76065')}")
            print(f"{t('i18n_common_b6dfdc')}")
            print(f"{t('i18n_common_a24d0b')}")
        else:
            print(t("i18n_common_168075"))
            print(f"{t('i18n_common_87edca')}")
        return

    elif action == "set":
        import getpass
        pw = args.password or getpass.getpass("新密码: ")
        if not pw.strip():
            print(t("i18n_common_dbd7f7"))
            return
        # 写入或更新
        found = False
        for i, line in enumerate(env_lines):
            if line.startswith("MESHCTX_PASSWORD="):
                env_lines[i] = f"MESHCTX_PASSWORD={pw.strip()}\n"
                found = True
                break
        if not found:
            env_lines.append(f"MESHCTX_PASSWORD={pw.strip()}\n")
        os.makedirs(os.path.dirname(env_path), exist_ok=True)
        with open(env_path, "w") as f:
            f.writelines(env_lines)
        print(f"{t('i18n_done_d0b72e')}")
        return

    elif action == "clear":
        env_lines = [l for l in env_lines if not l.startswith("MESHCTX_PASSWORD=")]
        with open(env_path, "w") as f:
            f.writelines(env_lines)
        print(t("i18n_common_abc0d3"))
        return


def cmd_status(args):
    try:
        import requests
        r = requests.get(f"http://localhost:{_get_port()}/health", timeout=3)
        d = r.json()
        print(f"meshctx v{d.get('version','?')} 运行中  "
              f"项目:{d.get('projects_count',0)} 会话:{d.get('conversations_count',0)} 记忆:{d.get('memories_count',0)}")
    except Exception:
        print(t("i18n_common_bb772f"))


def cmd_setup(args):
    """交互式首次配置向导 — 类似 Hermes / OpenClaw 的 setup 流程"""
    import os
    from pathlib import Path
    from src.model_registry import BUILTIN_MODELS, ENV_KEY_MAP
    
    print("""
╔══════════════════════════════════════════╗
║     meshctx 配置向导                    ║
║  支持 123 模型 · 37 供应商              ║
╚══════════════════════════════════════════╝
""")
    
    # Step 1: 选择模型
    providers = sorted(set(v["provider"] for v in BUILTIN_MODELS.values()))
    print(t("i18n_common_5bd6dd"))
    for i, p in enumerate(providers):
        models = [k for k, v in BUILTIN_MODELS.items() if v["provider"] == p]
        print(f"  [{i+1:2d}] {p:15s} ({len(models)}{t('i18n_model_cc89e8')}{', '.join(models[:3])}")
    
    print(f"{t('i18n_common_d043da')}{len(providers)}{t('i18n_model_e63588')}")
    choice = input("  选择: ").strip()
    
    model_id = None
    provider = None
    
    # 尝试解析为编号
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(providers):
            provider = providers[idx]
    except ValueError:
        pass
    
    # 尝试解析为模型ID
    if choice in BUILTIN_MODELS:
        model_id = choice
        provider = BUILTIN_MODELS[choice]["provider"]
    
    if not model_id and provider:
        # 列出该供应商的模型
        p_models = [(k, v) for k, v in BUILTIN_MODELS.items() if v["provider"] == provider]
        print(f"\n  {provider}{t('i18n_model_8b2a21')}")
        for i, (mid, _) in enumerate(p_models):
            print(f"  [{i+1}] {mid}")
        m_choice = input("  选择模型: ").strip()
        try:
            model_id = p_models[int(m_choice)-1][0]
        except (ValueError, IndexError):
            model_id = p_models[0][0]
            print(f"{t('i18n_default_2d6270')}{model_id}")
    
    if not model_id:
        print(t("i18n_common_80d45f"))
        model_id = "deepseek:chat"
        provider = "deepseek"
    
    model_info = BUILTIN_MODELS.get(model_id, BUILTIN_MODELS["deepseek:chat"])
    print(f"{t('i18n_model_d1ae96')}{model_id} ({model_info['model']})")
    
    # Step 2: API Key
    key_env = model_info["key_env"]
    existing_key = os.environ.get(key_env, "")
    masked = existing_key[:8] + "..." if len(existing_key) > 8 else ""
    
    print(f"\n🔑 API Key: {key_env}")
    if existing_key:
        print(f"{t('i18n_done_93a253')}{masked})")
        use_existing = input("  使用已有Key? [Y/n] ").strip().lower()
        if use_existing in ('n', 'no'):
            existing_key = ""
    
    if not existing_key:
        print(f"{t('i18n_common_a88ca8')}{provider}{t('i18n_common_094df8')}")
        api_key = input(f"  请输入 {key_env}: ").strip()
        if api_key:
            os.environ[key_env] = api_key
            # 保存到 ~/.meshctx/.env (合并模式)
            env_file = Path.home() / ".meshctx" / ".env"
            env_file.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if env_file.exists():
                for line in env_file.read_text().strip().split("\n"):
                    if "=" in line and not line.startswith("#"):
                        k, v = line.split("=", 1)
                        existing[k.strip()] = v.strip()
            existing[key_env] = api_key
            env_file.write_text("\n".join(f"{k}={v}" for k, v in existing.items()) + "\n")
            print(f"{t('i18n_done_ecfc8e')}{env_file}")
    
    # Step 3: 保存配置
    config_dir = Path.home() / ".meshctx"
    config_dir.mkdir(parents=True, exist_ok=True)
    
    import yaml
    config = {
        "default_model": model_id,
        "provider": provider,
        "version": "2.27.0",
    }
    with open(config_dir / "config.yaml", "w") as f:
        yaml.dump(config, f)
    
    print(f"""
╔══════════════════════════════════════════╗
║  配置完成!                              ║
║                                        ║
║  模型: {model_id:30s} ║
║  Key:  {key_env:30s} ║
║                                        ║
║  启动: meshctx start                   ║
║  聊天: meshctx chat                    ║
║  Web:  http://localhost:{_get_port()}/ui/chat   ║
╚══════════════════════════════════════════╝
""")


def cmd_evolve(args):
    from src.skill_manager import SkillManager
    from src.model_registry import get_registry

    mgr = SkillManager()
    reg = get_registry()

    print(t("i18n_common_310c0f"))
    stats = mgr.stats()
    print(f"Skills: {stats['total']}{t('i18n_auto_d5b8d8')}{stats['auto_created']})")

    if reg._entries:
        client = reg.get(None)
        if client:
            resp = client.chat([{"role":"user","content":"根据这些Skill数据提出3条优化建议:" + json.dumps(stats,ensure_ascii=False)}])
            print(f"{t('i18n_common_3178d5')}{resp['content']}")

            if args.auto:
                skill = mgr.auto_create_from_pattern({"task_pattern":"自动优化","avg_quality":0.8,"frequency":3})
                if skill:
                    print(f"{t('i18n_auto_069a82')}{skill.name}")

    print(t("i18n_common_fca356"))


def cmd_web(args):
    import webbrowser
    webbrowser.open(f"http://localhost:{_get_port()}/ui")


def cmd_desktop(args):
    """启动 All-in-One 桌面客户端"""
    import subprocess, sys
    desktop_script = Path(__file__).resolve().parent.parent / "meshctx_desktop.py"
    if not desktop_script.exists():
        print(t("i18n_common_99b947"))
        sys.exit(1)
    print(t("i18n_common_2753f5"))
    subprocess.run([sys.executable, str(desktop_script)])


def cmd_cron(args):
    """Cron 定时任务管理"""
    from src.cron import CronPlugin
    cron = CronPlugin()
    cron._jobs = {}  # 轻量实例
    
    if args.cron_action == "list":
        print(t("i18n_common_8c9b1f"))
    elif args.cron_action == "add" and args.name:
        cron.add_job(args.name, args.schedule or "every 1h", args.action or "")
        print(f"{t('i18n_done_ff149d')}{args.name} ({args.schedule})")


def cmd_search(args):
    """Session 搜索"""
    from src.session_search import SessionSearchEngine
    engine = SessionSearchEngine()
    
    if not args.query:
        recent = engine.get_recent(args.limit)
        if not recent:
            print(t("i18n_common_8915aa"))
        else:
            for s in recent:
                print(f"  {s['title'][:50]} ({s['message_count']}{t('i18n_common_9a045f')}")
        return
    
    results = engine.search(args.query, args.limit)
    if not results:
        print(f"{t('i18n_common_916964')}{args.query}")
    else:
        for r in results:
            print(f"  [{r.score:.0%}] {r.title[:50]}")


def cmd_browser(args):
    """Browser 工具 — Playwright 真实实现"""
    from src.browser_tool import BrowserTool
    tool = BrowserTool()

    async def _run():
        if args.action == "open":
            if not args.target:
                print(t("i18n_common_cb4a08"))
                return
            result = await tool.navigate(args.target)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.action == "snap":
            content = await tool.snapshot(full=False)
            print(content)
        elif args.action == "click":
            if not args.target:
                print(t("i18n_common_cb4a08"))
                return
            result = await tool.click(args.target)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.action == "type":
            if not args.target:
                print(t("i18n_common_cb4a08"))
                return
            text = getattr(args, 'text', '') or ''
            result = await tool.type_text(args.target, text)
            print(json.dumps(result, ensure_ascii=False, indent=2))

    try:
        asyncio.run(_run())
    except ImportError as e:
        print(f"✗ {e}")
    except Exception as e:
        print(f"✗ Browser 操作失败: {e}")


def cmd_profile(args):
    """Profile多实例管理"""
    from src.core.profile_manager import ProfileManager
    pm = ProfileManager()
    
    if args.action == "list":
        profiles = pm.list()
        print(f"Profiles ({len(profiles)}):")
        for p in profiles:
            marker = " ← 当前" if p == pm.active else ""
            print(f"  {'●' if p == pm.active else '○'} {p}{marker}")
    elif args.action == "create":
        if not args.name:
            print(t("i18n_common_cb4a08"))
            return
        pm.create(args.name)
        print(f"✓ Profile '{args.name}{t('i18n_done_f7d955')}")
    elif args.action == "use":
        if not args.name:
            print(t("i18n_common_f81f9b"))
            return
        pm.use(args.name)
        print(f"{t('i18n_done_8af8ed')}{args.name}'")
    elif args.action == "delete":
        if not args.name:
            print(t("i18n_common_0278cb"))
            return
        try:
            pm.delete(args.name)
            print(f"✓ Profile '{args.name}{t('i18n_done_9d2cda')}")
        except ValueError as e:
            print(f"✗ {e}")
    elif args.action == "clone":
        if not args.name or not args.target:
            print(t("i18n_common_dd54f6"))
            return
        pm.clone(args.name, args.target)
        print(f"✓ Profile '{args.name}{t('i18n_done_a5d8a3')}{args.target}'")
    elif args.action == "path":
        name = args.name or pm.active
        print(pm.get_path(name))


def cmd_approve(args):
    """命令审批配置"""
    from src.core.approval import ApprovalEngine
    
    ae = ApprovalEngine()
    
    if args.action == "status":
        print(f"{t('i18n_common_887df5')}{ae.mode}")
        print(f"YOLO: {'开启' if ae.yolo else '关闭'}")
    elif args.action == "mode":
        if not args.mode:
            print(f"{t('i18n_common_22c6aa')}{ae.mode}")
            print(t("i18n_common_cbcdea"))
            return
        ae.set_mode(args.mode)
        print(f"{t('i18n_done_a941df')}{args.mode}")
    elif args.action == "check":
        import sys
        cmd = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        if not cmd:
            print(t("i18n_common_ed4f71"))
            return
        result = ae.check(cmd)
        print(f"{t('i18n_common_d56c0f')}{cmd}")
        print(f"{t('i18n_common_a38b0c')}{'是' if result.requires_approval else '否'}")
        print(f"{t('i18n_common_629589')}{result.risk_level}")
        print(f"{t('i18n_common_3cf4dc')}{result.action}")
        print(f"{t('i18n_common_b14d7a')}{result.reason}")


def cmd_completion(args):
    """Shell自动补全"""
    import os
    script_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "scripts", "completions"
    )
    shell_file = os.path.join(script_dir, f"meshctx.{args.shell}")
    if os.path.isfile(shell_file):
        with open(shell_file) as f:
            print(f.read())
    else:
        print(f"{t('i18n_common_d82da2')}{shell_file}")


def cmd_tts(args):
    """TTS 语音合成"""
    from src.tts import TTSEngine
    import asyncio
    
    if not args.text:
        print(t("i18n_common_443129"))
        return
    
    async def run():
        engine = TTSEngine("edge")
        path = await engine.synthesize(args.text, args.voice)
        print(f"{t('i18n_done_c25913')}{path}")
    
    asyncio.run(run())


def cmd_mcp(args):
    """MCP 协议"""
    from src.mcp_server import MCPServer

    if args.action == "tools":
        server = MCPServer()
        print(f"{t('i18n_common_9639c4')}{len(server._tools)}{t('i18n_common_3fa102')}")
        for name, tool in server._tools.items():
            print(f"  {name}: {tool.description}")
    elif args.action == "serve":
        print(t("i18n_common_0fa497"))
        server = MCPServer()
        import asyncio
        asyncio.run(server.run_stdio())


def cmd_auth(args):
    """凭证池管理 — 多Key轮转"""
    from src.core.credential_pool import CredentialPoolManager
    mgr = CredentialPoolManager()

    if args.action == "list":
        if args.provider:
            keys = mgr.list_keys(args.provider)
            if not keys:
                print(f"Provider '{args.provider}{t('i18n_common_d8319c')}")
                return
            strategy = mgr.pools.get(args.provider)
            print(f"\n📋 {args.provider}{t('i18n_common_dc1a6d')}{strategy.strategy if strategy else 'round_robin'}")
            for i, k in enumerate(keys):
                icon = "🟢" if k["status"] == "active" else "🔴" if k["status"] == "revoked" else "🟡"
                name = k.get("label") or (k["key"][:12] + "...")
                print(f"  [{i}] {icon} {name} — calls:{k['call_count']} status:{k['status']}")
        else:
            providers = mgr.list_providers()
            if not providers:
                print(t("i18n_common_f54ed1"))
                return
            stats = mgr.get_stats()
            print(f"{t('i18n_common_a4ea52')}{stats['total_pools']} providers, {stats['total_keys']} keys")
            for prov in providers:
                pool = mgr.pools[prov]
                active = sum(1 for k in pool.keys if k.status == "active")
                print(f"  {prov}: {len(pool.keys)} keys ({active} active) — {pool.strategy}")

    elif args.action == "add":
        if not args.provider or not args.key:
            print(t("i18n_common_c09454"))
            return
        pk = mgr.add_key(args.provider, args.key, args.label)
        print(f"{t('i18n_done_acc478')}{args.provider}: {pk.key[:12]}{t('i18n_common_a0d484')}{len(mgr.pools[args.provider].keys)}")

    elif args.action == "remove":
        if not args.provider or args.index < 0:
            print(t("i18n_common_823fa7"))
            return
        ok = mgr.remove_key(args.provider, args.index)
        print(f"{'✅ 已移除' if ok else '❌ 未找到'} index={args.index}")

    elif args.action == "rotate":
        if not args.provider:
            print(t("i18n_common_8fa22a"))
            return
        key = mgr.get_key(args.provider)
        if key:
            print(f"{t('i18n_common_346e07')}{key[:8]}...{key[-4:]}")
        else:
            print(f"❌ {args.provider}{t('i18n_common_d31419')}")

    elif args.action == "reset":
        if not args.provider:
            print(t("i18n_common_4ccf54"))
            return
        if args.index >= 0:
            ok = mgr.reset_key(args.provider, args.index)
            print(f"{'✅ 已重置' if ok else '❌ 未找到'} index={args.index}")
        else:
            count = mgr.reset_provider(args.provider)
            print(f"{t('i18n_done_70ba1f')}{count}{t('i18n_common_ca3982')}")

    elif args.action == "stats":
        stats = mgr.get_stats(args.provider)
        print(f"{t('i18n_common_7ce229')}")
        print(f"  Providers: {stats['total_pools']}")
        print(f"  Total keys: {stats['total_keys']}")
        print(f"  Active: {stats['active_keys']} | Exhausted: {stats['exhausted_keys']}")
        for prov, ps in stats.get("per_provider", {}).items():
            print(f"  {prov}: {ps['total']} keys ({ps['active']} active) — {ps['strategy']}")

    elif args.action == "strategy":
        if not args.provider or not args.strategy:
            print(t("i18n_common_993dc2"))
            return
        ok = mgr.set_strategy(args.provider, args.strategy)
        print(f"{'✅ 策略已更新' if ok else '❌ 无效策略'}: {args.provider} → {args.strategy}")

    elif args.action == "clear":
        mgr.clear_all()
        print(t("i18n_common_c5fa61"))


def cmd_sessions(args):
    """会话管理 — 重命名/清理/统计/浏览"""
    from src.core.conversation_store import Conversation

    if args.action == "list":
        convs = Conversation.list_all()
        if not convs:
            print(t("i18n_common_cbdeb7"))
            return
        print(f"{t('i18n_common_d112b6')}{len(convs)}):")
        for c in convs:
            import datetime
            ts = datetime.datetime.fromtimestamp(c.get("updated_at", 0)).strftime("%m-%d %H:%M")
            title = c.get("title", "Untitled")[:40]
            mid = c.get("id", "")[:8]
            print(f"  {mid}... {title} — {c.get('message_count', 0)}msgs @{ts}")

    elif args.action == "rename":
        if not args.id or not args.title:
            print(t("i18n_common_2a23ae"))
            return
        ok = Conversation.rename(args.id, args.title)
        print(f"{'✅ 已重命名' if ok else '❌ 会话不存在'}")

    elif args.action == "delete":
        if not args.id:
            print(t("i18n_common_2f1f6c"))
            return
        ok = Conversation.delete(args.id)
        print(f"{'✅ 已删除' if ok else '❌ 会话不存在'}")

    elif args.action == "prune":
        result = Conversation.prune(args.days)
        print(f"{t('i18n_done_d1a678')}{result['deleted']}{t('i18n_common_198eb3')}{args.days}{t('i18n_common_f8890e')}{result['freed_bytes']}{t('i18n_common_55a8e9')}")

    elif args.action == "stats":
        stats = Conversation.stats()
        print(f"{t('i18n_common_f20ebf')}")
        print(f"{t('i18n_common_a8b9f4')}{stats['total_sessions']}")
        print(f"{t('i18n_common_75de8c')}{stats['total_messages']}")
        print(f"{t('i18n_common_62c385')}{stats['total_size_mb']} MB")
        print(f"{t('i18n_common_6ff1e5')}{stats['active_in_memory']}")
        if stats.get("model_distribution"):
            print(f"{t('i18n_model_4e58d0')}{stats['model_distribution']}")

    elif args.action == "browse":
        metas = Conversation.browse_meta(search=args.search)
        if not metas:
            print(t("i18n_common_f10c91"))
            return
        print(f"{t('i18n_common_1781f1')}{args.search}' — {len(metas)}{t('i18n_common_2e5a34')}")
        for m in metas:
            import datetime
            ts = datetime.datetime.fromtimestamp(m.get("updated_at", 0)).strftime("%m-%d %H:%M")
            title = m.get("title", "")[:50]
            mid = m.get("id", "")[:12]
            print(f"  {mid}... {title} — {m.get('message_count', 0)}msgs @{ts}")


def cmd_insights(args):
    """使用洞察分析"""
    from src.core.usage_insights import UsageInsights
    ins = UsageInsights()

    if args.period == "today":
        data = ins.get_today()
        print(f"{t('i18n_common_d45944')}{data['date']}):")
        print(f"{t('i18n_common_8a88f3')}{data['sessions']}{t('i18n_common_ac054e')}{data['messages']}")
        print(f"  Tokens: {data['total_tokens']}{t('i18n_common_ebd81f')}{data['errors']} ({data['error_rate_pct']}%)")
        print(f"{t('i18n_common_bfc6cd')}{data['avg_latency_ms']}{t('i18n_common_adb6ef')}{data['peak_hour']}h")
        if data.get("models_used"):
            print(f"{t('i18n_model_c1fef6')}{data['models_used']}")

    elif args.period == "weekly":
        data = ins.get_weekly()
        print(f"{t('i18n_common_cdb9c3')}")
        print(f"{t('i18n_common_8a88f3')}{data['total_sessions']}{t('i18n_common_ac054e')}{data['total_messages']}")
        print(f"{t('i18n_common_569d7b')}{data['avg_daily_sessions']}{t('i18n_common_c12fa3')}{data['avg_daily_messages']}{t('i18n_common_ff692f')}")
        print(f"  Tokens: {data['total_tokens']}{t('i18n_common_ebd81f')}{data['total_errors']}")
        if data.get("daily_breakdown"):
            for d in data["daily_breakdown"]:
                print(f"    {d['date']}: {d['sessions']}{t('i18n_common_9a834e')}{d['messages']}msg")

    elif args.period == "monthly":
        data = ins.get_monthly()
        print(f"{t('i18n_common_8645ac')}")
        print(f"{t('i18n_common_a8b9f4')}{data['total_sessions']}{t('i18n_common_eead76')}{data['total_messages']}")
        print(f"{t('i18n_common_569d7b')}{data['avg_daily_sessions']}{t('i18n_common_c12fa3')}{data['avg_daily_messages']}{t('i18n_common_ff692f')}")
        print(f"  Tokens: {data['total_tokens']}")

    else:  # all
        data = ins.get_summary(args.days)
        print(f"{t('i18n_common_805f1d')}{args.days}{t('i18n_common_cef1fe')}")
        t = data.get("today", {})
        print(f"{t('i18n_common_f256ef')}{t.get('sessions',0)}{t('i18n_common_9a834e')}{t.get('messages',0)}{t('i18n_common_ff692f')}")
        w = data.get("weekly", {})
        print(f"{t('i18n_common_c02dc6')}{w.get('total_sessions',0)}{t('i18n_common_9a834e')}{w.get('total_messages',0)}{t('i18n_common_ff692f')}")
        m = data.get("monthly", {})
        print(f"{t('i18n_common_88121a')}{m.get('total_sessions',0)}{t('i18n_common_9a834e')}{m.get('total_messages',0)}{t('i18n_common_ff692f')}")
        print(f"{t('i18n_common_a82f75')}{data.get('total_days_tracked',0)}")
        # Provider stats
        provs = data.get("providers", {}).get("providers", [])
        if provs:
            print(f"  Providers:")
            for p in provs[:5]:
                print(f"    {p['provider']}: {p['calls']}calls, {p['error_rate_pct']}% err, {p['avg_latency_ms']}ms")


def cmd_diff(args):
    """文件Diff预览 (v2.44)"""
    from src.core.diff_preview import get_diff_engine
    engine = get_diff_engine()
    if hasattr(args, 'diff_cmd') and args.diff_cmd == "history":
        history = engine.get_history()
        print(f"{t('i18n_common_0ac0eb')}{len(history)}{t('i18n_common_a38d69')}")
        for h in history[-10:]:
            print(f"  {h['change_id'][:20]}... {h['file_path']} (+{h.get('stats',{}).get('added',0)} -{h.get('stats',{}).get('removed',0)})")
    elif hasattr(args, 'diff_cmd') and args.diff_cmd == "backups":
        backups = engine.list_backups()
        print(f"{t('i18n_common_9c0e4e')}{len(backups)}{t('i18n_common_3fa102')}")
        for b in backups[:10]:
            print(f"  {b['filename']} ({b['size']}B)")
    else:
        print(t("i18n_common_66ad5d"))


def cmd_tasks(args):
    """后台任务管理 (v2.45)"""
    from src.core.task_progress import get_progress_engine
    engine = get_progress_engine()
    if hasattr(args, 'task_cmd') and args.task_cmd == "history":
        history = engine.get_history()
        print(f"{t('i18n_common_d3b84f')}{len(history)}{t('i18n_common_a38d69')}")
        for h in history[-10:]:
            print(f"  {h['name']}: {h['status']} ({h.get('progress',0)}%)")
    elif hasattr(args, 'task_cmd') and args.task_cmd == "stats":
        stats = engine.get_stats()
        print(f"{t('i18n_common_89bc06')}{stats['active']}{t('i18n_common_769d88')}{stats['completed']}{t('i18n_common_acd5cb')}{stats['failed']}")
    else:
        active = engine.list_active()
        print(f"{t('i18n_common_a8f267')}{len(active)}):")
        for t in active:
            print(f"  {t.name}: {t.status} ({t.progress}%)")


def cmd_sdb(args):
    """SDB框架 (v2.46)"""
    from src.core.sdb_framework import get_sdb_engine
    engine = get_sdb_engine()
    if hasattr(args, 'sdb_cmd') and args.sdb_cmd == "reliability":
        score = engine.get_reliability_score()
        print(f"{t('i18n_common_040287')}{score['reliability_score']}/100 {score['grade']}")
        print(f"  {score['recommendation']}")
    elif hasattr(args, 'sdb_cmd') and args.sdb_cmd == "test":
        record = engine.pipeline("cli", args.action, {},
            "test", ["check"], {"check": getattr(args, 'pass_check', True)})
        print(f"{t('i18n_test_f5bdd3')}{record.phase.value}")
        print(f"{t('i18n_common_4c6ba4')}{record.commit_success}")
    else:
        stats = engine.get_stats()
        print(f"{t('i18n_common_26bf60')}{stats['total_proposals']}{t('i18n_common_939d53')}{stats['total_commits']}{t('i18n_common_7173f8')}{stats['total_rejects']}")
        print(f"{t('i18n_common_48c118')}{stats['commit_rate']:.1%}{t('i18n_common_63e3f1')}{stats['replay_divergences']}")


def cmd_brain(args):
    """脑状态验证 (v2.48)"""
    from src.core.brain_validator import get_brain_validator
    bv = get_brain_validator()
    profile = bv.get_recovery_profile()
    print(f"{t('i18n_common_fc95ff')}{profile['recovery_grade']}")
    print(f"{t('i18n_common_941e6d')}{profile['overall_recovery']:.1%}")
    print(f"{t('i18n_common_b407a0')}{profile['dimensions_recovered']}/{profile['total_dimensions']}{t('i18n_common_f29c54')}")
    for cat, stats in profile.get('by_category', {}).items():
        print(f"  {cat}: {stats['mean']:.1%}")


def cmd_modify(args):
    """自修改代码引擎 (v2.47)"""
    from src.core.self_modify import get_self_modify_engine
    engine = get_self_modify_engine()
    if hasattr(args, 'modify_cmd') and args.modify_cmd == "analyze":
        target = getattr(args, 'path', 'src/')
        results = engine.analyze_src(pattern="*.py" if target.endswith('/') else target)
        print(f"{t('i18n_common_297640')}{results['files_analyzed']}{t('i18n_common_2a0c47')}{results['total_issues']}{t('i18n_common_5dc99f')}")
        if results.get('files_with_issues'):
            for f in results['files_with_issues'][:5]:
                print(f"  {f}")
    elif hasattr(args, 'modify_cmd') and args.modify_cmd == "history":
        history = engine.get_history()
        print(f"{t('i18n_common_b2ea62')}{len(history)}{t('i18n_common_a38d69')}")
        for c in history[-10:]:
            print(f"  {c['file_path']}: {c['change_type']} ({c['status']})")
    else:
        stats = engine.get_stats()
        print(f"{t('i18n_common_26e3b0')}{stats['total_proposed']}{t('i18n_common_5b0520')}{stats['total_applied']}{t('i18n_common_d00b48')}{stats['total_rolled_back']}")
        print(f"{t('i18n_done_eab34f')}{stats['applied_this_session']}/{stats['max_per_session']}")


def cmd_review(args):
    """代码审查 — 对标 Goose review 命令"""
    from src.core.code_reviewer import CodeReviewer

    reviewer = CodeReviewer()
    path = args.path

    if not os.path.exists(path):
        print(f"{t('i18n_common_1c26c5')}{path}")
        return

    if os.path.isfile(path):
        # 单文件审查
        ext = os.path.splitext(path)[1].lower()
        lang_map = {".py": "python", ".js": "javascript", ".jsx": "javascript",
                    ".ts": "typescript", ".tsx": "typescript", ".html": "html"}
        language = lang_map.get(ext, "python")

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except IOError as e:
            print(f"{t('i18n_common_858b56')}{e}")
            return

        issues = reviewer.review_file(os.path.basename(path), content, language=language)
        summary = reviewer.review_summary(issues)

        print(f"{t('i18n_common_03d9ee')}{os.path.basename(path)}")
        print(f"{t('i18n_common_5fc57e')}{language}{t('i18n_common_052409')}{len(content.split(chr(10)))}")
        _print_review_result(summary, issues, max_issues=getattr(args, 'max_issues', 30))

        # AI 深度审查（可选）
        if getattr(args, 'ai', False):
            print(t("i18n_common_c60595"))
            ai_result = reviewer.ai_deep_review(content, language=language)
            if ai_result:
                print(f"{t('i18n_model_c1fef6')}{ai_result.get('model_used', '?')}")
                print(f"   {ai_result.get('summary', '')[:300]}")
            else:
                print(t("i18n_common_2a65bf"))

    else:
        # 目录审查
        print(f"{t('i18n_scan_3a67fc')}{path}")
        result = reviewer.project_review(path)
        _print_review_result(result, result.get("issues", []),
                            max_issues=getattr(args, 'max_issues', 30))

        # 文件级统计
        by_file = result.get("by_file", {})
        if by_file:
            top_files = sorted(by_file.items(), key=lambda x: -x[1])[:10]
            if top_files:
                print(f"\n{'='*60}")
                print(t("i18n_common_fc770a"))
                for fname, count in top_files:
                    bar = "█" * min(count, 20)
                    print(f"  {count:>3} {bar} {fname}")

        # AI 深度审查（可选）
        if getattr(args, 'ai', False):
            print(t("i18n_common_ed7b9e"))


def _print_review_result(summary: dict, issues: list, max_issues: int = 30):
    """格式化输出审查结果。"""
    score = summary.get("score", 0)
    verdict = summary.get("verdict", "?")

    # 评分颜色（终端符号）
    if score >= 80:
        icon = "🟢"
    elif score >= 60:
        icon = "🟡"
    else:
        icon = "🔴"

    print(f"\n{'='*60}")
    print(f"  {icon}{t('i18n_common_58a2f6')}{score}/100 — {verdict}")
    print(f"{t('i18n_common_20e2dd')}{summary.get('total_issues', 0)}")
    if summary.get("files_scanned"):
        print(f"{t('i18n_scan_f88d3b')}{summary['files_scanned']}")

    by_sev = summary.get("by_severity", {})
    if by_sev:
        parts = []
        for sev in ("critical", "high", "medium", "low", "info"):
            if by_sev.get(sev):
                parts.append(f"{sev}={by_sev[sev]}")
        print(f"{t('i18n_common_3bdb88')}{', '.join(parts)}")

    by_cat = summary.get("by_category", {})
    if by_cat:
        parts = []
        for cat in ("security", "bug", "performance", "style", "docs"):
            if by_cat.get(cat):
                parts.append(f"{cat}={by_cat[cat]}")
        print(f"{t('i18n_common_c52d31')}{', '.join(parts)}")

    # 打印问题列表（最多显示30条）
    if issues:
        display_issues = issues if isinstance(issues[0], dict) else [i.to_dict() if hasattr(i, 'to_dict') else i for i in issues]
        print(f"\n{'='*60}")
        print(t("i18n_common_c6a97b"))
        for idx, issue in enumerate(display_issues[:max_issues]):
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵", "info": "⚪"}.get(
                issue.get("severity", ""), "❓")
            print(f"  {sev_icon} [{issue.get('severity', '?')}] {issue.get('file', '')}:{issue.get('line', '')}")
            print(f"     {issue.get('title', '')}")
            desc = issue.get('description', '')
            if desc:
                print(f"     {desc[:100]}")

        if len(display_issues) > max_issues:
            print(f"{t('i18n_common_dcf060')}{len(display_issues) - max_issues}{t('i18n_common_653ff0')}")


def cmd_loop(args):
    """统一OODA循环测试 (v2.50)"""
    from src.core.unified_loop import get_unified_loop
    import asyncio
    engine = get_unified_loop()
    text = " ".join(args.input) if args.input else "测试消息"
    async def run():
        for i in range(args.iterations):
            result = await engine.run_once(f"{text} #{i+1}")
            print(f"{t('i18n_common_183972')}{result['iteration']}: {result['total_ms']}ms")
            for phase, t in result.get('phase_times', {}).items():
                print(f"  {phase}: {t}ms")
    asyncio.run(run())


def cmd_image(args):
    """AI图片生成"""
    from src.core.image_gen import ImageGenerator

    if not args.prompt:
        # 无prompt时列出可用provider
        gen = ImageGenerator()
        providers = gen.list_providers()
        print(f"{t('i18n_common_49a0f4')}")
        for p in providers:
            status = "✓ 可用" if p["available"] else "✗ 无Key"
            print(f"  [{p['id']}] {p['name']:30s} {status}")
            print(f"{t('i18n_model_c1fef6')}{', '.join(p['models'])}")
            print(f"{t('i18n_common_1bbfef')}{', '.join(p['valid_sizes'][:3])}...")
            print()
        if not gen.has_provider:
            print(t("i18n_common_e6c0a1"))
            print("    export OPENAI_API_KEY=sk-...      # DALL-E")
            print("    export STABILITY_API_KEY=sk-...   # Stable Diffusion")
        print(f"{t('i18n_common_059874')}")
        return

    gen = ImageGenerator(provider=args.provider)
    print(f"🎨 生成中: \"{args.prompt}\" ({args.size})")
    result = gen.generate(args.prompt, size=args.size, style=args.style)

    if result.get("error"):
        print(f"❌ {result['error']}")
        return

    cached = " (缓存)" if result.get("cached") else ""
    print(f"{t('i18n_done_700485')}{cached}")
    print(f"{t('i18n_common_a127eb')}{result['provider']}")
    print(f"   URL:    {result['url']}")



# ═══════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(prog="meshctx", description="世界第一自进化 Agent")
    sub = p.add_subparsers(dest="command")

    # model
    m = sub.add_parser("model", help="模型管理 (30+内置)")
    m.add_argument("model_action", choices=["scan","list","available","add","test","use"])
    m.add_argument("model_id", nargs="?", help="模型ID, 如 deepseek:chat")
    m.add_argument("--key", help="API Key")
    m.add_argument("--model", help="实际模型名")
    m.add_argument("--base-url", help="API地址")
    m.add_argument("-p","--prompt", help="测试提示词")
    m.add_argument("-c","--config")
    m.set_defaults(func=cmd_model)

    # skill
    s = sub.add_parser("skill", help="Skill 管理")
    s.add_argument("skill_action", choices=["list","create","delete","auto"])
    s.add_argument("name", nargs="?")
    s.add_argument("-d","--description")
    s.add_argument("-t","--trigger")
    s.add_argument("--steps")
    s.add_argument("--tools")
    s.add_argument("-c","--config")
    s.set_defaults(func=cmd_skill)

    # chat
    c = sub.add_parser("chat", help="对话 (流式+工具+会话持久化)")
    c.add_argument("-m","--model", help="模型ID")
    c.add_argument("-s","--system", help="系统提示")
    c.add_argument("-p","--profile", help="Profile名称 (如 work, meshctx)")
    c.add_argument("-c","--config")
    c.add_argument("--project", help="项目上下文目录 (自动加载 AGENTS.md)")
    c.add_argument("--continue", dest="continue_session", help="恢复历史会话ID")
    c.add_argument("--new", dest="new_session", action="store_true", help="强制新会话(跳过自动恢复)")
    c.add_argument("--max-rounds", type=int, default=0, help="搜索轮次上限 (默认30=29搜+1交付; 0则读环境变量 MESHCTX_MAX_ROUNDS)")
    c.add_argument("--wall-clock", type=float, default=0.0, help="整轮处理墙钟上限秒 (默认1200; 0则读环境变量 MESHCTX_WALL_CLOCK)")
    c.add_argument("message", nargs="?", help="一发模式: 直接问一个问题")
    c.set_defaults(func=cmd_chat)

    # agent — 自主Agent模式
    ag = sub.add_parser("agent", help="自主Agent (OODA循环+工具)")
    ag.add_argument("-m","--model", help="模型ID")
    ag.add_argument("-c","--config")
    ag.add_argument("-p","--profile", help="Profile名称")
    ag.add_argument("-g","--goal", required=True, help="Agent目标")
    ag.add_argument("--project", help="项目上下文")
    ag.add_argument("--max-steps", type=int, default=8, help="最大步数 (默认8)")
    ag.set_defaults(func=cmd_agent)

    # task — 一次性任务
    tk = sub.add_parser("task", help="一次性任务执行 (自动工具循环)")
    tk.add_argument("-m","--model", help="模型ID")
    tk.add_argument("-c","--config")
    tk.add_argument("description", nargs="+", help="任务描述")
    tk.add_argument("--project", help="项目上下文")
    tk.add_argument("--max-steps", type=int, default=5, help="最大步数 (默认5)")
    tk.add_argument("--json-output", action="store_true",
                    help="结构化输出: 结束时打印 JSON(final_answer/tool_calls/session_id)，供 benchmark/harness 解析")
    tk.set_defaults(func=cmd_task)

    # start/stop/status/evolve/web
    st = sub.add_parser("start", help="启动服务")
    st.add_argument("-p","--port", type=int)
    st.add_argument("-c","--config")
    st.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="停止服务").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="状态").set_defaults(func=cmd_status)

    # password
    pw = sub.add_parser("password", help="Web UI 登录密码管理 (set/clear/status)")
    pw.add_argument("password_action", choices=["set","clear","status"], help="set|clear|status")
    pw.add_argument("password", nargs="?", help="新密码 (仅 set 需要)")
    pw.set_defaults(func=cmd_password)

    sub.add_parser("setup", help="首次配置向导 (交互式)").set_defaults(func=cmd_setup)

    ev = sub.add_parser("evolve", help="自进化")
    ev.add_argument("--auto", action="store_true")
    ev.add_argument("-c","--config")
    ev.set_defaults(func=cmd_evolve)

    sub.add_parser("web", help="Web控制台").set_defaults(func=cmd_web)
    sub.add_parser("desktop", help="桌面客户端 (All-in-One)").set_defaults(func=cmd_desktop)
    
    # cron
    cr = sub.add_parser("cron", help="定时任务")
    cr.add_argument("cron_action", choices=["list","add","remove"])
    cr.add_argument("name", nargs="?", help="任务名")
    cr.add_argument("-s","--schedule", help="crontab表达式, 如 'every 30m'")
    cr.add_argument("-a","--action", help="触发事件")
    cr.set_defaults(func=cmd_cron)
    
    # search
    sr = sub.add_parser("search", help="Session搜索")
    sr.add_argument("query", nargs="?", help="搜索关键词")
    sr.add_argument("-n","--limit", type=int, default=10)
    sr.set_defaults(func=cmd_search)
    
    # browser
    br = sub.add_parser("browser", help="浏览器工具")
    br.add_argument("action", choices=["open","snap","click","type"])
    br.add_argument("target", nargs="?", help="URL/ref/selector")
    br.add_argument("--text", help="输入文本")
    br.set_defaults(func=cmd_browser)
    
    # tts
    tt = sub.add_parser("tts", help="语音合成")
    tt.add_argument("text", nargs="?", help="文本")
    tt.add_argument("-v","--voice", default="zh-CN-XiaoxiaoNeural")
    tt.add_argument("-o","--output")
    tt.set_defaults(func=cmd_tts)
    
    # profile
    pr = sub.add_parser("profile", help="多实例Profile管理")
    pr.add_argument("action", choices=["list","create","use","delete","clone","path"])
    pr.add_argument("name", nargs="?", help="Profile名")
    pr.add_argument("--target", help="克隆目标名")
    pr.set_defaults(func=cmd_profile)
    
    # approve
    ap = sub.add_parser("approve", help="命令审批配置")
    ap.add_argument("action", choices=["status","mode","check"])
    ap.add_argument("mode", nargs="?", choices=["manual","smart","off"])
    ap.set_defaults(func=cmd_approve)
    # completion
    cm = sub.add_parser("completion", help="Shell自动补全脚本")
    cm.add_argument("shell", choices=["bash","zsh","fish"])
    cm.set_defaults(func=cmd_completion)
    # mcp
    mc = sub.add_parser("mcp", help="MCP协议")
    mc.add_argument("action", choices=["serve","tools"])
    mc.set_defaults(func=cmd_mcp)

    # image
    img = sub.add_parser("image", help="AI图片生成 (DALL-E/Stable Diffusion)")
    img.add_argument("prompt", nargs="?", help="图片描述提示词")
    img.add_argument("--size", default="1024x1024", help="尺寸, 如 1024x1024")
    img.add_argument("--style", default=None, help="风格 (DALL-E: vivid/natural)")
    img.add_argument("--provider", default=None, help="指定provider (openai/stability)")
    img.set_defaults(func=cmd_image)

    # auth (v2.37 凭证池)
    au = sub.add_parser("auth", help="凭证池管理 (多Key轮转)")
    au.add_argument("action", choices=["list","add","remove","rotate","reset","stats","strategy","clear"],
                    help="list|add|remove|rotate|reset|stats|strategy|clear")
    au.add_argument("--provider", default="", help="Provider名称")
    au.add_argument("--key", default="", help="API Key")
    au.add_argument("--label", default="", help="Key标签")
    au.add_argument("--index", type=int, default=-1, help="Key索引")
    au.add_argument("--strategy", default="", help="轮转策略: round_robin|least_used|random")
    au.set_defaults(func=cmd_auth)

    # sessions (v2.37 会话管理)
    ss = sub.add_parser("sessions", help="会话管理 (重命名/清理/统计/浏览)")
    ss.add_argument("action", choices=["list","rename","delete","prune","stats","browse"],
                    help="list|rename|delete|prune|stats|browse")
    ss.add_argument("--id", default="", help="会话ID")
    ss.add_argument("--title", default="", help="新标题 (用于rename)")
    ss.add_argument("--days", type=int, default=30, help="清理N天前的会话 (默认30)")
    ss.add_argument("--search", default="", help="搜索关键词 (用于browse)")
    ss.set_defaults(func=cmd_sessions)

    # insights (v2.38 使用洞察)
    ins = sub.add_parser("insights", help="使用洞察分析 (对标Hermes insights)")
    ins.add_argument("--days", type=int, default=30, help="统计天数 (默认30)")
    ins.add_argument("--period", default="all", choices=["today","weekly","monthly","all"],
                     help="统计周期")
    ins.set_defaults(func=cmd_insights)

    # ── v2.44-v2.50 新模块CLI ─────────────────────────────
    # diff (v2.44)
    df = sub.add_parser("diff", help="文件Diff预览 (对标Claude Code)")
    df_sub = df.add_subparsers(dest="diff_cmd")
    df_sub.add_parser("preview", help="预览文件修改diff").add_argument("file", help="文件路径")
    df_sub.add_parser("history", help="diff历史")
    df_sub.add_parser("backups", help="回滚备份列表")
    df.set_defaults(func=cmd_diff)

    # tasks (v2.45)
    tk = sub.add_parser("tasks", help="后台任务管理")
    tk_sub = tk.add_subparsers(dest="task_cmd")
    tk_sub.add_parser("list", help="列出活跃任务")
    tk_sub.add_parser("history", help="已完成任务历史")
    tk_sub.add_parser("stats", help="任务统计")
    tk.set_defaults(func=cmd_tasks)

    # sdb (v2.46)
    sd = sub.add_parser("sdb", help="SDB框架 (随机-确定性边界)")
    sd_sub = sd.add_subparsers(dest="sdb_cmd")
    sd_sub.add_parser("stats", help="SDB统计")
    t = sd_sub.add_parser("test", help="测试SDB管道")
    t.add_argument("--action", default="test", help="动作")
    t.add_argument("--pass-check", type=bool, default=True, help="是否通过验证")
    sd_sub.add_parser("reliability", help="可靠性评分")
    sd.set_defaults(func=cmd_sdb)

    # brain (v2.48)
    br = sub.add_parser("brain", help="脑状态验证 (13维度量化)")
    br_sub = br.add_subparsers(dest="brain_cmd")
    br_sub.add_parser("profile", help="恢复画像")
    br_sub.add_parser("measure", help="测量全部13维度")
    br.set_defaults(func=cmd_brain)

    # modify (v2.47)
    mo = sub.add_parser("modify", help="自修改代码引擎")
    mo_sub = mo.add_subparsers(dest="modify_cmd")
    mo_sub.add_parser("analyze", help="分析源码").add_argument("path", nargs="?", default="src/", help="文件或目录")
    mo_sub.add_parser("history", help="变更历史")
    mo_sub.add_parser("stats", help="引擎统计")
    mo.set_defaults(func=cmd_modify)

    # review (P0-4: 代码审查，对标Goose review)
    rv = sub.add_parser("review", help="代码审查 (对标Goose review)")
    rv.add_argument("path", help="文件或目录路径")
    rv.add_argument("--ai", action="store_true", help="启用AI深度审查 (需要LLM)")
    rv.add_argument("--max-issues", type=int, default=30, help="显示的最大问题数 (默认30)")
    rv.set_defaults(func=cmd_review)

    # loop (v2.50)
    lo = sub.add_parser("loop", help="统一OODA循环测试")
    lo.add_argument("input", nargs="*", help="测试输入")
    lo.add_argument("--iterations", type=int, default=1, help="迭代次数")
    lo.set_defaults(func=cmd_loop)

    args = p.parse_args()
    if not args.command:
        # 默认: 启动 Web 服务 (双击 .exe 的行为)
        import uvicorn, webbrowser, threading, time
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        def _open_browser():
            time.sleep(2)
            webbrowser.open(f"http://127.0.0.1:{_get_port()}/ui/chat")
        
        if sys.platform == "win32":
            threading.Thread(target=_open_browser, daemon=True).start()
        
        from src.main import app
        host = os.environ.get("MESHCTX_HOST", "0.0.0.0")
        port = int(os.environ.get("MESHCTX_PORT", "3001"))
        uvicorn.run(app, host=host, port=port, log_level="info", timeout_keep_alive=300)
        return
    args.func(args)


if __name__ == "__main__":
    main()
