# MeshCtx 营销词 Scope 声明 (Claims Scope) — 根级约束

- 文档编号: MCTX-CLAIMS-SCOPE-2026-0905
- 适用范围: **全部根级营销面** — docs/index.html (主页), docs/i18n/landing.json,
  docs/download.html, docs/getting-started.html, docs/governance.html,
  docs/telemetry.html, docs/llms.txt, templates/chat.html (UI 文案),
  docs/marketing/ 商业资料, 以及未来任何新增营销/文档页面。
- 触发: 002codex (6c70eaf8) 收尾核验提醒 — 3.124.1 送审须附复验方法。
- 性质: 强制词汇纪律 (2026-09 自进化口径收敛三轮回执的成果固化, 证据:
  docs/release/copy-scan-20260904-v3.txt / -v4.txt)。

---

## 1. 允许 vs 禁用词汇 (机器可复验)

### 1.1 禁用 (超卖/无法代码举证, 任何语言任何页面不得出现)

| 形态 | 词形示例 (git grep 需全文词形, 勿只搜子串) |
|---|---|
| 英语 | `World's First`, `world's first`, `first self-evolv`, `self-evolving`, `self-evolv`, `Self-Improving Agent Platform` (作 self-evolving 同义), `most intelligent in the world`, `smarter than every` 等最高级比较 |
| 中文 | 全球首个, 首款, 世界第一, 最聪明的, 最强大的, 越用越聪明(指向自我进化的断言语境) |
| 日文 | 自己進化, 自己改善型, 世界初, 最も賢い |
| 韩文 | 자가 진화 (自我进化), 세계 최초 |
| 西/意/法/德/俄/阿 | `auto-evolutivo`, `Auto-Evolutivo`(es/it), `le premier au monde`, `weltweit erste`, `саморазвивающ` 最高级等 |

> 例外: 文档内**声明本约束本身**时允许引用词形 (本文件/审计证据文件豁免, 与 copy-scan
> 证据文件同样豁免)。

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
   任何跨版声称须引用 docs/governance.html / docs/telemetry.html 的 Edition Scope 段。
3. **Benchmark 对位**: 分数类声称只能来自真实运行且注明运行模式
   (`mode: real`/`official_submission`/`reference`); 禁止占位/自报分入营销面。
4. **单键互斥禁止**: 同一 data-lang-key 的 10 语言值口径必须一致 —
   任何语言不得出现比 zh/en 更激进的最高级 (2026-09 多轮审计的复发根因)。

## 3. 复验方法 (3.124.1 送审时与每次发版前执行)

```bash
cd <repo> && git pull origin main
# A. 词形扫描 (全文词形, 覆盖 zh/en/ja/ko/es/it/fr/de/ru/ar 上表全部词形)
#    输出保存为 docs/release/copy-scan-<date>-v<n>.txt 留证
git grep -nE "World's First|world's first|self-evolv|self-evolving|Self-Improving|首款|全球首个|世界第一|自己進化|自己改善|자가 진화|auto-evolutivo|El Primer|le premier au monde|weltweit erste|саморазвивающ" \
  -- ':!docs/release/copy-scan-*.txt' ':!docs/marketing/claims-scope-20260905.md' ':!docs/governance/whitepaper.md' \
  > docs/release/copy-scan-$(date +%Y%m%d).txt; cat docs/release/copy-scan-$(date +%Y%m%d).txt

# B. i18n 键位/语言完整性 (10 语言)
python3 -m pytest tests/test_homepage_i18n.py tests/test_real_i18n_behavior.py -q
python3 -c "from src.i18n import validate_keys; print(validate_keys())"

# C. 详情页 L dict 自检 (键位 + 运行时替换)
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
  console.log(f,'OK',langs.length+' langs');
}
"

# D. 功能对位抽检 (声称点 ↔ 实现)
python3 -m pytest tests/test_org_governance.py tests/test_swarm_cards.py -q
```

判定: A 输出为空 (或仅豁免文件命中) + B/C/D 全绿 → Scope 纪律通过。

## 4. 责任与变更

- 任何营销/文档文案变更须先过 §1 词表再合入; CI 阶段不强推, 由发版 SOP
  (docs/release/qa_release_sop_v1.md G 门) + 三方审计执行。
- 新增营销页面须纳入 §3-C 的自检清单 (10 语言 + 词表)。
- 证据文件: copy-scan-20260904{-v3,-v4}.txt (全站口径收敛留证)。

— meshctx 治理 (MCTX-CLAIMS-SCOPE-2026-0905), 2026-09-05
