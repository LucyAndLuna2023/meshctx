# meshctx v3.115.18 多语言翻译完整审计报告

**审计日期**: 2026-07-16
**审计方法**: 浏览器直接访问 + JavaScript运行时检查 `window.__i18n` / `window.__t()`
**目标**: 全部7种语言 (English, 中文, 日本語, 한국어, Français, Deutsch, Español)

---

## 🔴 总体结论：i18n系统形同虚设 — 语言切换完全无效

语言选择器存在7种语言选项，但**所有语言的 `__t()` 函数均返回英文**。`window.__i18n` 包含1122个key，全部value为英文，零翻译数据。

---

## 一、i18n架构分析

```
window.__i18n  = { key → English string }  (1122 keys, ALL values are English)
window.__t(k)  = 查 __i18n[k]，找不到返回 k 本身
window.__lang  = "en" (修改无效，不触发任何重载)
```

| 检测项 | 结果 |
|--------|------|
| `__i18n` key数量 | 1122 |
| zh翻译条目 | **0** |
| ja翻译条目 | **0** |
| ko翻译条目 | **0** |
| fr翻译条目 | **0** |
| de翻译条目 | **0** |
| es翻译条目 | **0** |
| `?lang=` URL参数 | **被忽略** |
| 语言选择器点击 | **不改变页面内容** |

---

## 二、逐页语言测试（以中文模式 `?lang=zh` 为例）

### 2.1 首页 `/`

| 元素 | 预期(中文) | 实际 | 状态 |
|------|-----------|------|------|
| 语言按钮 | 中文 | 🇺🇸 English ▾ ▾ | 🔴 英文 + 双箭头bug |
| 导航栏 (Features/Compare/About/GitHub/Documentation) | 功能/对比/关于/GitHub/文档 | Features/Compare/About/GitHub/Documentation | 🔴 全英文 |
| 主标题 | AI智能体学习 | The Agent That Learns | 🔴 英文 |
| 副标题 | AGPLv3框架... | AGPLv3 framework... | 🔴 英文 |
| Why MeshCtx? | 为什么选择MeshCtx？ | Why MeshCtx? | 🔴 英文 |
| 6个特性卡片 | 分层记忆/自改进... | Hierarchical Memory/Self-Improving... | 🔴 全英文 |
| 13脑区模块 | 海马回放/杏仁核... | Hippocampal Replay/Amygdala... | 🔴 全英文 |
| CTA按钮 | 开始使用 → | Get Started → | 🔴 英文 |

**覆盖率: 0/所有** (仅页面标题由服务端设置但内容不变)

### 2.2 Chat `/ui/chat`

| 元素 | 预期(中文) | 实际 | 状态 |
|------|-----------|------|------|
| 导航: Dashboard | 仪表盘 | Dashboard | 🔴 英文 |
| 导航: Projects | 项目 | Projects | 🔴 英文 |
| 导航: Memories | 记忆 | Memories | 🔴 英文 |
| 导航: Continuity | 连续性 | Continuity | 🔴 英文 |
| 导航: Chat | 对话 | Chat | 🔴 英文 |
| 导航: Setup | 设置 | Setup | 🔴 英文 |
| 导航: Plugins | 插件 | Plugins | 🔴 英文 |
| 导航: Files | 文件 | Files | 🔴 英文 |
| 导航: API Docs | API文档 | API Docs | 🔴 英文 |
| 导航: Skip to main | 跳转到主内容 | Skip to main content | 🔴 英文 |
| 页面标题 | 💬 meshctx 对话 | 💬 meshctx Chat | 🔴 英文 |
| 输入框占位 | 输入消息... | 输入消息... (Enter 发送, Shift+Enter 换行) | 🟡 半翻(混英文) |
| 发送按钮 | 发送 | send | 🔴 英文 |

**覆盖率: ~15%** (仅输入框占位部分中文)

### 2.3 Dashboard `/ui/dashboard`

| 元素 | 预期 | 实际 | 状态 |
|------|------|------|------|
| 所有二级导航 | 中文 | Chat/Setup/Plugins/Files/Dashboard | 🔴 全英文 |
| 页面标题 | 系统仪表盘 | 📊 System Dashboard | 🔴 英文 |
| Watchdog | 看门狗 | 🛡️ Watchdog | 🔴 英文 |
| Auto-Healer | 自愈 | 🏥 Auto-Healer | 🔴 英文 |
| API Endpoints | API端点 | API Endpoints | 🔴 英文 |
| 表格头 (Endpoint/Latency/Status) | 端点/延迟/状态 | Endpoint/Latency/Status | 🔴 全英文 |
| 插件表格 (Name/Status/Installs) | 名称/状态/安装数 | Name/Status/Installs | 🔴 全英文 |
| 状态值 (active/beta) | 活跃/测试 | active/beta | 🔴 英文 |
| OK | 正常 | OK | 🔴 英文 |

**覆盖率: 0%**

### 2.4 Files `/ui/files`

| 元素 | 预期 | 实际 | 状态 |
|------|------|------|------|
| 所有导航 | 中文 | 全英文 | 🔴 |
| 页面标题 | 文件管理 | 📁 File Manager | 🔴 |
| 按钮: Up/Refresh/Copy Path | 上级/刷新/复制路径 | ⬆ Up/🔄 Refresh/📋 Copy Path | 🔴 全英文 |
| 表格: Name/Size/Modified | 名称/大小/修改时间 | Name/Size/Modified | 🔴 全英文 |
| 错误信息 | 目录不存在: /opt/meshctx | 目录不存在: /opt/meshctx | 🟢 中文 |

**覆盖率: ~5%** (仅错误信息)

### 2.5 Plugins `/ui/plugins`

| 元素 | 预期 | 实际 | 状态 |
|------|------|------|------|
| 导航 | 中文 | 💬 Chat/⚙ Setup/📁 Files/🔌 Plugins | 🔴 全英文 |
| 页面标题 | 插件市场 v2.4 | 🔌 插件市场 v2.4 | 🟢 中文 |
| 搜索框 | 搜索插件 | 搜索插件 | 🟢 中文 |
| 分类下拉 | 全部分类 | 📂 全部分类 | 🟢 中文 |
| 安装按钮 | 安装 | 📥 安装 | 🟢 中文 |
| 激活按钮 | 激活 | ⚡ 激活 | 🟢 中文 |
| 分类选项 (search/security等) | 搜索/安全... | search/security/system/analytics/dev/integration | 🔴 全英文 |
| 从URL安装 | 从 URL 安装插件 | 🔗 从 URL 安装插件 | 🟢 中文 |
| URL输入框 | 插件URL | Plugin URL | 🔴 英文 |
| 示例文字 | 示例 | 💡 示例: | 🟢 中文 |
| 提交链接 | 提交你的插件 → | ✏️ 提交你的插件 → | 🟢 中文 |
| 插件描述 | - | AI-powered git: auto-commit... | 🔴 英文(来自插件元数据) |

**覆盖率: ~70%** (7语言中最佳，但导航仍英文)

### 2.6 Projects `/ui/projects`

| 元素 | 预期 | 实际 | 状态 |
|------|------|------|------|
| 页面标题 | 项目管理 | 📁 Project Management | 🔴 英文(标题栏是"项目管理") |
| 副标题 | 创建和管理上下文记忆项目 | 创建和管理上下文记忆项目 | 🟢 中文 |
| 创建表单标题 | 创建新项目 | ➕ Create New Project | 🔴 英文 |
| Project Name | 项目名称 | Project Name * | 🔴 英文 |
| Description | 描述 | Description | 🔴 英文 |
| Tags | 标签(逗号分隔) | Tags (comma separated) | 🔴 英文 |
| 创建按钮 | 创建 | 创建 | 🟢 中文 |
| 表格头 | 项目名称/状态/会话数/记忆数/连续性/更新时间/操作 | 项目名称/状态/会话数/记忆数/连续性/更新时间/操作 | 🟢 全中文 |
| 状态值 | 活跃 | active | 🔴 英文 |
| 操作按钮 | 详情/删除 | 详情/删除 | 🟢 中文 |

**覆盖率: ~50%** (表格头中文，表单英文)

### 2.7 Memories `/ui/memories`

| 元素 | 预期 | 实际 | 状态 |
|------|------|------|------|
| 页面标题 | 记忆浏览 | 🧠 记忆浏览 | 🟢 中文 |
| 导航 | 中文 | 全英文 | 🔴 |

**覆盖率: ~30%** (仅标题，页面主体未完全加载)

---

## 三、跨语言一致性测试

使用 `window.__t()` 对所有7种语言测试6个核心key：

| Key | en | zh | ja | ko | fr | de | es |
|-----|----|----|----|----|----|----|-----|
| hello | Hello | Hello | Hello | Hello | Hello | Hello | Hello |
| chat | Chat | Chat | Chat | Chat | Chat | Chat | Chat |
| dashboard | Dashboard | Dashboard | Dashboard | Dashboard | Dashboard | Dashboard | Dashboard |
| send_btn | Send | Send | Send | Send | Send | Send | Send |
| files | Files | Files | Files | Files | Files | Files | Files |
| nav_home | Home | Home | Home | Home | Home | Home | Home |

**结论：所有语言返回完全相同的英文值。`__lang` 变量存在但无任何作用。**

---

## 四、缺陷清单

| # | 严重级别 | 缺陷 | 详情 |
|---|---------|------|------|
| 1 | **P0** | i18n翻译数据为零 | `__i18n` 1122条均为英文，zh/ja/ko/fr/de/es 翻译条目数=0 |
| 2 | **P0** | 语言选择器是摆设 | 7种语言选项存在但选中后页面不变化 |
| 3 | **P0** | `?lang=` URL参数无效 | 服务端不根据lang参数返回不同翻译 |
| 4 | **P0** | `window.__lang` 修改无效果 | JS运行时切换lang后`__t()`仍返回英文 |
| 5 | **P1** | 翻译严重不一致 | 插件页70%中文 vs 仪表盘0%，同一session体验割裂 |
| 6 | **P1** | 导航栏永为英文 | 出现在所有页面的全局导航从未翻译 |
| 7 | **P2** | 双箭头UI bug | "🇺🇸 English ▾ ▾" 出现双chevron |
| 8 | **P2** | "send"按钮永为英文 | 所有语言chat发送按钮均为"send" |
| 9 | **P2** | 部分硬编码中文泄漏 | chat输入框"输入消息..."是硬编码中文而非i18n查表 |

---

## 五、对比：首页 vs App内页

首页使用服务端模板渲染（非SPA），但其内容硬编码为英文，lang参数同样不生效：

- 首页 `/?lang=zh` → 100%英文
- 首页 `/?lang=ja` → 100%英文
- 语言按钮始终显示 "🇺🇸 English ▾ ▾"

---

## 六、修复建议

1. **建立翻译文件**: 为 `zh/ja/ko/fr/de/es` 各创建 `i18n/{lang}.json`
2. **实现 `__t()` 多语言**: 根据 `__lang` 选择正确的翻译表而非永远返回英文
3. **联动URL参数**: `?lang=zh` → 设置 `__lang="zh"` → 加载对应翻译
4. **全局导航优先级最高**: 导航栏出现频率最高，应最先翻译
5. **修复双箭头**: 语言按钮文案去掉重复 `▾`
6. **统一翻译策略**: 移除硬编码中文/英文，全部走i18n查表

---

**评分**: i18n: **5/100** — 有架构壳子(语言选择器+__t函数+1122 key槽位)，但零翻译数据，形同虚设。
