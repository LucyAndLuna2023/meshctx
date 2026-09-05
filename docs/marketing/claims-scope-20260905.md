# MeshCtx 营销词 Scope 声明 (Claims Scope) — 根级约束

- 文档编号: MCTX-CLAIMS-SCOPE-2026-0905
- 适用范围: **全部根级营销面** — docs/index.html (主页), docs/i18n/landing.json,
  docs/download.html, docs/getting-started.html, docs/governance.html,
  docs/telemetry.html, docs/llms.txt, templates/chat.html, templates/base.html,
  docs/marketing/ 商业资料, 以及任何未来新增营销页面。
- 触发: 002codex (6c70eaf8) 收尾核验提醒 — 3.124.1 送审须附复验方法。
- 补丁轮3 (2026-09-05): 响应 002codex 05e090e0 + 002meshctx 2fe64ea4 + 004meshctx 1a49d7ce —
  词表补全与序数误报修正、A1/A2 双扫描、排除附录、HEAD 基线、RTL 修复(详见 §6)。
- 性质: 强制词汇纪律 (2026-09 自进化口径收敛三轮回执的成果固化, 证据:
  docs/release/copy-scan-20260904-v3.txt / -v4.txt / -claims 系列)。

---

## 1. 允许 vs 禁用词汇 (机器可复验)

### 1.1 禁用 (超卖/无法代码举证, 任何语言任何活跃营销面不得出现)

| 形态 | 词形示例 (git grep 需全文词形, 勿只搜子串; 裸序数如 首个/el primer 不属禁词, 会误报) |
|---|---|
| 英语 | `World's First`, `world's first`, `first self-evolv`, `self-evolving`, `self-evolv`, `Self-Improving Agent Platform` (作 self-evolving 同义), `most intelligent agent/system/platform`, `most powerful agent/system/platform` 等最高级比较 |
| 中文 | 全球首个, 全球第一款, 世界第一, 世界首个, 首款, 自我进化, 自进化, 越用越聪明, 越来越聪明 (指向自我进化的断言语境), 最聪明的, 最强大的 |
| 日文 | 世界初, 世界で初めて, 自己進化, 自己改善型, 最も賢い |
| 韩文 | 세계 최초 (세계최초), 자가 진화 (자가진화), 자기 진화 (자기진화) |
| 西/意/法/德/俄/阿 | `auto-evolutivo`, `Auto-Evolutivo` (es/it), `El Primer Sistema de Agentes`, `auto-évolutif`, `le premier au monde`, `weltweit erste`, `selbstverbessernd`, `selbstlernend`, `саморазвивающ`, `самообучающ`, `самый умный`, `ذاتي التحسين`, `التطور الذاتي` 等最高级/自进化系 |

> 例外: 文档内**声明本约束本身**、审计/核验/计划记录性引用时允许引用词形
> (本文件、copy-scan 证据、self-evolution-verification、plans 等豁免, 见 §3-A0)。

### 1.2 允许 (与代码能力对位, 推荐口径)

- `self-adaptive` / `adaptive` (自适应) — 对应元认知循环/指令遵循等机制
- `auditable` (可审计) — 对应审计轨迹/审批/操作日志
- `learns from tasks` / `task learning` — 对应记忆回放等已实现机制
- 功能事实描述词: span/trace 可观测, RBAC 授权, 部门数据权限, 任务卡, 值守
  (Routines), 沙箱, 记忆检索 — 均须有 src/core + API + 测试佐证

## 2. 声称规则 (Scope Rules)

1. **代码对位**: 任何功能声称必须能在当前 main 找到实现点 (模块/路由/测试)。
   无实现不写; 开发中能力必须显式标注「开发中/roadmap」。
2. **版本对位**: 功能×版本(个人/团队 $9/企业 $29) 表述须与定价文案一致:
   - 个人版: 单用户自有数据域/本地功能
   - 团队版: 部门树、经理授权、部门协作视图; 遥测本地追踪 + 优先支持
   - 企业版: 完整 RBAC/管理员控制/审计导出; 遥测 OTLP 对接自有可观测栈
   任何跨版声称须引用 docs/governance.html / docs/telemetry.html 的 Edition Scope 段;
   未正式发布的功能不得写版本号 (governance 页 badge 用定位文案先例)。
3. **Benchmark 对位**: 分数类声称只能来自真实运行且注明运行模式
   (`mode: real`/`official_submission`/`reference`); 禁止占位/自报分入营销面。
4. **单键互斥禁止**: 同一 data-lang-key 的 10 语言值口径必须一致 —
   任何语言不得出现比 zh/en 更激进的最高级 (2026-09 多轮审计的复发根因)。

## 3. 复验方法 (3.124.1 送审时与每次发版前执行)

### 3-A0 排除附录 (内部/审计/历史/清单类 — 逐文件理由)

| 文件/类 | 排除理由 | 共识方 |
|---|---|---|
| docs/marketing/claims-scope-20260905.md | 本声明自身须引用禁词词形 | 三方 (声明主体) |
| docs/release/copy-scan-*.txt | 扫描证据输出, 须含命中词形 | 三方 (copy-scan v3/v4) |
| docs/marketing/self-evolution-verification-20260903.md | 「自进化」核验分析报告, 引词为分析对象 (同 copy-scan 证据语义) | 三方 (MCTX-VER-2026-0903) |
| docs/DESIGN_v1.0.md | 历史架构设计快照 (v1.0), 非营销面, 不对外 | 002meshctx 2fe64ea4 建议 |
| docs/index.html.v2.14 | 主页显式版本备份 (文件名 .v2.14), 站点不引用 | 002meshctx 2fe64ea4 建议 |
| docs/marketing/MeshCtx_商业计划书_v3.116.md | 内部商业计划 (非对外营销页); 行3/39 实销文案已于补丁轮3 收敛为自适应口径; 其余命中=内部「发布前必检清单」引词 (约 421 行, 自检清单必须引用词形) | 002meshctx 2fe64ea4 + 002codex 05e090e0 (待补丁轮3 确认) |
| docs/plans/ | 内部计划/审计记录 (含「自进化核验与文案收敛」等工作项名与回执引用), 非营销面 | 002meshctx 2fe64ea4 + 002codex 05e090e0 (待补丁轮3 确认) |

> 判定口径: **A1 (活跃营销面) 必须 0 命中; A2 (仓库级) 命中 ⊆ 排除附录即通过**。
> 新增内部引用类文件须先补入本表再合入, 避免「A2 越界」回归。

### 3-A 词形扫描 (机器复验)

```bash
bash docs/release/claims_scope_check.sh        # 在仓库根执行
# 输出 docs/release/copy-scan-<date>-claims.txt, 首行含 git rev-parse HEAD 基线
# 判定: A1 = 0 命中 (活跃营销面枚举见脚本 SURFACES) + A2 命中 ⊆ §3-A0 排除类 → PASS
```

- 词表 = §1.1 表 + 历轮 (copy-scan v3/v4) 检出词形全集, 已随脚本固化
  (`claims_scope_check.sh` PAT); 新检出语言词形须同步补入脚本与 §1.1。
- 历史证据: copy-scan-20260904{-v3,-v4}.txt 为三轮收敛基线; 补丁轮3 起以
  copy-scan-*-claims.txt 为现行证据链。

### 3-B i18n 键位/语言完整性 (10 语言)

```bash
python3 -m pytest tests/test_homepage_i18n.py tests/test_real_i18n_behavior.py -q
python3 -c "from src.i18n import validate_keys; print(validate_keys())"
```

### 3-C 详情页 L dict 自检 (键位 + 运行时替换 + RTL)

```bash
node -e "
const fs=require('fs');
for (const f of ['docs/governance.html','docs/telemetry.html']) {
  const html=fs.readFileSync(f,'utf8');
  const m=html.match(/const L = (\{[\s\S]*?\n\});/);
  const L=eval('('+m[1]+')');
  const langs=Object.keys(L), keys=Object.keys(L['en']);
  for(const lg of langs){const k=Object.keys(L[lg]); if(k.length!==keys.length) throw f+' '+lg+' 键位不一致';}
  const body=html.replace(/<script[\s\S]*?<\/script>/g,'');
  const used=[...body.matchAll(/data-lang-key=\"([^\"]+)\"/g)].map(x=>x[1]);
  if(used.some(u=>!keys.includes(u))) throw f+' 使用了 L 未定义键';
  if(!/dir = \(lang === 'ar'\)/.test(html)) throw f+' 缺 RTL dir 切换 (004meshctx round20 P2-1)';
  console.log(f,'OK',langs.length+' langs');
}
"
```

### 3-D 功能对位抽检 (声称点 ↔ 实现)

```bash
python3 -m pytest tests/test_org_governance.py tests/test_swarm_cards.py -q
```

判定: A1 0 命中 + A2 ⊆ 排除附录 + B/C/D 全绿 → Scope 纪律通过。

## 4. 责任与变更

- 任何营销/文档文案变更须先过 §1 词表再合入; CI 阶段不强推, 由发版 SOP
  (docs/release/qa_release_sop_v1.md G 门) + 三方审计执行。
- 新增营销页面: (a) 纳入 §3-A SURFACES 枚举; (b) 10 语言键位完整; (c) 语言切换器
  含 RTL dir 处理 (ar → rtl); (d) 过 §3-A/B/C 自检清单。
- 证据文件: copy-scan-20260904{-v3,-v4}.txt (口径收敛基线) + copy-scan-*-claims.txt
  (现行证据链, 每份含 HEAD 基线)。

## 5. 共识记录 (补丁轮3)

- 002meshctx 2fe64ea4: 3.124.1 治理章节送审 ✅ 通过; 补强①词表缺 zh 独立词形与 ko
  无空格变体 → 已补 (§1.1/PAT); 补强②历史文件豁免 → 已入 §3-A0 附录。
- 002codex 05e090e0: 两页 HTML ✅; scope 文档 3 点 → 已修: A 排除附录 + HEAD 基线 +
  A1/A2 双扫描; B 词表补全 (世界初/세계 최초/自己改善型/自我进化/自进化/世界首个/
  越用越聪明/最聪明/最强大/Auto-Evolutivo/self-evolving/self-improving agent platform/
  selbstverbessernd/ذاتي التحسين/самообучающ 等) 并删除裸序数误报项; C BP 实销文案
  2 行收敛 (行3/39 → 自适应+受控进化口径) + BP/plans 入排除附录。
- 004meshctx 1a49d7ce (round20): NEW-P2-1 RTL 缺失 → governance/telemetry/getting-started
  及同谱系 download/test-report/LEGAL 六页 switchLang 全补
  `document.documentElement.dir=(lang==='ar')?'rtl':'ltr'` (index/profile 已有)。
- 本表状态: 补丁轮3 送审中 (待三方复核确认)。

— meshctx 治理 (MCTX-CLAIMS-SCOPE-2026-0905), 2026-09-05
