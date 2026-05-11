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
import json
import os
import sys
from pathlib import Path


# ═══════════════════════════════════════════════════
# model 命令 — 30+模型, 一行配置
# ═══════════════════════════════════════════════════

def cmd_model(args):
    from src.model_registry import get_registry, BUILTIN_MODELS

    reg = get_registry(args.config)

    if args.model_action == "scan":
        print("🔍 扫描环境变量...")
        entries = reg.auto_configure()
        if not entries:
            print("未发现任何 API Key。请设置环境变量，例如:")
            print("  export BAILIAN_API_KEY=sk-xxx")
            print("  export DEEPSEEK_API_KEY=sk-xxx")
        else:
            print(f"✅ 自动配置 {len(entries)} 个模型:")
            for e in entries:
                print(f"   {e['id']:<30} {'✓' if e['ready'] else '⚠缺Key'}")

    elif args.model_action == "list":
        entries = reg.list_all()
        if not entries:
            print("暂无已配置模型。运行 'meshctx model scan' 自动扫描")
        else:
            print(f"\n{'模型ID':<30} {'Provider':<12} {'实际模型':<28} 状态")
            print("-" * 85)
            for e in entries:
                s = "✓ 就绪" if e['ready'] else "⚠ 缺Key"
                print(f"{e['id']:<30} {e['provider']:<12} {e['model']:<28} {s}")

    elif args.model_action == "available":
        print(f"\n内置模型目录 ({len(BUILTIN_MODELS)} 个):\n")
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
            print("用法: meshctx model add <provider:model> [--key KEY] [--model MODEL] [--base-url URL]")
            print("示例: meshctx model add deepseek:chat --key sk-xxx")
            return
        cfg = reg.add(model_id, key=args.key or "", model=args.model or "", base_url=args.base_url or "")
        status = "✓" if cfg.get("key") else "⚠ 需要 API Key"
        print(f"模型已添加: {model_id} {status}")

    elif args.model_action == "test":
        client = reg.get(args.model_id)
        if not client:
            print(f"模型 '{args.model_id or '默认'}' 未配置。")
            print("运行 'meshctx model scan' 自动扫描，或 'meshctx model add' 手动添加")
            return
        prompt = args.prompt or "用一句话介绍你自己"
        print(f"🧪 测试 {client.model_id} ({client.model_name})...")
        print(f"Q: {prompt}")
        resp = client.chat([{"role": "user", "content": prompt}])
        print(f"A: {resp['content']}")
        print(f"   Tokens: {resp['tokens']}")

    elif args.model_action == "use":
        # 设置默认模型(写到环境或配置)
        model_id = args.model_id
        if model_id not in reg._entries:
            print(f"模型 '{model_id}' 未配置。先运行 'meshctx model add {model_id}'")
            return
        os.environ["MESHCTX_MODEL"] = model_id
        print(f"✅ 默认模型已切换为: {model_id}")


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
            print("暂无 Skill。创建: meshctx skill create <name> -d '描述'")
        else:
            print(f"\n{'Skill':<30} {'来源':<10} {'使用':<6} {'成功率':<8} 描述")
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
        print(f"✓ Skill 已创建: {args.name}")

    elif args.skill_action == "delete":
        if mgr.delete(args.name):
            print(f"✓ 已删除: {args.name}")
        else:
            print(f"✗ 不存在: {args.name}")

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
            print(f"✓ 自动生成 Skill: {skill.name}")


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
        print("\n📱 企业微信配置")
        print("请从企业微信管理后台获取以下参数：")
        print("  企业ID: 管理后台 → 我的企业 → 企业信息")
        print("  应用Secret: 应用管理 → 自建应用 → 查看Secret")
        print("  AgentId: 应用管理 → 自建应用 → AgentId\n")
        
        try:
            corp_id = input("企业ID (corp_id): ").strip()
            corp_secret = input("应用Secret (corp_secret): ").strip()
            agent_id = input("AgentId: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("已取消")
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
            print("❌ corp_id 和 corp_secret 不能为空")
    
    elif choice == "2":
        print("\n📱 飞书配置")
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
            print(f"✅ 飞书已配置！重启后生效")
    
    elif choice == "3":
        print("\n📱 Telegram 配置")
        try:
            bot_token = input("Bot Token: ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        
        if bot_token:
            config.setdefault("gateway", {})["enabled"] = True
            config["gateway"]["telegram"] = {"bot_token": bot_token}
            with open(config_path, "w") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            print(f"✅ Telegram 已配置！重启后生效")


def cmd_chat(args):
    from src.model_registry import get_registry

    reg = get_registry(args.config)
    model_id = args.model or os.environ.get("MESHCTX_MODEL")
    client = reg.get(model_id)

    if not client:
        print("无可用模型。运行 'meshctx model scan' 自动扫描")
        return

    print(f"🤖 meshctx → {client.model_id}  /quit退出 /models列表 /model<id>切换 /gateway配置平台\n")

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    else:
        # 检测运行环境
        import platform
        is_wsl = "microsoft" in platform.uname().release.lower()
        wsl_info = ""
        if is_wsl:
            wsl_info = """
⚠️ 你正运行在 WSL (Windows Subsystem for Linux) 环境中。
   Windows 文件路径映射:
     C:\\ → /mnt/c/      D:\\ → /mnt/d/      E:\\ → /mnt/e/
   用户可以访问 Windows 文件，如 /mnt/e/file.txt。
   你本地有完整的文件系统访问权限，不是云端！"""
        
        from src.soul import get_soul_prompt
        soul_prompt = get_soul_prompt()
        
        messages.append({"role": "system", "content": f"""你是 meshctx 助手，运行在用户本地机器。

你有完整的本地文件系统访问权限，可以读写文件。
{wsl_info}

{soul_prompt}
你可以使用以下工具（在回复中用JSON格式调用）:
  read_file: 读取文件。参数: path
  write_file: 写入文件。参数: path, content
  list_dir: 列出目录。参数: path
  run_cmd: 执行终端命令。参数: cmd
  search_files: 搜索文件内容。参数: pattern, path, glob
  web_search: 搜索网页。参数: query

调用格式示例:
{{"tool": "read_file", "path": "/mnt/e/file.txt"}}

重要规则:
- 用户让你读文件/查代码/执行命令时，直接使用工具！不要说"我无法访问"
- 工具执行后你会收到结果，基于结果回复用户
- 回复简洁有用，中文优先"""})

    while True:
        try:
            user = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user:
            continue
        if user == "/quit":
            break
        if user == "/gateway":
            _cmd_gateway_setup()
            continue
        if user == "/models" or user == "/model":
            entries = reg.list_all()
            print(f"\n  {'模型ID':<25} {'状态':<8} 说明")
            print(f"  {'-'*50}")
            for e in entries:
                status = "✓" if e['ready'] else "✗"
                desc = {"deepseek:v4-pro":"🏆 最新最強 V4","deepseek:v4-flash":"⚡ 极速 V4","deepseek:chat":"V3 稳定","deepseek:reasoner":"🧠 R1 推理"}.get(e['id'], "")
                print(f"  {e['id']:<25} {status:<8} {desc}")
            print()
            continue
        if user.startswith("/model "):
            new_id = user.split(" ", 1)[1].strip()
            new_client = reg.get(new_id)
            if new_client:
                client = new_client
                print(f"✅ 已切换 → {client.model_id} ({client.model_name})\n")
            else:
                print(f"❌ 模型 '{new_id}' 不可用。输入 /models 查看可选模型\n")
            continue

        messages.append({"role": "user", "content": user})
        
        # 自动翻译 Windows 路径 → WSL 路径
        import re as _re
        if _re.search(r'[A-Z]:\\', user):
            def _translate_path(m):
                return '/mnt/' + m.group(1).lower() + '/'
            wsl_user = _re.sub(r'([A-Z]):\\', _translate_path, user).replace('\\', '/')
            if wsl_user != user:
                messages[-1]["content"] = wsl_user + "\n[WSL路径: " + wsl_user + "]"
        
        from src.chat_tools import execute_tool, has_tool_call
        max_turns = 3
        for _ in range(max_turns):
            print("meshctx> ", end="", flush=True)
            resp = client.chat(messages)
            text = resp["content"]
            
            # 安全打印
            try:
                print(text)
            except UnicodeEncodeError:
                print(text.encode('utf-8', errors='surrogateescape').decode('utf-8', errors='replace'))
            
            messages.append({"role": "assistant", "content": text})
            
            # 检测工具调用
            if has_tool_call(text):
                result = execute_tool(text)
                if result:
                    print(f"\n🔧 {result[:200]}")
                    messages.append({"role": "user", "content": f"[工具执行结果]\n{result}\n\n请基于以上结果回复用户。"})
                    continue
            break
        
        if len(messages) > 30:
            messages = messages[-30:]


# ═══════════════════════════════════════════════════
# start / stop / status
# ═══════════════════════════════════════════════════

def cmd_start(args):
    """启动 meshctx v1.0 统一服务"""
    import uvicorn
    from src.main import app
    
    port = args.port or 3000
    host = '0.0.0.0'
    
    print(f"""
╔══════════════════════════════════════╗
║       meshctx v1.2 已启动           ║
╠══════════════════════════════════════╣
║  API:     http://localhost:{port}     ║
║  Docs:    http://localhost:{port}/docs║
║  Web UI:  http://localhost:{port}/ui ║
╚══════════════════════════════════════╝
    """)
    
    uvicorn.run(app, host=host, port=port, log_level="info")


def cmd_stop(args):
    import subprocess
    r = subprocess.run(["pkill", "-f", "uvicorn.*src.main"], capture_output=True)
    print("meshctx 已停止" if r.returncode == 0 else "未找到运行中的 meshctx")


def cmd_status(args):
    try:
        import requests
        r = requests.get("http://localhost:8000/health", timeout=3)
        d = r.json()
        print(f"meshctx v{d.get('version','?')} 运行中  "
              f"项目:{d.get('projects_count',0)} 会话:{d.get('conversations_count',0)} 记忆:{d.get('memories_count',0)}")
    except:
        print("meshctx 未运行。meshctx start 启动")


def cmd_evolve(args):
    from src.skill_manager import SkillManager
    from src.model_registry import get_registry

    mgr = SkillManager()
    reg = get_registry()

    print("🧬 自进化循环\n")
    stats = mgr.stats()
    print(f"Skills: {stats['total']}个 (自动生成{stats['auto_created']})")

    if reg._entries:
        client = reg.get(None)
        if client:
            resp = client.chat([{"role":"user","content":"根据这些Skill数据提出3条优化建议:" + json.dumps(stats,ensure_ascii=False)}])
            print(f"💡 优化建议:\n{resp['content']}")

            if args.auto:
                skill = mgr.auto_create_from_pattern({"task_pattern":"自动优化","avg_quality":0.8,"frequency":3})
                if skill:
                    print(f"✅ 自动创建: {skill.name}")

    print("✨ 完成")


def cmd_web(args):
    import webbrowser
    webbrowser.open("http://localhost:8000/ui")


def cmd_cron(args):
    """Cron 定时任务管理"""
    from src.cron import CronPlugin
    cron = CronPlugin()
    cron._jobs = {}  # 轻量实例
    
    if args.cron_action == "list":
        print("暂无定时任务。添加: meshctx cron add <name> -s 'every 1h'")
    elif args.cron_action == "add" and args.name:
        cron.add_job(args.name, args.schedule or "every 1h", args.action or "")
        print(f"✓ 已添加: {args.name} ({args.schedule})")


def cmd_search(args):
    """Session 搜索"""
    from src.session_search import SessionSearchEngine
    engine = SessionSearchEngine()
    
    if not args.query:
        recent = engine.get_recent(args.limit)
        if not recent:
            print("暂无已索引会话")
        else:
            for s in recent:
                print(f"  {s['title'][:50]} ({s['message_count']}条消息)")
        return
    
    results = engine.search(args.query, args.limit)
    if not results:
        print(f"未找到: {args.query}")
    else:
        for r in results:
            print(f"  [{r.score:.0%}] {r.title[:50]}")


def cmd_browser(args):
    """Browser 工具"""
    print("Browser 工具需要: pip install playwright && playwright install chromium")
    if args.action == "open" and args.target:
        print(f"打开: {args.target}")


def cmd_tts(args):
    """TTS 语音合成"""
    from src.tts import TTSEngine
    import asyncio
    
    if not args.text:
        print("用法: meshctx tts '要合成的文本'")
        return
    
    async def run():
        engine = TTSEngine("edge")
        path = await engine.synthesize(args.text, args.voice)
        print(f"✓ 语音已生成: {path}")
    
    asyncio.run(run())


def cmd_mcp(args):
    """MCP 协议"""
    from src.mcp_server import MCPServer
    
    if args.action == "tools":
        server = MCPServer()
        print(f"MCP 工具 ({len(server._tools)}个):")
        for name, tool in server._tools.items():
            print(f"  {name}: {tool.description}")
    elif args.action == "serve":
        print("MCP stdio 服务器启动中... (用于 Claude Desktop / Cursor)")
        server = MCPServer()
        import asyncio
        asyncio.run(server.run_stdio())



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
    c = sub.add_parser("chat", help="对话")
    c.add_argument("-m","--model", help="模型ID")
    c.add_argument("-s","--system", help="系统提示")
    c.add_argument("-c","--config")
    c.set_defaults(func=cmd_chat)

    # start/stop/status/evolve/web
    st = sub.add_parser("start", help="启动服务")
    st.add_argument("-p","--port", type=int)
    st.add_argument("-c","--config")
    st.set_defaults(func=cmd_start)

    sub.add_parser("stop", help="停止服务").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="状态").set_defaults(func=cmd_status)

    ev = sub.add_parser("evolve", help="自进化")
    ev.add_argument("--auto", action="store_true")
    ev.add_argument("-c","--config")
    ev.set_defaults(func=cmd_evolve)

    sub.add_parser("web", help="Web控制台").set_defaults(func=cmd_web)
    
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
    
    # mcp
    mc = sub.add_parser("mcp", help="MCP协议")
    mc.add_argument("action", choices=["serve","tools"])
    mc.set_defaults(func=cmd_mcp)

    args = p.parse_args()
    if not args.command:
        # 默认: 启动 Web 服务 (双击 .exe 的行为)
        import uvicorn, webbrowser, threading, time
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        
        def _open_browser():
            time.sleep(2)
            webbrowser.open("http://127.0.0.1:3000/ui/chat")
        
        if sys.platform == "win32":
            threading.Thread(target=_open_browser, daemon=True).start()
        
        host = os.environ.get("MESHCTX_HOST", "0.0.0.0")
        port = int(os.environ.get("MESHCTX_PORT", "3000"))
        uvicorn.run(app, host=host, port=port, log_level="info")
        return
    args.func(args)


if __name__ == "__main__":
    main()
