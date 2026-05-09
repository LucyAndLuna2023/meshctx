# meshctx 完整用户手册 v1.0

> 最后更新: 2026-05-10  
> 适用版本: meshctx v1.0

---

## 目录

1. [5分钟快速开始](#1-5分钟快速开始)
2. [配置AI模型](#2-配置ai模型)
3. [接入企业微信](#3-接入企业微信-完整踩坑指南)
4. [接入飞书](#4-接入飞书)
5. [接入Telegram](#5-接入telegram)
6. [聊天命令速查](#6-聊天命令速查)
7. [CLI命令速查](#7-cli命令速查)
8. [常见问题排错](#8-常见问题排错)

---

## 1. 5分钟快速开始

### 安装

```bash
# 前提: Python 3.10+
git clone https://github.com/meshctx/meshctx.git
cd meshctx
pip install -e .
pip install pycryptodome  # 企业微信加密需要
```

### 启动

```bash
meshctx start
# 访问 http://localhost:3000/ui/
```

### 开始聊天

```bash
meshctx model scan    # 自动发现模型
meshctx chat          # 开始对话
```

---

## 2. 配置AI模型

### DeepSeek（推荐，便宜强大）

```bash
# 1. 获取 API Key: https://platform.deepseek.com
# 2. 设置环境变量
export DEEPSEEK_API_KEY=sk-你的key

# 3. 自动扫描
meshctx model scan

# 4. 测试
meshctx model test deepseek:v4-pro -p "你好"

# 5. 开始聊天
meshctx chat
```

可用模型：`deepseek:v4-pro`(最强) | `deepseek:v4-flash`(极速) | `deepseek:chat`(V3) | `deepseek:reasoner`(R1推理)

### 阿里百炼

```bash
export BAILIAN_API_KEY=sk-你的key
meshctx model scan
```

### OpenAI

```bash
export OPENAI_API_KEY=sk-你的key
meshctx model scan
```

---

## 3. 接入企业微信（完整踩坑指南）

### 3.1 获取参数

进入企业微信管理后台 → 应用管理 → 自建应用：

| 参数 | 位置 |
|------|------|
| 企业ID (corp_id) | 我的企业 → 企业信息 |
| 应用Secret | 应用管理 → 自建应用 → 查看Secret |
| AgentId | 应用管理 → 自建应用 |
| Token | 接收消息 → 随机生成(10位以上) |
| EncodingAESKey | 接收消息 → 随机生成(43位) |

### 3.2 配置 meshctx

**方式一：聊天里配（推荐）**

```bash
meshctx chat
# 进入后敲:
/gateway
# 选 1.企业微信 → 按提示填入参数
```

**方式二：手动编辑配置文件**

`~/.meshctx/config.yaml`:
```yaml
gateway:
  enabled: true
  wechat:
    corp_id: "ww1234567890"
    corp_secret: "你的secret"
    agent_id: "1000001"
    token: "你的token"
    encoding_aes_key: "你的43位AESKey"
```

### 3.3 设置回调URL

企业微信管理后台 → 接收消息 → 设置API接收：

| 字段 | 值 |
|------|-----|
| URL | `http://你的服务器IP:3000/gateway/wechat` |
| Token | 你配置的token |
| EncodingAESKey | 你配置的43位key |

### 3.4 踩坑记录

| 问题 | 原因 | 解决 |
|------|------|------|
| 回调URL验证不通过 | FastAPI默认返回JSON `"xxx"`，企业微信要纯文本 `xxx` | 使用 `PlainTextResponse` 返回 |
| 验证通过但消息没回复 | 消息体是加密XML，需要AES解密 | 安装 `pycryptodome`，实现完整验签+解密+加密回复流程 |
| 代码更新后不生效 | Python .pyc缓存 | `find /opt/meshctx -name __pycache__ -exec rm -rf {} +` 后重启 |
| 本地配了远程收不到 | 企业微信回调必须公网可达 | 部署到有公网IP的服务器，回调URL填公网地址 |
| 端口不对 | 防火墙/安全组未开放 | 确认端口3000在安全组中开放 |

### 3.5 验证消息收发

```bash
# 查看服务器日志确认收到消息
tail -f /opt/meshctx/logs/server.log | grep gateway

# 日志中看到 200 OK 表示回调正常
# 看到 POST 请求表示收到用户消息
```

---

## 4. 接入飞书

在飞书开放平台创建应用，获取 `app_id` 和 `app_secret`。

聊天中配置：
```bash
meshctx chat
/gateway → 选 2.飞书 → 填入参数
```

或手动编辑 `~/.meshctx/config.yaml`:
```yaml
gateway:
  feishu:
    app_id: "cli_xxx"
    app_secret: "xxx"
```

---

## 5. 接入Telegram

在 @BotFather 创建Bot，获取 `bot_token`。

```bash
meshctx chat
/gateway → 选 3.Telegram → 填入 token
```

---

## 6. 聊天命令速查

| 命令 | 功能 |
|------|------|
| `/models` | 列出所有可用模型 |
| `/model deepseek:v4-flash` | 切换到极速模型 |
| `/model deepseek:v4-pro` | 切换到最强模型 |
| `/gateway` | 配置消息平台（企业微信/飞书/Telegram） |
| `/quit` | 退出聊天 |

---

## 7. CLI命令速查

```bash
meshctx start              # 启动服务 (端口3000)
meshctx stop               # 停止服务
meshctx status             # 查看状态
meshctx chat               # 开始聊天
meshctx model scan         # 扫描API Key
meshctx model list         # 列出模型
meshctx model test <id> -p "测试"  # 测试模型
meshctx web                # 打开Web控制台
```

Web控制台: `http://localhost:3000/ui/`  
API文档: `http://localhost:3000/docs`  
健康检查: `http://localhost:3000/health`

---

## 8. 常见问题排错

### meshctx 命令跳到了 Hermes

```bash
which meshctx          # 看指向哪里
hash -r                # 清除bash命令缓存
# 如果 ~/.local/bin/meshctx 指向 hermes，删掉它
rm ~/.local/bin/meshctx
```

### 聊天报 surrogate 错误

```bash
# 升级到最新代码即可，已自动修复
cd meshctx && git pull && pip install -e .
```

### 企业微信消息发来没回复

1. 确认服务器 `pycryptodome` 已安装: `pip install pycryptodome`
2. 确认 `~/.meshctx/config.yaml` 中的 token 和 encoding_aes_key 与企业微信后台一致
3. 查看日志: `tail -f /opt/meshctx/logs/server.log`
4. 确认 DEEPSEEK_API_KEY 环境变量已设置

### 服务启动失败

```bash
# 查看日志
journalctl -u meshctx -n 50

# 手动启动看报错
cd /opt/meshctx
./venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 3000
```
