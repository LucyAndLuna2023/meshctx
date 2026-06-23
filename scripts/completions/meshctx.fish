# =============================================================================
# meshctx Fish 自动补全脚本
# =============================================================================
#
# 安装方法:
#   meshctx completion fish | source
#   或复制到: ~/.config/fish/completions/meshctx.fish
#      cp scripts/completions/meshctx.fish ~/.config/fish/completions/
#
# =============================================================================

# -- 全局选项 (会出现在所有子命令中)
set -l global_opts '--version' '--help' '--yolo' '--profile'

# -- 顶层子命令
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "model"       -d "模型管理"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "skill"       -d "Skill管理"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "chat"        -d "对话"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "start"       -d "启动服务"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "stop"        -d "停止服务"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "status"      -d "状态"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "setup"       -d "首次配置向导"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "evolve"      -d "自进化"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "web"         -d "Web控制台"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "desktop"     -d "桌面客户端"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "cron"        -d "定时任务"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "search"      -d "Session搜索"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "browser"     -d "浏览器工具"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "tts"         -d "语音合成"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "mcp"         -d "MCP协议"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "profile"     -d "多实例管理"
complete -c meshctx -f -n "not __fish_seen_subcommand_from model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve" \
    -a "approve"     -d "命令审批"

# -- 每个子命令的子动作

# model
complete -c meshctx -f -n "__fish_seen_subcommand_from model; and not __fish_seen_subcommand_from list test use scan available add" \
    -a "list"       -d "列出已配置模型"
complete -c meshctx -f -n "__fish_seen_subcommand_from model; and not __fish_seen_subcommand_from list test use scan available add" \
    -a "test"       -d "测试模型"
complete -c meshctx -f -n "__fish_seen_subcommand_from model; and not __fish_seen_subcommand_from list test use scan available add" \
    -a "use"        -d "切换默认模型"
complete -c meshctx -f -n "__fish_seen_subcommand_from model; and not __fish_seen_subcommand_from list test use scan available add" \
    -a "scan"       -d "自动扫描环境变量"
complete -c meshctx -f -n "__fish_seen_subcommand_from model; and not __fish_seen_subcommand_from list test use scan available add" \
    -a "available"  -d "查看内置模型目录"
complete -c meshctx -f -n "__fish_seen_subcommand_from model; and not __fish_seen_subcommand_from list test use scan available add" \
    -a "add"        -d "添加模型"

# skill
complete -c meshctx -f -n "__fish_seen_subcommand_from skill; and not __fish_seen_subcommand_from list create delete auto" \
    -a "list"       -d "列出Skills"
complete -c meshctx -f -n "__fish_seen_subcommand_from skill; and not __fish_seen_subcommand_from list create delete auto" \
    -a "create"     -d "创建Skill"
complete -c meshctx -f -n "__fish_seen_subcommand_from skill; and not __fish_seen_subcommand_from list create delete auto" \
    -a "delete"     -d "删除Skill"
complete -c meshctx -f -n "__fish_seen_subcommand_from skill; and not __fish_seen_subcommand_from list create delete auto" \
    -a "auto"       -d "自动生成Skill"

# cron
complete -c meshctx -f -n "__fish_seen_subcommand_from cron; and not __fish_seen_subcommand_from list add remove" \
    -a "list"       -d "列出任务"
complete -c meshctx -f -n "__fish_seen_subcommand_from cron; and not __fish_seen_subcommand_from list add remove" \
    -a "add"        -d "添加任务"
complete -c meshctx -f -n "__fish_seen_subcommand_from cron; and not __fish_seen_subcommand_from list add remove" \
    -a "remove"     -d "删除任务"

# profile
complete -c meshctx -f -n "__fish_seen_subcommand_from profile; and not __fish_seen_subcommand_from list create use delete clone path" \
    -a "list"       -d "列出Profiles"
complete -c meshctx -f -n "__fish_seen_subcommand_from profile; and not __fish_seen_subcommand_from list create use delete clone path" \
    -a "create"     -d "创建Profile"
complete -c meshctx -f -n "__fish_seen_subcommand_from profile; and not __fish_seen_subcommand_from list create use delete clone path" \
    -a "use"        -d "切换Profile"
complete -c meshctx -f -n "__fish_seen_subcommand_from profile; and not __fish_seen_subcommand_from list create use delete clone path" \
    -a "delete"     -d "删除Profile"
complete -c meshctx -f -n "__fish_seen_subcommand_from profile; and not __fish_seen_subcommand_from list create use delete clone path" \
    -a "clone"      -d "克隆Profile"
complete -c meshctx -f -n "__fish_seen_subcommand_from profile; and not __fish_seen_subcommand_from list create use delete clone path" \
    -a "path"       -d "查看路径"

# approve
complete -c meshctx -f -n "__fish_seen_subcommand_from approve; and not __fish_seen_subcommand_from status mode check" \
    -a "status"     -d "查看审批状态"
complete -c meshctx -f -n "__fish_seen_subcommand_from approve; and not __fish_seen_subcommand_from status mode check" \
    -a "mode"       -d "切换审批模式"
complete -c meshctx -f -n "__fish_seen_subcommand_from approve; and not __fish_seen_subcommand_from status mode check" \
    -a "check"      -d "检查命令是否需要审批"

# browser
complete -c meshctx -f -n "__fish_seen_subcommand_from browser; and not __fish_seen_subcommand_from open snap click type" \
    -a "open"       -d "打开URL"
complete -c meshctx -f -n "__fish_seen_subcommand_from browser; and not __fish_seen_subcommand_from open snap click type" \
    -a "snap"       -d "截图"
complete -c meshctx -f -n "__fish_seen_subcommand_from browser; and not __fish_seen_subcommand_from open snap click type" \
    -a "click"      -d "点击元素"
complete -c meshctx -f -n "__fish_seen_subcommand_from browser; and not __fish_seen_subcommand_from open snap click type" \
    -a "type"       -d "输入文本"

# mcp
complete -c meshctx -f -n "__fish_seen_subcommand_from mcp; and not __fish_seen_subcommand_from serve tools" \
    -a "serve"      -d "启动MCP服务"
complete -c meshctx -f -n "__fish_seen_subcommand_from mcp; and not __fish_seen_subcommand_from serve tools" \
    -a "tools"      -d "列出工具"

# -- 全局选项 (在所有上下文可用)
for opt in $global_opts
    complete -c meshctx -l (string replace '--' '' $opt) -d "全局选项"
end
