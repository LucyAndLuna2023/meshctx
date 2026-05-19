#compdef meshctx
# =============================================================================
# meshctx Zsh 自动补全脚本
# =============================================================================
#
# 安装方法:
#   source <(meshctx completion zsh)
#   或复制到: ~/.zsh/completions/  (需在 fpath 中)
#      mkdir -p ~/.zsh/completions
#      cp scripts/completions/meshctx.zsh ~/.zsh/completions/_meshctx
#      echo 'fpath=(~/.zsh/completions $fpath)' >> ~/.zshrc
#      echo 'autoload -Uz compinit && compinit' >> ~/.zshrc
#
# =============================================================================

_meshctx() {
    local -a commands
    commands=(
        'model:模型管理 (30+内置)'
        'skill:Skill管理'
        'chat:对话'
        'start:启动服务'
        'stop:停止服务'
        'status:状态'
        'setup:首次配置向导'
        'evolve:自进化'
        'web:Web控制台'
        'desktop:桌面客户端'
        'cron:定时任务'
        'search:Session搜索'
        'browser:浏览器工具'
        'tts:语音合成'
        'mcp:MCP协议'
        'profile:多实例Profile管理'
        'approve:命令审批配置'
    )

    local -a global_opts
    global_opts=(
        '--version[显示版本]'
        '--help[显示帮助]'
        '--yolo[跳过审批]'
        '--profile[指定Profile]'
    )

    _arguments -C \
        '1: :{_describe "command" commands}' \
        '*:: :->args' \
        && return

    case "$state" in
        args)
            local cmd="${words[1]}"
            case "$cmd" in
                model)
                    _arguments \
                        '1:action:((list\:"列出已配置" test\:"测试模型" use\:"切换默认模型" scan\:"自动扫描环境变量" available\:"查看内置模型" add\:"添加模型"))' \
                        '*::optional:->model_extra' \
                        && return
                    ;;
                skill)
                    _arguments \
                        '1:action:((list\:"列出Skills" create\:"创建Skill" delete\:"删除Skill" auto\:"自动生成Skill"))' \
                        && return
                    ;;
                cron)
                    _arguments \
                        '1:action:((list\:"列出任务" add\:"添加任务" remove\:"删除任务"))' \
                        && return
                    ;;
                profile)
                    _arguments \
                        '1:action:((list\:"列出Profiles" create\:"创建Profile" use\:"切换Profile" delete\:"删除Profile" clone\:"克隆Profile" path\:"查看路径"))' \
                        && return
                    ;;
                approve)
                    _arguments \
                        '1:action:((status\:"查看状态" mode\:"切换模式" check\:"检查命令"))' \
                        && return
                    ;;
                browser)
                    _arguments \
                        '1:action:((open\:"打开URL" snap\:"截图" click\:"点击" type\:"输入"))' \
                        && return
                    ;;
                mcp)
                    _arguments \
                        '1:action:((serve\:"启动MCP服务" tools\:"列出工具"))' \
                        && return
                    ;;
                *)
                    _arguments \
                        $global_opts \
                        && return
                    ;;
            esac
            ;;
        model_extra)
            _arguments \
                $global_opts \
                '--key[API Key]' \
                '--model[实际模型名]' \
                '--base-url[API地址]' \
                '-p[测试提示词]' \
                '--prompt[测试提示词]' \
                '-c[配置文件]' \
                '--config[配置文件]' \
                && return
            ;;
    esac
}

_meshctx "$@"
