# MeshCtx Development Rules — 自动加载，每次会话强制执行

## 交付前铁律
1. 改了代码 → 构建 → 本地测试(test_desktop.py) → 零错误 → 再上传
2. 版本号用 sync_version.py，禁止手动sed
3. NSIS用v2.43的MUI_LANGDLL方案，不改顺序
4. Windows exe属性必须有版本号(VIProductVersion + pyi-set_version)
5. CI tag推送才上传Release，workflow_dispatch只构建不上传

## 禁止行为
- console=False (会丢失stdin导致崩溃)
- 跳过pre-commit测试门禁
- 同一个bug出现两次
- 不看编译器/工具输出就改代码
- 改了不测就交付

## CI/CD
- 发布流程: python3 tools/release.py X.Y.Z
- 测试全过(1725+)才能打tag
- CI自动构建NSIS+上传Release
- meshctx.com = GitHub Pages (不是47.120.0.239)

## 已修复的13个历史Bug
每个都有回归测试，修复后跑tests/test_project_integrity.py验证

## 关键文件
- NSIS: meshctx_setup.nsi (v2.43方案 + VIProductVersion + LangDLL.dll内置)
- Spec: meshctx_desktop.spec (console=True, _here=r'E:\Meshctx')
- 版本: tools/sync_version.py 一键同步10处
- 发布: tools/release.py 全门禁流程
