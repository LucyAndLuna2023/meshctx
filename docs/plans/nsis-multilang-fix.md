# NSIS多语言安装包 — 修复计划

## 根因分析（Systematic Debugging Phase 1-2）
- 试了MUI_LANGDLL → CI缺LangDLL.dll → 对话框静默消失
- 试了nsDialogs → SendMessage字符串指针问题 → 下拉框为空
- 试了v2.43恢复 → NSIS编译器警告LANGUAGE/PAGE顺序 → 运行时NS_ERROR
- **最简版（English only）构建成功：0错误0警告，152MB → 基础稳固**

## 方案：从基础版逐步加功能，每步验证
1. 基础版（已验证OK）→ 加VIProductVersion全部字段 → 构建验证
2. 加第2语言 → 构建验证
3. 加第3-7语言 → 构建验证
4. 加语言选择（用MUI_LANGDLL + 内置LangDLL.dll）→ 构建验证
5. 上传Release

## TDD：每个修改前写测试，改后验证
