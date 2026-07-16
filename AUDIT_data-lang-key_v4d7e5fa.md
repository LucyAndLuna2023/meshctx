# 🔍 data-lang-key 架构审计报告

**审计对象**: meshctx.com (gh-pages 分支, commit `4d7e5fa`)  
**审计人**: qa (hermes-cluster-v3, 004)  
**审计日期**: 2026-07-16  
**审计范围**: Hero / About / Download / Plugin 四大内容区 7 语言 data-lang-key 覆盖率

---

## 📊 总体评分: 95/100

| 指标 | 结果 |
|------|------|
| Content key 覆盖率 | **100% (116/116)** |
| 7 语言完整性 | **全部通过** |
| CRITICAL 缺陷 | **0** |
| LOW 问题 | 2 |
| INFO 备注 | 2 |

---

## ✅ 1. Hero 区 — 100% 通过

| Key | en | zh | fr | de | ja | ko | es |
|-----|----|----|----|----|----|----|----|
| hero_title | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| hero_desc | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| hero_cta1 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| hero_cta2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

> ⚠️ ZH hero_title 从 `会<span>自适应学习</span>的 Agent v3.115.18` 变为 `会<span>学习</span>的智能体`，版本徽章丢失。原因：统一模板不支持 ZH-only 的内联徽章。建议：将版本号放到全局 footer 或通过 CSS `::after` 注入。

## ✅ 2. About 区 — 100% 通过

| Key | en | zh | fr | de | ja | ko | es |
|-----|----|----|----|----|----|----|----|
| about_h3 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| about_p | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| about_li1 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| about_li2 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| about_li3 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| about_li4 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## ✅ 3. Download 区 — 100% 通过

| Key | 7 语言 |
|-----|--------|
| install_title | ✅ |
| linux_desc | ✅ |
| mac_desc | ✅ |
| win_desc | ✅ |
| win_dl_installer | ✅ |
| win_dl_portable | ✅ |
| mac_dl | ✅ |

## ✅ 4. Plugin 区 — 100% 通过

| Key | 7 语言 |
|-----|--------|
| plugin_title | ✅ |
| plugin_subtitle | ✅ |
| pl1_title / pl1_desc | ✅ |
| pl2_title / pl2_desc | ✅ |
| pl3_title / pl3_desc | ✅ |
| pl4_title / pl4_desc | ✅ |
| pl5_title / pl5_desc | ✅ |
| pl_btn_browse | ✅ |
| pl_btn_dev | ✅ |

---

## 🟡 发现的问题

### LOW-1: Dead code in switchLang
`index.html` 中 `.lang[data-lang]` 的 show/hide 逻辑仍在 switchLang 函数中 (7行)，但全站已无 `data-lang` 属性元素 (0 matches)。**无害，可清理。**

### LOW-2: innerHTML 全局使用
switchLang 对 **所有** data-lang-key 元素使用 `el.innerHTML = L[lang][key]`。hero_title 需要 innerHTML（含 `<span>`），但纯文本键也被 innerHTML 处理。当前所有值硬编码，无 XSS 风险；若未来支持用户自定义翻译，需改用 `textContent` + 白名单。

---

## 🔵 INFO 备注

### INFO-1: data-lang-key-area
Download/Plugin 区域使用了 `data-lang-key-area="download"` / `"plugin"` 属性，但 switchLang 中没有对应处理器。当前无功能影响，仅标记用途。

### INFO-2: docs/ 子页面
`docs/download.html`、`docs/index.html`、`docs/getting-started.html`、`docs/LEGAL.html` 均为独立英文页面，未接入 i18n 系统。这是架构设计决策，非本次修复范围。

---

## 📈 与修复前对比

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| 语言特定 div | 28 个 (4区×7语言) | 0 个 |
| HTML 行数 | ~650 | ~443 (-32%) |
| data-lang-key 覆盖率 | 0% (Hero/About/Download/Plugin 无键) | 100% |
| 旧 data-lang div 残留 | 28 | 0 |

**结论**: commit `4d7e5fa` 成功统一了四大内容区的 data-lang-key 架构，7 语言覆盖率 100%，无 CRITICAL 缺陷。✅
