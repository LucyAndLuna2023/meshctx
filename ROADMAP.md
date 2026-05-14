     1|# ═══════════════════════════════════════════════════════════════
     2|# meshctx 加速冲刺计划 — 智能提升 + macOS + 全量测试
     3|# 2026-05-14 启动
     4|# ═══════════════════════════════════════════════════════════════
     5|
     6|## 当前状态
     7|| 维度 | 状态 |
     8||------|------|
     9|| Python 后端测试 | ✅ 224/224 全过 |
    10|| Brain-Inspired 模块 | ✅ 三大闭环集成完成 |
    11|| Windows 桌面 | ✅ NSIS安装程序+v1.5.25 exe |
    12|| macOS 桌面 | ❌ 未开始 |
    13|| 前端 UI 测试 | ❌ 无 |
    14|| 构建自动化 | ⚠️ 仅 Windows, GitHub Actions |
    15|
    16|## ━━ Phase 0: 智能提升冲刺 (48h) ━━
    17|
    18|### P0-P2 脑启发算法栈（已有）
    19|基本算法框架完成（自由能/主动推理/工作空间/内稳态/元认知），
    20|但离 "真正智能" 还有差距。需要：
    21|
    22|#### 🚀 P0 — 智能突破 (24h内)
    23|- [x] **生成模型在线学习** ✅ — ActiveInference 的 GenerativeModel 当前是静态的
    24|      必须从每次交互中学习转移矩阵 p(s'|s,a) 和观察矩阵 p(o|s)
    25|      → 让模型真正"理解"环境变化
    26|- [x] **完整自由能循环驱动 Chat** ✅ — 当前 Chat 是直出 LLM 响应
    27|      改造: OODA®Orient→Decide 时计算自由能 F，如果 F 高 → 先探索再回答
    28|      低F → 直接生成答案。加入"认知成本"感知。
    29|- [x] **混合推理调度器** ✅ — 何时用经典算法vs直出LLM
    30|      规则: F > 阈值 → 主动推理探索 → 积累证据 → LLM生成
    31|      F < 阈值 → 直接LLM回答
    32|- [x] **智能基准测试自动化** ✅ — 跑 benchmark 量化验证改进效果
    33|      场景: 动态多臂老虎机、资源压力测试、决策链质量
    34|
    35|#### 🔧 P1 — 能力增强 (48h内)
    36|- [ ] **预测×自由能闭环** ✅ 已完成 (FreeEnergyPredictorAdapter)
    37|- [ ] **元认知×主动推理闭环** ✅ 已完成 (MetaActiveInferenceAdapter)
    38|- [ ] **工作空间×OODA集成** ✅ 已完成 (WorkspaceAwareAdapter)
    39|- [ ] **自由能驱动的Chat响应** — 上述P0的核心交付
    40|- [ ] **情境感知记忆检索** — 工作空间状态影响记忆检索权重
    41|- [ ] **自调节探索-利用曲线** — 追踪并可视化exploration_ratio变化
    42|
    43|#### 📊 P2 — 量化验证
    44|- [ ] 决策质量对比: 集成前 vs 集成后 (决策成本/准确率)
    45|- [ ] 资源压力测试: 100任务生存率
    46|- [ ] 收敛速度: 策略收敛步数
    47|- [ ] 对比表更新到 README
    48|
    49|## ━━ Phase 1: macOS 构建 (36h) ━━
    50|
    51|### macOS 客户端构建流程
    52|
    53|#### Step 1 — 测试工具链搭建
    54|- [ ] **pyobjc/pywebview macOS 兼容性验证**
    55|- [ ] **macOS CI runner 配置** (GitHub Actions macos-latest)
    56|- [ ] **交叉编译可行性验证** (WSL 无法编译 macOS .app)
    57|- [ ] **创建 mac-build.yml** GitHub Actions workflow
    58|
    59|#### Step 2 — macOS 原生打包
    60|- [ ] **meshctx_mac.spec** — PyInstaller for macOS .app
    61|- [ ] **版本信息嵌入** (Info.plist + CFBundleVersion)
    62|- [ ] **代码签名** (macOS 安全要求, ad-hoc 至少)
    63|- [ ] **打包为 .app + .dmg** (create-dmg 或 dmgbuild)
    64|
    65|#### Step 3 — 打包脚本
    66|- [ ] **scripts/build-mac.sh** — 自动构建脚本
    67|- [ ] **macOS 安装脚本** — install_mac.sh
    68|- [ ] **版本描述文件** — version_info_mac.txt
    69|
    70|#### Step 4 — CI/CD 集成
    71|- [ ] **GitHub Actions release 双平台** (Windows + macOS)
    72|- [ ] **macOS 下载链接** (meshctx.com 下载页)
    73|- [ ] **主页更新** platform badge 加回 macOS
    74|
    75|## ━━ Phase 2: 全方位测试 (36h) ━━
    76|
    77|### 分层测试策略
    78|
    79|#### T1 — 单元测试 (已有 224, 需要: 350+)
    80|- [ ] **web_ui.py 路由测试** — 全部 30+ API 端点
    81|- [ ] **model_registry.py 模型扫描/切换测试**
    82|- [ ] **config.py 配置加载/热加载测试**
    83|- [ ] **cli.py 全部 13+ 命令测试**
    84|- [ ] **gateway.py 9平台连接器测试**
    85|- [ ] **cron.py 定时任务测试**
    86|- [ ] **i18n.py 7语言翻译完整性测试**
    87|
    88|#### T2 — 前端 UI 自动化测试 (Playwright)
    89|- [ ] **tests/ui/test_base_layout.py** — 导航/页脚/语言切换/主题
    90|- [ ] **tests/ui/test_chat.py** — 输入/发送/流式/历史/多轮
    91|- [ ] **tests/ui/test_setup.py** — API配置/模型选择/表单验证
    92|- [ ] **tests/ui/test_dashboard.py** — 状态面板/插件列表/统计
    93|- [ ] **tests/ui/test_projects.py** — CRUD/过滤/详情
    94|- [ ] **tests/ui/test_memories.py** — 搜索/删除/详情
    95|- [ ] **tests/ui/test_continuity.py** — 上下文/会话管理
    96|- [ ] **tests/ui/test_conversation.py** — 会话列表/加载/删除
    97|
    98|#### T3 — 集成测试 (已有 36, 需要: 80+)
    99|- [ ] **多插件协同测试** — kernel + memory + metacognition + predict
   100|- [ ] **OODA 全循环测试** — observe→orient→decide→act→learn
   101|- [ ] **构建产物验证测试** — .exe 完整性/版本号/功能
   102|- [ ] **错误恢复测试** — 插件崩溃/重启/熔断
   103|- [ ] **并发压力测试** — 多会话/多请求
   104|
   105|#### T4 — 构建验证测试
   106|- [ ] **GitHub Actions workflow 完整性测试**
   107|- [ ] **Windows .exe 产物验证** (版本号/大小/功能)
   108|- [ ] **macOS .app 产物验证**
   109|- [ ] **pip install 安装测试**
   110|
   111|## ━━ Phase 3: 文档与发布 (12h) ━━
   112|
   113|- [ ] README 最终版 (包含macOS支持)
   114|- [ ] CHANGELOG 补全
   115|- [ ] docs/ 所有文档刷新
   116|- [ ] meshctx.com 主页同步更新
   117|- [ ] 下载页 mac 下载链接
   118|- [ ] 版本标签推送
   119|
   120|## ━━ 时间表 ━━
   121|
   122|| 阶段 | 时间 | 交付物 | 测试目标 |
   123||------|------|--------|---------|
   124|| P0 智能突破 | 24h | 自由能驱动Chat + 混合推理 + benchmark | 350+ 单元测试 |
   125|| P1-P2 优化量化 | 24h | 闭环完善 + 量化对比表 | |
   126|| macOS 构建 | 36h | .app + .dmg + CI | 构建验证测试 |
   127|| UI 自动化测试 | 36h | Playwright 全页面遍历 | 100% UI 覆盖 |
   128|| 文档+发布 | 12h | 全部文档刷新 + 双平台发布 | |
   129|
   130|**总计: ~96h (4天)**
   131|
   132|## ━━ 当前状态追踪 ━━
   133|
   134|### 测试计数: 473 ✅
   135|- tests/ 下 20+ 个测试文件
   136|- 脑启发模块: 46+36=82 测试
   137|- 集成测试: 36 测试 (test_v15_integration.py)
   138|- 全量通过: 473 passed, 17 skipped
   139|