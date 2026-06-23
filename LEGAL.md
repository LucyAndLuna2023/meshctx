# MeshCtx 法律声明

## 一、开源许可 (License)

MeshCtx 采用 **双重许可 (Dual License)** 结构：

### 框架层 — AGPLv3 开源
MeshCtx 平台框架（Web UI、API路由、插件系统、Chat界面、安装程序）遵循
**GNU Affero General Public License v3 (AGPLv3)**。

这意味着：
- ✅ 你可以自由使用、修改、分发框架代码
- ✅ 你可以查看所有源码
- ✅ 你可以提交 Pull Request
- ⚠️ 如果你修改了 AGPLv3 代码并对外提供服务，必须公开你的修改
- 完整文本: https://www.gnu.org/licenses/agpl-3.0.html

### 核心大脑层 — 专有许可 (Proprietary)
以下模块为 MeshCtx **核心知识产权 (Core IP)**，采用 **源码可用 (Source Available)** 许可：

| 模块 | 算法 | 保护原因 |
|------|------|----------|
| `super_brain.py` | 13区域全脑仿真架构 | 核心编排逻辑 |
| `brain_router.py` | Gumbel-Softmax网关路由 | 动态路由决策 |
| `free_energy.py` | Friston自由能原理实现 | 惊讶度量与信念更新 |
| `active_inference.py` | 主动推理引擎 | 探索-利用平衡 |
| `global_workspace.py` | Baars-Dehaene全局工作空间 | 多Agent竞争广播 |
| `homeostasis.py` | 内稳态调节器 | 自适应资源分配 |
| `metacognition.py` | 元认知监控引擎 | 自我评估与策略选择 |
| `hybrid_reasoning.py` | 混合推理调度器 | 探索模式切换 |

这些模块的使用限制：
- ✅ 源码公开，可审查、学习
- ✅ 非商业用途（学术研究、个人使用）免费
- ❌ **商业用途（SaaS、企业部署、商业产品集成）必须获取商业授权**
- ❌ 不得删除或修改模块中的版权声明
- ❌ 不得将核心大脑算法提取到其他项目中

### 商业授权
商业使用请联系：**license@meshctx.com**

## 二、免责声明 (Disclaimer of Warranty)

MeshCtx（以下简称"本软件"）按"原样"（AS IS）提供，不提供任何明示或暗示的担保，包括但不限于：

- 适销性担保 (Merchantability)
- 特定用途适用性担保 (Fitness for a particular purpose)
- 安全性担保 (Security)
- 不侵权担保 (Non-infringement)
- 可用性担保 (Availability)

用户 **自行承担** 使用本软件的全部风险。在任何情况下，MeshCtx 的开发者、维护者、贡献者（以下统称"项目方"）均不对因使用或无法使用本软件而产生的任何直接、间接、附带、特殊、惩戒性或后果性损害承担责任，包括但不限于：

- 数据丢失或损坏
- 系统崩溃或损坏
- 业务中断或收入损失
- 第三方索赔
- 由 Agent 自主执行的操作导致的任何后果
- 由第三方开发的插件、技能（Skill）或连接器导致的任何损失

**关于第三方插件（Skills）：**
MeshCtx 支持第三方开发者提交和发布插件。这些插件未经项目方安全审计。用户在安装和使用任何第三方插件前应自行评估风险。项目方不对第三方插件的内容、安全性、合法性承担责任。

**关于 AI Agent 行为：**
MeshCtx 是一个 AI Agent 框架，其行为受模型、配置和用户指令影响。项目方不对 Agent 产生的具体输出内容、决策或行为承担责任。用户应在其使用场景中自行审查和监控 Agent 行为。

## 三、知识产权声明 (Intellectual Property Notice)

MeshCtx 代码版权归 MeshCtx 项目方所有，受中华人民共和国著作权法及国际版权条约保护。

- 源代码中的版权声明不得删除或修改
- 项目名称 "MeshCtx" 及 logo 为项目方商标，未经授权不得用于商业目的
- 核心大脑模块（详见§一）受专有许可保护
- 商业授权需与版权方另行签订书面协议

## 四、服务条款 (Terms of Service)

### 网站使用
访问和使用 meshctx.com 即表示您同意以下条款：

1. **内容仅供参考** — 网站上的文档、博客、示例代码仅供参考，不构成专业建议
2. **不保证可用性** — 网站可能因维护或其他原因暂停服务
3. **禁止滥用** — 禁止对网站进行反向工程、爬虫抓取（除搜索引擎外）、DDoS 攻击等
4. **链接到第三方** — 网站可能包含第三方链接，项目方不对第三方内容负责

### 社区行为准则
参与 MeshCtx 社区（GitHub Issues、Discord 等）需遵守：
- 尊重他人，禁止人身攻击、歧视言论
- 禁止发布 spam、广告、恶意软件
- 违反者可能被移除社区访问权限

## 五、隐私政策 (Privacy Policy)

### 我们收集什么
- **GitHub 公开信息**：当您提交 Issue 或 PR 时，GitHub 用户名和头像
- **邮箱**：当您订阅邮件列表或联系商业授权时
- **网站访问日志**：标准服务器日志（IP、User-Agent、访问时间）

### 我们不收集
- ❌ 不追踪您的浏览行为
- ❌ 不向第三方出售数据
- ❌ 不在您的设备上放置追踪 Cookie（除必要的会话 Cookie）

### 数据用途
- 改进项目和服务
- 回复您的咨询
- 遵守法律义务

## 六、联系方式

- 商业授权：license@meshctx.com
- 一般咨询：support@meshctx.com
- 法律事务：legal@meshctx.com

---

*最后更新：2026年5月14日*
