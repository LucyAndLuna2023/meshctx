# 🔴 R7+R8 审计报告 — OAuth/错误处理/部署一致性 + CSP/pwd-bar/changePwd

> 审计方: QA | 日期: 2026-07-18 | 第七轮+第八轮穷举审计
> 角度: OAuth流程、未捕获Promise、innerHTML XSS、部署一致性、语言选择器、CSP、密码强度、修改密码

---

## 📊 R7新发现: 6个bug

| # | 级别 | 描述 | 位置 |
|---|------|------|------|
| #46 | P2 | OAuth按钮缺少ID → btn.disabled无效 | index.html L543+L600 |
| #47 | P1 | profile.html _refreshI18n innerHTML XSS | profile.html L146/L150 |
| #48 | P1 | Mac 192.168.3.63:3001 未部署auth.js | 部署 |
| #49 | P2 | updateUser wrapper缺少.catch() | auth.js L66-73 |
| #50 | P3 | saveProfile/changeEmail用alert报错 | profile.html L232/L245 |
| #51 | P3 | Mac语言选择器缺it/ar (7/9语言) | Mac部署版 |

## 🟡 R8 (2026-07-18): CSP / pwd-bar / changePwd 审计

| # | 级别 | 描述 | 状态 |
|---|------|------|------|
| #52 | P1 | CSP `unsafe-eval` 在所有9个HTML中被允许但从未使用 → 移除，并添加 `form-action`/`base-uri` | ✅ 已修 |
| #53 | P1 | profile.html changePassword 缺少密码强度条（仅signup有） | ✅ 已修 |
| #54 | P1 | `doChangePassword()` 仅检查长度≥8，无强度验证、无确认字段、无成功消息文本、无.catch() | ✅ 已修 |

### 修复详情 (commit: 0f71dce + cherry-pick 9644405)
- **#52**: 9个HTML文件移除 `unsafe-eval`，添加 `form-action 'self' https://xtyjsjlkljzdgvqpskyk.supabase.co; base-uri 'self'; object-src 'none'`
- **#53**: auth.js 添加通用 `_checkPwdStrength()`，profile.html 添加强度条HTML + oninput事件
- **#54**: `doChangePassword()` 全面重写 — 使用 `isPasswordStrong()`、添加确认密码匹配检查、显示 `profile_pwd_changed` i18n消息、try/catch网络错误处理

---

## ✅ 确认修复 (9644405 R7 + 0f71dce R8)

9644405已修复R7全部4个代码bug:
- #46 P2: 两处btn-oauth-github加 `id=oauth-btn-github` ✅
- #47 P1: profile.html L146/L150 innerHTML→textContent ✅
- #49 P2: updateUser wrapper加 `.catch()` ✅
- #50 P3: saveProfile/changeEmail alert→pf-error内联显示 ✅

0f71dce已修复R8全部3个bug:
- #52 P1: CSP移除unsafe-eval + 添加form-action/base-uri + object-src:none ✅
- #53 P1: profile.html changePassword强度条 ✅
- #54 P1: doChangePassword isPasswordStrong + 确认密码 + 成功消息 + .catch ✅

---

## 🔍 详细分析

### BUG#46 (P2): OAuth按钮缺少ID
```html
<!-- 当前 (两处): -->
<button class="btn-oauth btn-oauth-github" onclick="signInWithOAuth('github')">

<!-- auth.js L351 查找: -->
var btn = document.getElementById('oauth-btn-' + provider); // 'oauth-btn-github' → null!
```
**影响**: btn永远为null → OAuth期间按钮不禁用（可重复点击）、错误后不恢复。

### BUG#47 (P1): profile.html innerHTML XSS
```js
// profile.html L146:
cn.innerHTML = val;   // ⚠️ XSS — i18n值注入HTML
// profile.html L150:
el.innerHTML = val;   // ⚠️ XSS
```
auth.js已在R5修复（改用textContent/createElement），profile.html未同步。landing.json的i18n值被篡改即可注入。

### BUG#48 (P1): Mac平台未部署auth
实测192.168.3.63:3001: 页面仅2个script，无auth.js，无Sign In按钮。与git repo最新代码不一致。Linux/Win平台同样DOWN。

### BUG#49 (P2): updateUser无.catch()
signUp/signInWithPassword/resetPasswordForEmail都有`.catch()`兜底，唯独updateUser没有:
```js
return fetch(...).then(r=>r.json().then(d=>({data:r.ok?d:null,error:r.ok?null:d})));
// 无.catch() → 网络错误时Promise拒绝且未捕获
```
saveProfile()和changeEmail()调用此函数，网络故障时静默失败。

### BUG#50 (P3): alert报错不一致
saveProfile用`alert()`、changeEmail用`alert()`，但doChangePassword用内联`errEl.style.display='block'`。用户体验不一致。

### BUG#51 (P3): 语言选择器缺it/ar
Mac页面lang dropdown只有7语言(en/zh/ja/ko/es/fr/de)，缺少Italian和Arabic。landing.json中it/ar数据完整但UI不可达。

---

## 📈 累计统计

- **八轮总计**: 54 bug / 40已修 / 14遗留
  - R7新增6 + R8新增3 = 54 total
  - 已修: R6(5) + R7(4) + R8(3) = 12 (本轮) + 前6轮28 = 40
- **遗留**: #48(P1 Mac部署), #51(P3 Mac语言) — 代码已修，待192.168.3.63:3001重新部署

---

## ⚡ 当前状态

- R7代码修复(9644405): ✅ 已合并到gh-pages
- R8代码修复(0f71dce): ✅ 已在gh-pages
- Mac部署(#48/#51): ⏳ 待192.168.3.63:3001重新部署
