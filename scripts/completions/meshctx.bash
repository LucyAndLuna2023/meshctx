#!/usr/bin/env bash
# =============================================================================
# meshctx Bash 自动补全脚本
# =============================================================================
#
# 安装方法:
#   source <(meshctx completion bash)
#   或复制到: ~/.bash_completion  (Bash 4.1+)
#   或复制到: ~/.local/share/bash-completion/completions/meshctx
#
# =============================================================================

_meshctx_completion() {
    local cur prev words cword
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    words=("${COMP_WORDS[@]}")
    cword=$COMP_CWORD

    # -- 顶层子命令列表
    local commands="model skill chat start stop status setup evolve web desktop cron search browser tts mcp profile approve"

    # -- 子命令 -> 子动作映射
    local model_actions="list test use scan available add"
    local skill_actions="list create delete auto"
    local cron_actions="list add remove"
    local profile_actions="list create use delete clone path"
    local approve_actions="status mode check"
    local browser_actions="open snap click type"
    local mcp_actions="serve tools"

    # -- 全局选项
    local global_opts="--version --help --yolo --profile"

    # 找到当前命令词（跳过 meshctx 本身）
    local cmd=""
    local subcmd=""
    local i=1
    while [[ $i -lt $cword ]]; do
        local w="${words[$i]}"
        if [[ "$w" != -* ]]; then
            if [[ -z "$cmd" ]]; then
                cmd="$w"
            elif [[ -z "$subcmd" ]]; then
                subcmd="$w"
            fi
        fi
        ((i++))
    done

    # 情况1: 还没输入子命令 → 补全子命令 + 全局选项
    if [[ -z "$cmd" ]]; then
        COMPREPLY=($(compgen -W "$commands $global_opts" -- "$cur"))
        return
    fi

    # 情况2: 已输入子命令但没有子动作 → 看是否需要子动作
    case "$cmd" in
        model)
            if [[ -z "$subcmd" ]]; then
                COMPREPLY=($(compgen -W "$model_actions $global_opts" -- "$cur"))
                return
            fi
            ;;
        skill)
            if [[ -z "$subcmd" ]]; then
                COMPREPLY=($(compgen -W "$skill_actions $global_opts" -- "$cur"))
                return
            fi
            ;;
        cron)
            if [[ -z "$subcmd" ]]; then
                COMPREPLY=($(compgen -W "$cron_actions $global_opts" -- "$cur"))
                return
            fi
            ;;
        profile)
            if [[ -z "$subcmd" ]]; then
                COMPREPLY=($(compgen -W "$profile_actions $global_opts" -- "$cur"))
                return
            fi
            ;;
        approve)
            if [[ -z "$subcmd" ]]; then
                COMPREPLY=($(compgen -W "$approve_actions $global_opts" -- "$cur"))
                return
            fi
            ;;
        browser)
            if [[ -z "$subcmd" ]]; then
                COMPREPLY=($(compgen -W "$browser_actions $global_opts" -- "$cur"))
                return
            fi
            ;;
        mcp)
            if [[ -z "$subcmd" ]]; then
                COMPREPLY=($(compgen -W "$mcp_actions $global_opts" -- "$cur"))
                return
            fi
            ;;
        # 这些子命令接受文件名/值, 不补全子动作, 只补全全局选项
        chat|start|stop|status|setup|evolve|web|desktop|search|tts)
            COMPREPLY=($(compgen -W "$global_opts" -- "$cur"))
            return
            ;;
    esac

    # 情况3: 已有子动作 → 补全全局选项
    COMPREPLY=($(compgen -W "$global_opts" -- "$cur"))
}

complete -F _meshctx_completion meshctx
