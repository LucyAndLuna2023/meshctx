# meshctx QA 与发布流程 SOP（标准发布流程 v1.0）

- 编号: MCTX-REL-SOP-001　版本: v1.1（三方审计 P2 修正）　生效: 2026-09-03（自 v3.124.0 强制）
- 适用范围: meshctx 全产品矩阵的每次版本发布（**后续所有新版本必须走此流程**）
- 维护: 004meshctx（发布负责人）＋ 三方审计（002meshctx/002codex/004meshctx）
- 依据: MCTX-PLAN-2026-0903 质量门 + v3.123.0/3.123.1 实际发版经验 + 三方审计多轮反馈

---

## 1. 复杂度矩阵（本 SOP 覆盖的全部维度）

| 维度 | 值 | 发布时对应检查 |
|---|---|---|
| 平台 SKU | Windows / macOS / Linux | Build windows/macos/linux 三 workflow 全绿 + Release 资产齐全 |
| 语言 | 10（en/zh/ja/ko/de/fr/es/it/ar/ru） | i18n Guard CI + 本地 i18n 套件 + 键数一致性断言 |
| 版本（Edition） | 个人 free / 团队 $9 / 企业 $29 | edition gating 测试（36 路由隐藏清单不漂移）+ 安装器版本一致 |
| 代码形态 | 开源 AGPL（meshctx-public）+ 闭源增强（installer 物理覆盖 src/core/*.py） | install-edition.sh 覆盖清单核对 + `src/core/*.py` 新增即登记 |
| 站点 | meshctx.com（GitHub Pages, docs/） | Deploy Pages workflow + 线上抽查 |

原则：**任一维度不通过 → 版本不发**。

## 2. 角色与门禁

| 角色 | 职责 |
|---|---|
| 004meshctx（发布负责人） | 编码/测试/版本号/发版序列执行/回滚 |
| 002meshctx / 002codex / 004meshctx（三方审计） | 每里程碑 rc1 送审 → P2（阻断）/P3（建议）→ rc2 修复 → 终验放行 |
| 用户（产品 owner） | 触发审计方审阅、最终放行确认 |

门禁规则：
- **P2 = 阻断**：修复前不得发版（rc1 收 P2 → rc2 必修）。
- **P3/P4 = 建议/排期**：终验前至少处理"发版前必修"类 P3（按审计方建议清单）。
- 三方终验"放行"后才执行 R4 之后动作（tag/资产）。

## 3. 发布前 QA 门（每个候选版本必须全绿）

| 门 | 命令/动作 | 通过标准（v3.123.0 基线） |
|---|---|---|
| G1 全量回归 | `pytest tests/`（无 --timeout；stub 模式跳过项为白名单） | 3717+ passed / 59 skipped / **0 failed**；新增测试随提交 |
| G2 T0/专项套件 | routines×3 / telemetry / sandbox / hub×5 等 | 全绿（本次 99 passed） |
| G3 i18n | i18n Guard workflow + `tests/test_v16_i18n.py` 等 | 10 语言键完整；chat/base/landing 键数一致性 |
| G4 edition 门控 | `tests/test_task_edition_gating.py` 等 | personal 隐藏 36 路由清单不漂移；**新增 `src/core/*.py` 即登记**（路由隐藏/清单/CHANGELOG） |
| G5 完整性（**release 硬门**：R4 前必须全绿，任一 FAIL 不得 tag） | `tests/test_project_integrity.py` | 35 passed：`install.sh`≡`docs/install.sh` md5 一致；安装器对一致；版本资产 parity |
| G6 三平台构建 | CI 触发 Build Linux/macOS/Windows（tags `v*` 必跑） | 三 workflow success；Release 资产生成 + **资产版本元数据抽查**（exe/dmg 版本串 = 发布号） |
| G7 沙箱/安全 | `tests/test_sandbox_policy.py` + GC 严格模式 | sandbox 16 passed；无 unraisable 警告 |
| G8 JS/前端 | `node --check`（chat.html 内嵌 JS）+ 相关 UI 冒烟 | 语法通过；data-lang-key 键可解析 |
| G9 文档联动 | CHANGELOG 条目 / docs 增量 /（BP/站点 i18n 页按里程碑） | 与发布内容一致 |
| G10 版本一致性（**自动门**） | `test_version_parity_all_assets`（integrity 内）+ §4 核对 | 全部版本文件一致（含 nsi/spec/元组）；installer md5 对 |

## 4. 版本号与升级规程（v3.123.0 实测清单）

版本单一事实源：`src/__init__.py: __version__`。
升级需同步（**整批一次提交，禁止部分升级**；SOP v1.1 按三方 P2-2 补全构建文件清单）：

```
A. src/__init__.py __version__            B. src/core/__init__.py __version__
C. meshctx_desktop.py TITLE + 启动日志    D. version_info.txt StringStruct FileVersion/ProductVersion
E. version_info.txt FixedFileInfo filevers/prodvers 元组   (v1.0 漏项 → 3.123.0 缺陷根因)
F. install.sh VERSION                     G. docs/install.sh VERSION (≡F)
H. meshctx_setup.nsi: VERSION / VIProductVersion / FileVersion / ProductVersion (v1.0 漏项)
I. meshctx_desktop.spec: CFBundleShortVersionString / CFBundleVersion (v1.0 漏项)
J. CHANGELOG 新条目
```

硬性校验（R4 提交前脚本化执行，全过才可 commit/tag）：
```bash
md5sum install.sh docs/install.sh          # 必须两行同值 (md5 对)
python3 -m pytest tests/test_project_integrity.py -q   # 35 passed (含 G10 parity 自动断言,
                                                 # nsi/spec/元组/install 任一漏同步即 FAIL)
python3 -c "import src; assert src.__version__=='X.Y.Z'"
```
- 小步提交：功能提交与版本号提交分离；版本号提交 = 发布提交（R4）。
- 分支/回滚安全：每次里程碑前打 `pre-xxx` tag + `~/meshctx-backups/` 快照。

## 5. 发版序列（R0–R7，每次版本照此执行）

| 步 | 动作 | 输出/门 |
|---|---|---|
| R0 代码冻结 | 功能/修复合入 main；本地跑 G1–G5/G7–G9（G6/G10 需 tag 后全绿，R4 后回补） | 候选 HEAD |
| R1 rc1 送审 | 按 §8 模板送三方（范围 HEAD 差异/测试基线/请核项） | rc1 回执 |
| R2 收 P 项 | P2 必修 + 审计方指定"发版前必修"P3 → rc2 修复提交 | rc2 HEAD |
| R3 终验 | 三方终验回执全"放行" + **用户/产品 owner 最终放行**（显式确认） | 审计闭环声明 |
| R4 版本 bump | §4 全清单同步（A–J；G5 integrity 全绿为前提，任一 FAIL 不得 tag）+ CHANGELOG 定稿 + `git tag -a vX.Y.Z` | 发布提交 + tag |
| R5 资产构建 | 等 Build Linux/macOS/Windows（tags）全绿；核对 Release 资产清单 + **版本元数据抽查**（exe/dmg 版本串 = 发布号）；checksum(.sha256) 入正式门（P3-1, v3.124.0 起各 workflow 上传前生成） | 资产清单 |
| R6 公告 | Release notes + 三方/用户发版通知 | 回执留档 |
| R7 站点/文档 i18n | docs 网站页 10 语言/BP 更新（按里程碑范围，可并行不阻塞资产） | Pages 部署 ✅ + 线上抽查 |

## 6. 回滚规程

- 单 WP/单提交回滚：`git revert <commit>`（加法式提交保证可逆）；保留 backups 快照。
- 整版本回滚：切回上一 release tag（`v3.122.0` 等）→ 重跑 R5 资产 → 站点/installer 同步降级；
  Release 资产侧同步处理（旧资产替换/标注 deprecated，防误装）。
- backups：保留策略（里程碑快照保留 ≥ 最近 3 版）+ 定期恢复演练；状态数据（task_cards/routines JSON）
  若随版本改 schema，整版降级需只读保护（先备份再降）。
- 触发条件：任一 QA 门回归、线上 P0 事故、审计 P2 漏网。
- 回滚后必须复盘并更新本 SOP（防同类漏网）。

## 7. 审计接口（送审消息模板字段）

每次里程碑送审消息必须含：
```
【004meshctx → 三方审计方】<里程碑/版本> rcN 送审 (HEAD <sha>, 项目路由: meshctx)
■ 范围: <base>..<head> = 提交清单与 WP 对应
■ 测试基线: 全量 X passed/Y skipped/Z failed + 专项套件数
■ 请审计方核对 (P2/P3 格式): <逐项请核点>
■ 前置闭环说明 (若 rc2+)
■ HEAD <sha> 已推送 meshctx main
```
回执 P 项分级：P2=阻断 / P3=建议 / P4=排期（信息）；无 P2 且指定 P3 修复完成 → 可放行。

## 8. v3.123.0 走查（本 SOP 首例执行）

| 门 | 状态 | 证据 |
|---|---|---|
| G1 全量回归 | ✅ | 3717 passed / 59 skipped / 0 failed（三方独立重跑一致） |
| G2 专项 | ✅ | T0 套件 99 passed |
| G3 i18n | ✅ | i18n Guard CI success @5323eccc；277 i18n 相关本地 passed |
| G4 edition | ✅ | 36 路由清单无漂移；routines/telemetry/sandbox 新增已登记 |
| G5 完整性 | ⚠️→✅ | v1.0 走查失实更正（三方 P2-2）: release HEAD 5323eccc 实为 33 passed + 1 failed
  （test_version_info_has_correct_version 抓 filevers 元组未 bump）；v3.123.1 修复后 35 passed |
| G6 三平台 | ⏳ | v3.123.0 tag 推送后 Build Linux/macOS/Windows 运行中（i18n Guard ✅） |
| G7 沙箱 | ✅ | sandbox 16 passed |
| G8 JS | ✅ | node --check 通过 |
| G9 文档 | ✅(部分) | CHANGELOG [3.123.0] 定稿；docs 网站页 10 语言简介待 R7 |
| G10 版本 | ⚠️→✅ | v1.0 走查失实更正: 仅 7 文件串一致；nsi/spec/元组漏同步（P2-1, v3.123.0 资产元数据缺陷）
  → v3.123.1 全矩阵 3.123.1 + G10 parity 自动断言入 integrity |
| 审计门 | ✅ | rc1+rc2 三方两轮通过，审计闭环 |
| R0–R6 | ✅ | v3.123.1 全流程首跑（修复+tag+资产重建） |
| R7 | ⏳ | docs 网站页 10 语言简介（值守/治理/遥测）— 与 T1 并行（R7 不阻塞资产，v3.123.1 例外已含补发） |

## 9. 即用检查清单（每次发布复制使用）

- [ ] G1 全量回归 0 failed，基线不回退
- [ ] G2 受影响专项套件全绿
- [ ] G3 10 语言 i18n（Guard + 键一致性）
- [ ] G4 edition 门控 + 新增即登记
- [ ] G5 project_integrity（md5 对）
- [ ] G6 三平台 Build + 资产
- [ ] G7 沙箱/安全/GC
- [ ] G8 JS 语法 + UI 冒烟
- [ ] G9 CHANGELOG/docs/（BP/站点按范围）
- [ ] G10 版本 7 文件一致
- [ ] 三方审计 rc1 → rc2 → 终验放行
- [ ] R4 tag + R5 资产核对 + R6 公告 + R7 站点
- [ ] 回滚预案（pre tag + backups）就绪

---

## 10. 修订记录

### v1.0 → v1.1（2026-09-03，三方 SOP 审计 P2/P3 并入：002meshctx/002codex/004meshctx）
- P2-1（资产缺陷）: v3.123.0 资产元数据漏同步（version_info FixedFileInfo 元组/nsi/spec）→
  v3.123.1 全矩阵补发；§8 走查证据更正为实况。
- P2-2（§4 盲点根因）: 版本清单补全 A–J（含构建文件 H/I 与元组 E）；G5 = release 硬门
  （integrity 35 passed 全绿才可 tag）；G10 自动断言（test_version_parity_all_assets）。
- P3 并入: R5 checksum(.sha256) 正式门（v3.124.0 起）+ 资产版本元数据抽查；R0 措辞
  （G6/G10 tag 后回补）；R3→R4 显式用户放行步；回滚补 Release 资产侧 + backups 保留/演练。

*维护注：任何流程缺口在审计/发布中发现后，先改本 SOP 再改发布动作（流程优先）。*
*强制时点：SOP v1.1 起，v3.124.0 及后续所有版本强制执行本流程。*
