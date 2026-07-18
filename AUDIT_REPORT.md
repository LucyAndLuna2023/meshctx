# 🔴 MeshCtx 认证系统 — 完整审计报告

> 审计方: QA Profile | 日期: 2026-07-07 ~ 2026-07-18 | 五轮穷举审计
> 目标: 004meshctx 登录/注册/多语言/Profile系统

---

## 📊 总览: 40 bug → 22已修 / 18未修 (修复率 55%)

| 轮次 | 报告 | 发现 | P0 | P1 | 状态 |
|------|------|------|----|----|------|
| R1 | 首次验证 | #1-6 (6) | 2 | 4 | 7已修(544f40e) |
| R2 | 穷举+平台 | #7-11 (5) | 2 | 1 | 4已修(00e0d66) |
| R3 | 深入审计 | #12-24 (13) | 1 | 5 | 已修(1c4dedd) |
| R4 | 语言审计 | #25-32 (8) | 0 | 3 | 已修(d72d222+71cb80a) |
| R5 | 修复验证 | #33-40 (8) | 0 | 3 | 🔴 待修 |

---

## 🔴 P0 — 致命 (2个，均已修复 ✅)

### #12 Session不互通 (index.html vs profile.html) ✅ 已修
- **问题**: profile.html 之前用 Supabase SDK CDN (sb-*-auth-token)，index.html 用自定义 wrapper (meshctx-token)，两套 session 不互通
- **修复**: 1c4dedd — profile.html 改用 `_getSupabase()` + `meshctx-token`

### #1 注册误报 ✅ 已修 (544f40e)
- 注册成功/失败判断条件反了

---

## 🔴 P1 — 高危 (14个，4个待修)

### 已修复 ✅
| Bug | 描述 | 修复commit |
|-----|------|------------|
| #2 | 密码提示不显示 | 544f40e |
| #3 | signOut报错 | 544f40e |
| #4 | 重置密码无响应 | 544f40e |
| #5 | 邮箱参数缺失 | 544f40e |
| #6 | 密码验证<6 | 544f40e |
| #8 | _t()永远返回英文 | 00e0d66 |
| #14 | profile L['en']硬编码 | 1c4dedd |
| #15 | profile密码<6 vs auth.js<8 | 1c4dedd |
| #16 | profile 6处alert硬编码 | 1c4dedd |
| #25 | LEGAL fr/de假翻译(58/68键=英文) | d72d222 |

### 🔴 待修复
| Bug | 描述 |
|-----|------|
| **#33** | 11个新i18n键缺ar/it翻译 (auth_err_unknown等, 7/9语言) |
| **#34** | 键名不一致: `auth_btn_signin`(JS) vs `auth_signin_btn`(HTML) |
| **#35** | profile.html `getUserIdentities` 在wrapper中不存在 → 多邮箱功能无效 |

---

## 🟡 P2 — 中危 (8个，4个待修)

### 已修复 ✅
| Bug | 描述 |
|-----|------|
| #17 | catch块硬编码错误消息 |
| #18 | showAuthError 7处无i18n |
| #21 | CAPTCHA代码重复(signup/signin两份) |
| #29 | 按钮loading文字硬编码 |

### 🔴 待修复
| Bug | 描述 |
|-----|------|
| **#36** | `_captchaCode=''` 初始值 → canvas未渲染时CAPTCHA可绕过 |
| **#37** | LEGAL.html缺it/ar语言 (7语言 vs index.html 9语言) |
| #26 | index.html 33个modal键缺失 (后续确认:已覆盖) |
| #27 | LEGAL.html 0个auth键 |

---

## ⚪ P3 — 低危 (11个，5个待修)

### 已修复 ✅
| Bug | 描述 |
|-----|------|
| #22 | 全局变量明文 |
| #31 | updateUser发空Bearer |
| - | XSS: innerHTML → createElement+textContent |

### 🔴 待修复
| Bug | 描述 |
|-----|------|
| #38 | `_t()`(auth.js) 与 `_t_i18n()`(profile.html) 重复 |
| #39 | `addEmail`函数名误导 → 实际改主邮箱非添加 |
| #40 | LEGAL.html L对象JSON尾逗号语法错误 |
| #23 | stub功能 |
| #24 | 整页重译 |

---

## 📁 004修复记录

```
71cb80a fix: #29-31 additional hardcoded strings → i18n
d72d222 fix: 004qa第4轮 bugs #17-28 (LEGAL 783行真翻译)
1c4dedd fix: 第三轮审计 BUG#12-16 (P0 Session不互通 + 4 P1)
00e0d66 fix: 11 bugs (第二轮) — _t()、try-catch、redirect_to等
544f40e fix: 7 critical auth bugs (第一轮)
```

---

## ⚡ 当前最紧急 (TOP 3)

1. **#33** — 11个i18n键缺ar/it，阿拉伯语/意大利语用户看到英文错误提示
2. **#34** — 键名不一致导致未来修改时易遗漏
3. **#35** — `getUserIdentities`不存在，多邮箱功能完全不可用

---

*报告文件: ~/meshctx-public/AUDIT_REPORT.md*
*Redis: hub:dm:004 (91条JSON) / hub:dm:meshctx (纯文本)*

---

## 🟡 R6 (2026-07-18): CSS/字段名/死文件审计

| # | 级别 | 描述 | 状态 |
|---|------|------|------|
| #41 | P1 | display_name vs full_name 三端不一致 → Profile改名字导航栏不更新 | 🔴 |
| #42 | P1 | auth.css 14处使用未定义CSS变量 --surface/--accent/--fg-dim | 🔴 |
| #43 | P2 | #signin-captcha 缺少CSS样式 (只有#signup-captcha有) | 🔴 |
| #44 | P3 | legal-i18n.json (86KB) 未被 LEGAL.html 加载 | 🔴 |
| #45 | P3 | i18n/目录7个JSON文件不被任何页面加载 | 🔴 |

**关键发现:**
- `full_name` (注册时写入) vs `display_name` (Profile保存时写入) vs `full_name` (导航栏读取) → 三端断裂
- `--surface`, `--accent`, `--fg-dim` 在auth.css中使用14次但从未在:root定义
- index.html CSS变量定义: --bg, --bg2, --fg, --muted, --border, --purple 缺3个
