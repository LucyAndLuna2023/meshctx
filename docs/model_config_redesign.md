# meshctx 模型配置重做 — 对标 deepseek harness / zcode 体验

> 用户指令: 现在太垃圾, 对标 harness/zcode 重做; 不行就参考 GitHub 上的开源实现。

## harness / zcode 的模型配置体验 (对标目标)

| 能力 | 说明 |
|---|---|
| 一键扫描 | 点一下 → 自动发现所有可用 provider (Ollama 本地 / OpenAI 兼容网关 / API key 供应商) |
| 模型下拉选择 | 扫描结果以卡片+多选列表呈现, 勾选即加入 |
| 一键测活 | 每个模型一个测活按钮, 结果内联显示 (延迟/模型名/错误原因) |
| 默认模型切换 | 单选切换, 立即生效 |
| 多 provider 并存 | Ollama/Zhipu/DeepSeek/OpenRouter 等任意多个同时配置, 互不干扰 |
| 环境变量 key | .env 自动加载 + UI 直接粘贴 key |

## meshctx 已有

- `/api/models/discover` — 扫描端点 (SSRF 守卫+Ollama/OpenRouter/provider 探测)
- `/api/models/batch` — 扫描结果批量加入 (加密存储)
- `/api/models/{id}` PUT — 编辑 base_url/key/model
- `/api/models/{id}/default` PATCH — 切默认
- UI: setup.html — 卡片列表 + ✎ 编辑弹窗 + 测活按钮

## 缺口 (本轮补齐)

1. **扫描结果展示**: discover 端点有了但 UI 没有"扫描→展示→勾选加入"流 (discover 按钮缺)
2. **测活结果内联展示**: 测活只显示 ✓/✗, 无延迟/错误详情
3. **编辑弹窗无 base_url 常用预设** (智谱 coding/标准/OpenRouter 等快捷按钮)
4. **多 key 并存管理** (同 provider 多 key 轮换)
