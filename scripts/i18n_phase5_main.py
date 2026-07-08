#!/usr/bin/env python3
"""i18n Phase 5 v2: Direct JSON manipulation — no lazy TRANSLATIONS proxy"""
import re, json, os

os.chdir(os.path.join(os.path.dirname(__file__), '..'))

# Load translations from JSON directly
with open('src/i18n_translations.json', encoding='utf-8') as f:
    trans = json.load(f)

ERROR_KEYS = {
    "请求body需为JSON": "error_body_must_be_json",
    "无效的JSON请求体": "error_invalid_json_body",
    "无配置文件": "error_no_config",
    "请提供 code 参数": "error_missing_code_param",
    "请提供 q 参数": "error_missing_q_param",
    "请提供 message": "error_missing_message",
    "对话不存在": "error_conversation_not_found",
    "插件注册表不存在": "error_plugin_registry_not_found",
    "密码错误": "error_wrong_password",
    "配置文件不存在，请先添加模型": "error_no_config_add_model",
    "配置文件不存在": "error_config_not_found",
    "请提供搜索词 q 参数": "error_missing_search_q",
    "请提供飞书webhook地址": "error_missing_feishu_webhook",
    "请提供webhook_url和content": "error_missing_webhook_params",
    "请提供 command 参数": "error_missing_command",
    "请提供 url 参数": "error_missing_url",
    "请提供 path 参数": "error_missing_path",
    "请提供 files 参数": "error_missing_files",
    "请提供文件路径 path 参数": "error_missing_file_path",
    "安全限制: 路径中禁止包含 ..": "error_path_traversal_blocked",
    "路径是目录无法写入": "error_path_is_directory",
    "content 不能为空": "error_content_empty",
    "请提供 url": "error_missing_url_short",
    "代码为空": "error_code_empty",
    "无效JSON": "error_invalid_json",
    "请提供 code": "error_missing_code_short",
    "请求体不能为空，需要提供 description 字段": "error_missing_description",
    "id 和 provider 为必填项": "error_id_provider_required",
    "请使用 POST body": "error_use_post_body",
}

EN_MAP = {
    "error_body_must_be_json": "Request body must be JSON",
    "error_invalid_json_body": "Invalid JSON request body",
    "error_no_config": "No configuration file",
    "error_missing_code_param": "Missing 'code' parameter",
    "error_missing_q_param": "Missing 'q' parameter",
    "error_missing_message": "Missing 'message' field",
    "error_conversation_not_found": "Conversation not found",
    "error_plugin_registry_not_found": "Plugin registry not found",
    "error_wrong_password": "Wrong password",
    "error_no_config_add_model": "Config not found, add a model first",
    "error_config_not_found": "Configuration file not found",
    "error_missing_search_q": "Missing search query parameter",
    "error_missing_feishu_webhook": "Missing Feishu webhook URL",
    "error_missing_webhook_params": "Missing webhook_url and content",
    "error_missing_command": "Missing 'command' parameter",
    "error_missing_url": "Missing 'url' parameter",
    "error_missing_path": "Missing 'path' parameter",
    "error_missing_files": "Missing 'files' parameter",
    "error_missing_file_path": "Missing file path parameter",
    "error_path_traversal_blocked": "Security: path traversal blocked",
    "error_path_is_directory": "Path is a directory, cannot write",
    "error_content_empty": "Content cannot be empty",
    "error_missing_url_short": "Missing 'url'",
    "error_code_empty": "Code cannot be empty",
    "error_invalid_json": "Invalid JSON",
    "error_missing_code_short": "Missing 'code'",
    "error_missing_description": "Missing 'description' field",
    "error_id_provider_required": "ID and provider are required",
    "error_use_post_body": "Use POST body",
}

# Add keys to translations
for key, zh in ERROR_KEYS.items():
    trans['zh'][key] = zh
    trans['en'][key] = EN_MAP.get(key, f'[EN] {zh}')
    for lc in ['ja', 'ko', 'fr', 'de', 'es']:
        prefix = {'ja': '[JA]', 'ko': '[KO]', 'fr': '[FR]', 'de': '[DE]', 'es': '[ES]'}[lc]
        trans[lc][key] = f'{prefix} {zh[:60]}'

# Save translations
with open('src/i18n_translations.json', 'w', encoding='utf-8') as f:
    json.dump(trans, f, ensure_ascii=False, indent=2)
print(f"Added {len(ERROR_KEYS)} keys. Total: {len(trans['zh'])}")

# Replace in main.py
with open('src/main.py') as f:
    content = f.read()

count = 0
for zh, key in ERROR_KEYS.items():
    escaped = re.escape(zh)
    # Replace: HTTPException(N, "中文") or ('中文')  → HTTPException(N, t('key'))
    pattern = rf'(HTTPException\(\d+,\s*)"{escaped}"'
    repl = rf"\1t('{key}')"
    new, n = re.subn(pattern, repl, content)
    if n > 0:
        count += n
        content = new
    # Also single-quoted variant
    pattern2 = rf"(HTTPException\(\d+,\s*)'{escaped}'"
    new2, n2 = re.subn(pattern2, repl, content)
    if n2 > 0:
        count += n2
        content = new2

with open('src/main.py', 'w') as f:
    f.write(content)

print(f"Replaced {count} error messages in main.py")
