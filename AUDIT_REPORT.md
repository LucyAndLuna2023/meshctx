# 🔴 R7审计报告 — OAuth/错误处理/部署一致性

> 审计方: QA | 日期: 2026-07-18 | 第七轮穷举审计
> 角度: OAuth流程、未捕获Promise、innerHTML XSS、部署一致性、语言选择器

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

---

## ✅ 确认修复 (dbe5f56)

004的commit dbe5f56已修复R6全部5个bug:
- #41 P1: display_name→full_name统一 ✅
- #42 P1: :root添加--surface/#1a1a2e --accent/#8b5cf6 --fg-dim/#64748b ✅
- #43 P2: #signin-captcha CSS样式已添加 ✅
- #44 P3: LEGAL.html注释legal-i18n.json用途 ✅
- #45 P3: 删除i18n/{de,en,es,fr,ja,ko,zh}.json 7个死文件 ✅

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

- **六轮总计**: 45 bug / 34已修 / 11未修
- **R7新增**: 6 bug
- **新总计**: 51 bug / 34已修 / 17未修

---

## ⚡ TOP 3 紧急

1. **#47 P1**: profile.html innerHTML XSS — 安全漏洞，需立即同步auth.js修复方案
2. **#48 P1**: Mac未部署auth — 主平台无登录功能
3. **#49 P2**: updateUser无.catch() — 用户修改Profile可能静默失败
