#!/usr/bin/env python3
"""i18n Phase 5b: Replace hardcoded Chinese print() in cli.py with t() calls"""
import re, json, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

with open('src/i18n_translations.json', encoding='utf-8') as f:
    trans = json.load(f)

# CLI-specific keys
CLI_KEYS = {
    "文件Diff预览": "cli_diff_preview",
    "统一OODA循环测试": "cli_ooda_test",
    "一样好用的命令行": "cli_tagline",
    "一键扫描环境变量": "cli_scan_env",
    "自动配置所有模型": "cli_auto_config",
    "测试当前模型": "cli_test_model",
    "确保API Key已从": "cli_ensure_api_key",
    "加载到环境变量": "cli_load_env",
    "未发现任何 API Key": "cli_no_api_key",
    "暂无已配置模型": "cli_no_models",
    "用一句话介绍你自己": "cli_intro_prompt",
    "默认模型已切换为": "cli_model_switched",
    "暂无 Skill": "cli_no_skills",
    "重启 meshctx 后生效": "cli_restart_生效",
    "重启后生效": "cli_restart_生效_short",
    "已配置！重启后生效": "cli_configured_restart",
    "飞书已配置！重启后生效": "cli_feishu_configured",
    "无可用模型": "cli_no_available_models",
    "和 corp_secret 不能为空": "cli_corp_secret_required",
    "请从企业微信管理后台获取以下参数": "cli_wechat_params",
    "消息平台接入配置": "cli_platform_config",
    "交互式配置消息平台接入": "cli_interactive_config",
    "像 Hermes 一样通过聊天配置": "cli_hermes_config",
    "你本地有完整的文件系统访问权限，不是云端": "cli_local_fs",
}

# Add to translations
for key, zh in CLI_KEYS.items():
    trans['zh'][key] = zh
    trans['en'][key] = f'[EN] {zh[:60]}'
    for lc in ['ja', 'ko', 'fr', 'de', 'es']:
        p = {'ja': '[JA]', 'ko': '[KO]', 'fr': '[FR]', 'de': '[DE]', 'es': '[ES]'}[lc]
        trans[lc][key] = f'{p} {zh[:50]}'

with open('src/i18n_translations.json', 'w', encoding='utf-8') as f:
    json.dump(trans, f, ensure_ascii=False, indent=2)

# Replace in cli.py
with open('src/cli.py') as f:
    content = f.read()

count = 0
for zh, key in CLI_KEYS.items():
    escaped = re.escape(zh)
    for quote in ['"', "'"]:
        pattern = rf'{quote}{escaped}{quote}'
        repl = f"t('{key}')"
        new, n = re.subn(pattern, repl, content)
        if n > 0:
            count += n
            content = new

with open('src/cli.py', 'w') as f:
    f.write(content)

print(f"Added {len(CLI_KEYS)} keys ({len(trans['zh'])} total). Replaced {count} strings in cli.py")
