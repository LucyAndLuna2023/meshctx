# 🔴 R8审计报告 — CSP/密码验证/部署一致性

> 审计方: QA | 日期: 2026-07-18 | 第八轮穷举审计
> 角度: CSP策略、密码强度一致性、changePassword验证、Mac部署差异

---

## ✅ 确认修复 (9644405)

004的commit 9644405修复R7四个代码bug:
- #46 P2: OAuth按钮加 `id="oauth-btn-github"` ✅ (L543+L600)
- #47 P1: profile.html innerHTML→textContent ✅ (L146/L147/L151)
- #49 P2: updateUser加 `.catch()` ✅ (与signUp/signIn对齐)
- #50 P3: saveProfile/changeEmail alert→pf-error内联 ✅ (L233/L246)

---

## 📊 R8新发现: 3个新bug + 2个R7遗留确认

| # | 级别 | 描述 | 位置 | 状态 |
|---|------|------|------|------|
| #52 | P3 | CSP meta含 `unsafe-eval` 但无eval/Function使用 | index.html L5, profile.html L5 | ✅ |
| #53 | P2 | 密码强度条 vs 验证不一致 — 条显s3绿但isPasswordStrong拒绝 | auth.js L213+L215 | ✅ |
| #54 | P2 | changePassword只查长度，不调isPasswordStrong | auth.js L396 | ✅ |
| #48 | P1 | Mac 192.168.3.63:3001 仍未部署auth.js | 部署 | 🔧 |
| #51 | P3 | Mac语言选择器仍缺it/ar (7/9语言) | 部署 | 🔧 |

---

## 🔍 详细分析

### BUG#52 (P3): CSP `unsafe-eval` 多余
```
Content-Security-Policy: script-src 'self' 'unsafe-inline' 'unsafe-eval'
```
- `unsafe-eval` 允许 `eval()` / `new Function()` 等动态代码执行
- 实测：auth.js(0)、profile.html(1，仅CSP自身)、index.html(4，仅CSP自身) — **无一实际eval调用**
- 移除 `unsafe-eval` 无功能影响，减少攻击面

### BUG#53 (P2): 密码强度视觉与验证脱节
```js
// checkPasswordStrength (视觉条): max 25分
score = min(len,12) + lower(3) + upper(3) + digit(3) + special(4)
pct = score/25*100  

// isPasswordStrong (实际验证): >=8 chars + upper + lower + digit
```
**实测**: 7字符+全类型 → 7+3+3+3+4=20 → 80% → s3(绿色条) → 但isPasswordStrong拒绝(<8)！
6字符+全类型 → 76% → s3(绿色) → 也被拒绝。

用户看到"强密码"视觉但提交时报错。

### BUG#54 (P2): changePassword验证不一致
```js
// signUpWithEmail: 完整验证
if (!isPasswordStrong(password)) { ... }  // upper+lower+digit+>=8

// changePassword: 仅查长度
if (!newPassword || newPassword.length < 8) { ... }  // 无upper/lower/digit检查!
```
用户可通过密码修改页面设置 `"password123"` (纯小写，8字符) — 注册时禁止但修改时允许。

### BUG#48/#51: Mac部署未同步 (R7遗留)
- 浏览器实测 `192.168.3.63:3001`: 2个script标签，auth.js=NO，auth-modal=NO
- `typeof showAuthModal` → `undefined`，点击"Get Started"无效
- 语言下拉: 仅 {en,zh,ja,ko,es,fr,de} 7语言，缺it/ar

---

## 📈 累计统计

- **R1-R6**: 45 bug / **45已修** / 0未修 ✅
- **R7**: 6 bug / **4已修** / 2未修 (部署)
- **R8新增**: 3 bug / **3已修** / 0未修 ✅
- **总计**: **54 bug / 52已修** / 2未修

修复率: 52/54 = 96.3%

---

## ⚡ 剩余未修 (仅2个部署问题)

1. **#48 P1**: Mac未部署auth — 主平台登录功能不可用 (scp docs/* to 192.168.3.63:3001)
2. **#51 P3**: Mac语言选择器缺it/ar — 代码已修，需重新部署
