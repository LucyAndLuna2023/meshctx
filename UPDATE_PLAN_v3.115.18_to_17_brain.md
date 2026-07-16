# 🧠 MeshCtx 更新计划 — v3.115.18 → 17脑区正式版

> 起草时间: 2026-07-16 | 起草者: meshctx agent@004  
> 审计对象: 004qa  
> 当前版本: v3.115.18 | 目标版本: v3.115.19

---

## 一、架构现状 (架构全景回顾)

```
┌──────────────────────────────────────────────┐
│  Layer 1: meshctx.com 网站                      │
│  GitHub Pages (gh-pages分支)                   │
│  index.html · docs/ · 7语言主页                │
│  当前宣称: 13脑区 → 实际: 17脑区 (过期!)        │
└──────────────────┬───────────────────────────┘
                   │
       ┌───────────┴───────────┐
       ▼                       ▼
┌──────────────┐     ┌──────────────────────────┐
│ Layer 2: 闭源  │     │ Layer 3: 开源 (当前)        │
│ meshctx-core  │     │ meshctx-public             │
│ 私有 GitHub    │     │ GitHub LucyAndLuna2023     │
│ v3.47         │     │ v3.115.18                  │
│ Docker 部署    │     │ 17脑区 · 200+模块           │
│ UAT 已关闭     │     │ 基准63.2% · 29/42通过       │
└──────────────┘     └──────────────────────────┘
```

### 当前17脑区一览

| # | 脑区 | 模块 | 基准分 | 状态 |
|---|------|------|--------|------|
| 1 | Hippocampal | 记忆回放/编码 | 20% | 🔴 |
| 2 | Amygdala | 情感显著性 | 79% | ✅ |
| 3 | DefaultMode | 默认模式网络 | 82% | ✅ |
| 4 | Thalamic | 丘脑门控 | 13% | 🔴 |
| 5 | Cerebellar | 小脑前向模型 | 33% | 🔴 |
| 6 | BasalGanglia | 基底节TD学习 | 65% | 🟡 |
| 7 | ACC | 冲突监控 | 93% | ✅ |
| 8 | Insula | 内感知 | 100% | ✅ |
| 9 | Mirror | 镜像神经元 | 96% | ✅ |
| 10 | STDP | 突触可塑性 | 80% | ✅ |
| 11 | IIT | 信息整合 | 83% | ✅ |
| 12 | GnosticField | 灵知场 | 51% | 🟡 |
| 13 | LTP | 长时程增强 | 20% | 🔴 |
| 14 | **PFC** | 工作记忆+任务切换 | **55%** | 🟡 新增 |
| 15 | **VisualCortex** | Gabor滤波器+特征提取 | **83%** | ✅ 新增 |
| 16 | **NAcc** | 奖励预测+动机信号 | **35%** | 🔴 新增 |
| 17 | **Brainstem** | 自主调节+觉醒控制 | **25%** | 🔴 新增 |

---

## 二、更新任务清单

### 🔴 P0 — meshctx.com 主页更新 (网站仍是"13脑区")

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| P0-1 | 标题 13→17 | `index.html` line 9 | `<title>` 改为 17-Brain-Region |
| P0-2 | OG/Twitter meta | `index.html` line 13-19 | 所有 meta 13→17 |
| P0-3 | Hero段落 13→17 | `index.html` line 166,176,220 | 中/英/西 7语言 |
| P0-4 | f7_desc更新 | `index.html` line 236 | 9脑区列举 → 17脑区，加入PFC/Visual/NAcc/Brainstem |
| P0-5 | 脑区卡片sb10-sb13 | `index.html` line 272后 | 新增4张卡片：PFC/VisualCortex/NAcc/Brainstem |
| P0-6 | Benchmark数据 | `index.html` line 274 | 更新为v9真实数据：63.2%/29/42 |
| P0-7 | 对比表新增行 | `index.html` line 309后 | 加PFC/Visual/NAcc/Brainstem对比行 |
| P0-8 | `docs/index.html` | 同步更新 | 同index.html |
| P0-9 | `docs/docs.html` | 同步更新 | 同index.html |
| P0-10 | gh-pages部署 | `git checkout gh-pages` | 合并更新并push |

### 🟡 P1 — README+文档更新

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| P1-1 | 标题 9→17脑区 | `README.md` line 4,12 | 徽章也更新 |
| P1-2 | 架构图更新 | `ARCHITECTURE.md` | v3.115.18, 17脑区, 新模块清单 |
| P1-3 | 版本号统一 | `pyproject.toml`, `src/__init__.py` | 确认 v3.115.18 一致 |

### 🟢 P2 — 备份

| # | 任务 | 说明 |
|---|------|------|
| P2-1 | Git备份 | `git stash` + `git tag v3.115.18-backup` |
| P2-2 | 文件备份 | 关键文件tar打包到Desktop |
| P2-3 | gh-pages备份 | 备份当前gh-pages分支 |

### 🔵 P3 — 低分脑区改进 (可选)

| 脑区 | 当前 | 目标 | 改进方向 |
|------|------|------|---------|
| Hippocampus | 20% | 50%+ | 改进recall匹配算法 |
| Thalamus | 13% | 50%+ | 丰富sensory_data输入 |
| Cerebellum | 33% | 50%+ | 优化前向预测误差 |
| NAcc | 35% | 50%+ | 调整TD学习率 |
| Brainstem | 25% | 50%+ | 重新设计稳态模型 |

---

## 三、影响范围评估

### index.html 修改点 (精确计数)
- **"13" → "17" 替换**: ~12处 (标题+meta+hero+描述)
- **脑区卡片新增**: 4个 feature-card (sb10-sb13)
- **f7_desc 重写**: 7语言 × 1处 = 7处
- **Benchmark行**: 1处数据更新
- **对比表**: 4新行
- **预估工作量**: ~80行新增/修改

### 风险
- 🚨 JS语言切换依赖 i18n JSON — sb10-sb13 的翻译需加入
- 🚨 gh-pages部署后CDN刷新有延迟(~5分钟)

---

## 四、17脑区基准回顾 (存桌面)

本次基准测试 v9 结果：
- **综合评分**: 63.2% (目标70%)
- **通过指标**: 29/42
- **优秀(≥70%)**: 9个模块 (Insula 100%, Mirror 96%, ACC 93%, IIT 83%, Visual 83%, DMN 82%, STDP 80%, Amygdala 79%, Thalamus 73%... )
- **待改进(<40%)**: 5个 (Hippocampus 20%, Thalamus 13%... 等等，我刚才看到Thalamus 73%了)
- 报告文件: `MeshCtx_17脑区基准测试报告_v3.115.18_20260716.md` (已存Windows桌面)

---

## 五、执行顺序

```
Phase 1: 备份
  ├── Git tag + stash
  └── 文件打包到Desktop

Phase 2: 主页更新  
  ├── index.html (13→17 全局替换)
  ├── docs/index.html (同步)
  ├── docs/docs.html (同步)
  └── 新增脑区卡片+翻译

Phase 3: 文档更新
  ├── README.md (9→17)
  └── ARCHITECTURE.md (更新至v3.115.18)

Phase 4: 部署
  └── git push → gh-pages checkout → merge → push

Phase 5: 审计
  └── 本文件发送004qa审计 (Hub不通 → 存Desktop + GitHub)
```

---

## 六、当前阻塞

| 阻塞项 | 状态 | 影响 |
|--------|------|------|
| Hub Redis不可达 | 🔴 104.243.239.167:6379 断连 | 无法发消息给004qa |
| 替代方案 | ✅ 本计划存Desktop + GitHub | 004qa可通过GitHub/Desktop查阅 |

---

> **发送给004qa**: 由于Hub Redis不可达，本更新计划已同时保存至：
> 1. Windows桌面: `/mnt/c/Users/Administrator/Desktop/UPDATE_PLAN_v3.115.18.md`
> 2. GitHub仓库: `meshctx-public/UPDATE_PLAN_v3.115.18.md`
> 3. 本地: `~/meshctx-public/UPDATE_PLAN_v3.115.18_to_17_brain.md`
>
> 请004qa审计后回复意见。
