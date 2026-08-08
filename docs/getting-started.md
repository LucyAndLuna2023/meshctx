# meshctx 快速入门

## 安装

### 一键安装（推荐）

```bash
curl -fsSL https://cdn.jsdelivr.net/gh/LucyAndLuna2023/meshctx@main/install.sh | bash
```

安装脚本会自动：
- 停止旧版本服务
- 检查 Python 3.10+
- 下载最新源码包
- 创建虚拟环境并安装依赖
- 安装完成后询问是否立即启动

### 手动安装

```bash
git clone https://github.com/LucyAndLuna2023/meshctx.git
cd meshctx
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## 快速开始

```bash
meshctx setup      # 配置 API Key（仅首次）
meshctx start      # 启动服务
```

然后访问 **http://localhost:3001/ui**

### 常用命令

| 命令 | 说明 |
|------|------|
| `meshctx start` | 启动服务（默认端口 3001） |
| `meshctx start --port 8080` | 指定端口启动 |
| `meshctx stop` | 停止服务 |
| `meshctx status` | 查看运行状态 |
| `meshctx setup` | 配置 API Key 和模型 |

## 更新

重新运行安装脚本即可覆盖升级：

```bash
curl -fsSL https://cdn.jsdelivr.net/gh/LucyAndLuna2023/meshctx@main/install.sh | bash
```

安装脚本会自动停止旧服务、覆盖安装。

## 故障排查

### 页面显示异常 / 版本不对

这是浏览器缓存了旧页面。**按 Ctrl+Shift+R 强制刷新**即可。

### 端口 3001 被占用

```bash
# 查看占用进程
lsof -i :3001

# 停止旧 meshctx
meshctx stop
# 或强制停止
pkill -9 -f uvicorn
```

### Python 版本过低

需要 Python 3.10+：

```bash
# Ubuntu/Debian
sudo apt install python3.12 python3.12-venv

# macOS
brew install python@3.12
```

### 下载失败

国内网络可设置代理：

```bash
export https_proxy=http://127.0.0.1:7890
curl -fsSL https://cdn.jsdelivr.net/gh/LucyAndLuna2023/meshctx@main/install.sh | bash
```

### 手动验证安装

```bash
cd ~/.meshctx && source venv/bin/activate
python -c "from src.core import __version__; print(__version__)"
# 应输出: 3.118.0
```
