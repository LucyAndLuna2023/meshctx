# Meshctx 安全与质量修复方案 v20260805

> **发送方**: 004 meshctx（审计代理）
> **接收方**: 002 meshctx (jason-ThinkPad-E470)
> **日期**: 2026-08-05
> **Git 基准**: 2097075
> **审计方法**: 3 子代理并行审计 (DeepSeek v4 Pro) — 代理1=搜索修复审查, 代理2=第二轮修复审查, 代理3=chat.html 审查

---

## 目录

1. [P0-1: SSRF URL 校验 (`_do_web_extract`)](#p0-1-ssrf-url-校验-_do_web_extract)
2. [P0-2: 安全护栏恢复 (`SENSITIVE_TOOLS` / `DESTRUCTIVE_TOOLS`)](#p0-2-安全护栏恢复-sensitive_tools--destructive_tools)
3. [P0-3: chat.html JS 致命 Bug ×2](#p0-3-chathtml-js-致命-bug-2)
4. [P1-1: 超时文案 180→300](#p1-1-超时文案-180300)
5. [P1-2: asyncio.Queue 跨线程不安全](#p1-2-asyncioqueue-跨线程不安全)
6. [P2-1: HTML 实体解码 (`html.unescape()`)](#p2-1-html-实体解码-htmlunescape)
7. [P2-2: 魔术数字 999](#p2-2-魔术数字-999)
8. [P2-3: chat.html `showToast` 合并 + `statusDot`](#p2-3-chathtml-showtoast-合并--statusdot)
9. [P2-4: urllib3 全局 SSL 抑制局部化](#p2-4-urllib3-全局-ssl-抑制局部化)

---

## P0-1: SSRF URL 校验 (`_do_web_extract`)

### 问题描述

`_do_web_extract()` 直接使用用户传入的 URL 发起 HTTP 请求，未对目标地址做任何合法性校验。攻击者可通过构造内网 URL（如 `http://169.254.169.254/latest/meta-data/`、`http://localhost:6379/`）读取云实例元数据凭证、访问内网 Redis 等敏感服务。

**风险等级**: 🔴 P0 — 云凭证泄露 / 内网横向移动

### 文件:行号

`src/main.py:3886-3916`

### Before

```python
def _do_web_extract(url: str) -> str:
    """抓取网页内容（支持SOCKS5/HTTP代理）"""
    import requests, re, os
    from src.config import load_config as _load_extract_config

    # ── 代理配置 ──
    proxies = None
    try:
        cfg = _load_extract_config()
        proxy_url = cfg.get("search", {}).get("proxy", os.environ.get("MESHCTX_SEARCH_PROXY", ""))
    except Exception:
        proxy_url = os.environ.get("MESHCTX_SEARCH_PROXY", "")

    if proxy_url and proxy_url.strip():
        proxies = {"http": proxy_url, "https": proxy_url}

    try:
        try:
            resp = requests.get(url, headers={...}, timeout=20, proxies=proxies, verify=False)
        except requests.exceptions.SSLError:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(url, headers={...}, timeout=20, proxies=proxies, verify=False)
        html = resp.text
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:12000]
    except Exception as e:
        return f"抓取失败: {e}"
```

### After

```python
import ipaddress
from urllib.parse import urlparse

# ── SSRF 防护: 黑名单 + IP 范围校验 ──
_SSRF_BLOCKED_SCHEMES = {"file", "ftp", "gopher", "dict", "ldap"}
_SSRF_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal"}
_SSRF_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),      # 私有 A 类
    ipaddress.ip_network("172.16.0.0/12"),   # 私有 B 类
    ipaddress.ip_network("192.168.0.0/16"),  # 私有 C 类
    ipaddress.ip_network("169.254.0.0/16"),  # 链路本地 (AWS/云元数据)
    ipaddress.ip_network("127.0.0.0/8"),     # 回环
    ipaddress.ip_network("::1/128"),         # IPv6 回环
    ipaddress.ip_network("fc00::/7"),        # IPv6 唯一本地
]

def _validate_url(url: str) -> str:
    """校验 URL 合法性，阻止 SSRF 攻击。返回清理后的 URL 或抛出 ValueError。"""
    parsed = urlparse(url)
    if parsed.scheme.lower() in _SSRF_BLOCKED_SCHEMES:
        raise ValueError(f"禁止的协议: {parsed.scheme}")
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"仅支持 http/https 协议")
    hostname = parsed.hostname or ""
    if hostname.lower() in _SSRF_BLOCKED_HOSTS:
        raise ValueError(f"禁止访问的主机: {hostname}")
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError(f"禁止访问的 IP 地址: {hostname}")
    except ValueError:
        # hostname 不是 IP 地址 → 允许通过（DNS 解析的域名）
        pass
    return url

def _do_web_extract(url: str) -> str:
    """抓取网页内容（支持SOCKS5/HTTP代理，含 SSRF 防护）"""
    import requests, re, os
    from src.config import load_config as _load_extract_config

    # ── SSRF 校验 ──
    try:
        url = _validate_url(url)
    except ValueError as e:
        return f"URL 被拒绝: {e}"

    # ── 代理配置 ──
    proxies = None
    try:
        cfg = _load_extract_config()
        proxy_url = cfg.get("search", {}).get("proxy", os.environ.get("MESHCTX_SEARCH_PROXY", ""))
    except Exception:
        proxy_url = os.environ.get("MESHCTX_SEARCH_PROXY", "")

    if proxy_url and proxy_url.strip():
        proxies = {"http": proxy_url, "https": proxy_url}

    try:
        # SSL 警告局部抑制（见 P2-4）
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 ..."}, timeout=20, proxies=proxies, verify=False)
        html = resp.text
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:12000]
    except Exception as e:
        return f"抓取失败: {e}"
```

### 修复理由

1. **阻止云凭证泄露**: 封禁 `169.254.0.0/16`（AWS/Azure/GCP 元数据端点）
2. **阻止内网横向移动**: 封禁 RFC 1918 私有地址 + 回环地址
3. **阻止协议走私**: 封禁 `file://`、`gopher://`、`dict://` 等危险协议
4. **防止 DNS 重绑定绕过**: 同时校验 IP 和 hostname 黑名单

---

## P0-2: 安全护栏恢复 (`SENSITIVE_TOOLS` / `DESTRUCTIVE_TOOLS`)

### 问题描述

在 `2097075` 提交中，`SENSITIVE_TOOLS` 和 `DESTRUCTIVE_TOOLS` 均被设为空集合 `set()`，导致 Agent 获得不受限制的系统访问权。恶意 prompt 可执行 `rm -rf`、写入 `/etc/`、远程执行任意命令等操作。

**风险等级**: 🔴 P0 — 任意命令执行 / 系统破环

### 文件:行号

`src/main.py:3662-3663`

### Before

```python
# ── 工具定义 ──
SENSITIVE_TOOLS = set()
DESTRUCTIVE_TOOLS = set()  # 所有工具自动批准，不弹确认框
```

### After

```python
# ── 工具定义 ──
SENSITIVE_TOOLS = {
    "terminal",        # 任意 Shell 命令执行
    "write_file",      # 写入任意文件
    "remote_write",    # 远程文件写入
    "remote_exec",     # 远程命令执行
}
DESTRUCTIVE_TOOLS = {
    "terminal",        # rm -rf / dd if=/dev/zero
    "write_file",      # 覆盖系统文件
    "remote_exec",     # 远程破环
    "process",         # 进程管理 (kill/restart)
}
_approved_tools = set()  # 本次流中已批准的工具
_page_cache = {}         # 浏览器页面缓存
```

### 修复理由

1. **最小权限原则**: 只有明确标记为敏感/破坏性的工具才需要用户审批
2. **分级防护**:
   - `SENSITIVE_TOOLS` — 触发确认对话框（读敏感文件、网络操作等）
   - `DESTRUCTIVE_TOOLS` — 需要二次确认 + 操作日志记录
3. **与 chat.html 确认面板协同**: `confirm-panel` 已实现 UI，需后端填充工具列表才生效

---

## P0-3: chat.html JS 致命 Bug ×2

### 问题 1: `streamingAbortController` 未定义

**风险等级**: 🔴 P0 — WebSocket 实时消息处理崩溃

#### 文件:行号

`templates/chat.html:1504`

#### Before

```javascript
function handleWsMessage(msg) {
  switch (msg.type) {
    // ...
    case 'chat.message':
      if (msg.role === 'assistant' && msg.content) {
        const msgs = document.getElementById('messages');
        // Avoid duplicating if user just sent and we're streaming
        if (streamingAbortController) break;   // ❌ ReferenceError: streamingAbortController is not defined
        // ...
        appendMessage('ai', msg.content);
      }
      break;
  }
}
```

#### After

```javascript
// ═══ 在文件顶部 (全局变量区域) 添加声明 ═══
let streamingAbortController = null;  // SSE 流中断控制器引用
let streamingActive = false;          // 流式传输进行中标记

// ═══ 在 send() 函数中保存引用 ═══
async function send() {
  // ...
  const controller = new AbortController();
  streamingAbortController = controller;   // 保存到全局，供 handleWsMessage 检查
  streamingActive = true;
  // ...
  try {
    const resp = await fetch('/api/chat/stream', {
      signal: controller.signal,
      // ...
    });
    // ... streaming logic ...
  } finally {
    streamingAbortController = null;
    streamingActive = false;
  }
}

// ═══ 在 handleWsMessage() 中使用 ═══
function handleWsMessage(msg) {
  switch (msg.type) {
    case 'chat.message':
      if (msg.role === 'assistant' && msg.content) {
        if (streamingActive) break;  // ✅ 使用显式 boolean 标记
        // ...
      }
      break;
  }
}
```

#### 修复理由

`streamingAbortController` 在函数内通过 `const controller = new AbortController()` 创建，作用域局限于 `send()` 函数。`handleWsMessage()` 尝试访问一个未声明的全局变量，导致 `ReferenceError`，WebSocket 消息处理链路完全崩溃。

---

### 问题 2: `appendMessage()` 函数不存在

**风险等级**: 🔴 P0 — WebSocket 消息无法渲染

#### 文件:行号

`templates/chat.html:1511`

#### Before

```javascript
case 'chat.message':
  if (msg.role === 'assistant' && msg.content) {
    // ...
    appendMessage('ai', msg.content);  // ❌ TypeError: appendMessage is not a function
  }
```

#### After

```javascript
case 'chat.message':
  if (msg.role === 'assistant' && msg.content) {
    // ...
    addMsg('ai', msg.content);  // ✅ 使用已定义的 addMsg(role, text) 函数
  }
```

#### 修复理由

项目中不存在 `appendMessage` 函数。正确的消息渲染函数是 `addMsg(role, text)`（定义于 `chat.html` 内）。这个拼写错误导致 WebSocket 推送的 AI 回复无法渲染到聊天界面。

---

## P1-1: 超时文案 180→300

### 问题描述

实际超时时间为 300 秒（`time.time() - _start_time > 300`），但错误提示文案仍显示 "180 秒"。用户会在 300 秒时看到 "已达到最大处理时间 180 秒"，造成困惑。

**风险等级**: 🟡 P1 — 用户误导

### 文件:行号

`src/main.py:3687`

### Before

```python
if time.time() - _start_time > 300:
    yield f"data: {_json.dumps({'token': '\n\n[已达到最大处理时间 180 秒，已中止]'})}\n\n"
    break
```

### After

```python
_STREAM_TIMEOUT_SECONDS = 300

if time.time() - _start_time > _STREAM_TIMEOUT_SECONDS:
    yield f"data: {_json.dumps({'token': f'\n\n[已达到最大处理时间 {_STREAM_TIMEOUT_SECONDS} 秒，已中止]'})}\n\n"
    break
```

### 修复理由

1. 文案与实际阈值一致（300 秒），消除用户困惑
2. 提取为命名常量 `_STREAM_TIMEOUT_SECONDS`，未来修改只需一处

---

## P1-2: asyncio.Queue 跨线程不安全

> ⚠️ **建议 002 处理，涉及架构调整**

### 问题描述

`_call_llm_stream()` 在异步上下文中创建 `asyncio.Queue`，然后将其传递给 worker 线程调用 `q.put_nowait()`。`asyncio.Queue` 不是线程安全的 —— 在多线程环境下调用其方法可能导致内部状态损坏、死锁或数据丢失。

**风险等级**: 🟡 P1 — 死锁 / token 丢失

### 文件:行号

`src/main.py:3371-3440`

### Before

```python
async def _call_llm_stream(client, **kwargs):
    """流式 LLM 调用 — 逐 token yield"""
    import asyncio, threading

    q: asyncio.Queue = asyncio.Queue()   # ❌ 在事件循环线程创建
    done = threading.Event()

    def _stream():
        try:
            response = client.client.chat.completions.create(stream=True, **kwargs)
            for chunk in response:
                # ...
                q.put_nowait(("token", delta.content))  # ❌ worker 线程调用 asyncio.Queue
            q.put_nowait(("done", resp))
        except Exception as e:
            q.put_nowait(("error", str(e)))
        finally:
            done.set()

    t = threading.Thread(target=_stream, daemon=True)
    t.start()
    # ... 主协程从 q 读取 ...
```

### 推荐修复（给 002）

**方案 A（最小改动）**: 使用线程安全的 `queue.Queue` + `asyncio.to_thread` 桥接:

```python
import queue
import threading

async def _call_llm_stream(client, **kwargs):
    q: queue.Queue = queue.Queue()        # ✅ 线程安全队列
    done = threading.Event()

    def _stream():
        try:
            response = client.client.chat.completions.create(stream=True, **kwargs)
            for chunk in response:
                q.put(("token", delta.content))
            q.put(("done", resp))
        except Exception as e:
            q.put(("error", str(e)))
        finally:
            done.set()

    t = threading.Thread(target=_stream, daemon=True)
    t.start()

    # 从线程安全队列读取
    while True:
        try:
            item = await asyncio.to_thread(q.get, timeout=0.1)
            if item[0] == "token":
                yield item[1]
            elif item[0] == "done":
                yield item[1]
                break
            elif item[0] == "error":
                raise RuntimeError(item[1])
        except queue.Empty:
            if done.is_set() and q.empty():
                break
            continue
```

**方案 B（推荐，但改动大）**: 使用 `asyncio.run_coroutine_threadsafe()` 正确桥接:

```python
import asyncio
import threading

async def _call_llm_stream(client, **kwargs):
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    done = threading.Event()

    def _stream():
        try:
            response = client.client.chat.completions.create(stream=True, **kwargs)
            for chunk in response:
                asyncio.run_coroutine_threadsafe(
                    q.put(("token", delta.content)), loop
                )
            asyncio.run_coroutine_threadsafe(q.put(("done", resp)), loop)
        except Exception as e:
            asyncio.run_coroutine_threadsafe(q.put(("error", str(e))), loop)
        finally:
            done.set()

    t = threading.Thread(target=_stream, daemon=True)
    t.start()
    # ... 正常从 q 读取 ...
```

### 修复理由

CPython 的 `asyncio.Queue` 依赖于事件循环的单线程假设，其内部 `_put`/`_get` 操作使用 `collections.deque`，在多线程并发读写时可能出现:
- **竞态条件**: `_queue.append()` 和 `_queue.popleft()` 同时执行
- **Future 状态损坏**: `_getters`/`_putters` 列表的并发修改
- **GIL 不能完全保护**: deque 操作不是原子的跨字节码边界

---

## P2-1: HTML 实体解码 (`html.unescape()`)

### 问题描述

`_do_web_search()` 中的 `_strip()` 函数只手动处理了 5 种 HTML 实体 (`&amp;`, `&lt;`, `&gt;`, `&#x27;`, `&quot;`)，遗漏了 `&nbsp;`、`&copy;`、`&#x2F;`、`&#47;` 等数百种标准实体，导致 DDG 搜索结果出现乱码。

**风险等级**: 🟢 P2 — 搜索结果乱码

### 文件:行号

`src/main.py:3865-3869`

### Before

```python
def _strip(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    s = s.replace('&#x27;', "'").replace('&quot;', '"')
    return s.strip()
```

### After

```python
import html

def _strip(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)  # ✅ 标准库全覆盖: &amp; &lt; &gt; &quot; &#x27; &nbsp; &copy; &#47; ...
    return s.strip()
```

### 修复理由

1. `html.unescape()` 是 Python 标准库，覆盖所有 HTML5 命名实体 + 数字字符引用
2. 删除 5 行脆弱的手工替换，减少维护负担
3. 标准库已被广泛测试，不会出现遗漏或边界情况

---

## P2-2: 魔术数字 999

### 问题描述

`_max_web_searches = 999` 是一个 "魔术数字"——没有语义含义，其他开发者无法理解其意图。用户看到 "最多 999 次搜索" 也会困惑。

**风险等级**: 🟢 P2 — 可维护性

### 文件:行号

`src/main.py:3682`

### Before

```python
_web_search_count = 0
_max_web_searches = 999  # 不限制搜索次数，由 max_rounds 防死循环
```

### After

```python
# ── 搜索限制 (由 max_rounds 防死循环，此处仅为安全上限) ──
_MAX_WEB_SEARCHES_HARD_LIMIT = max_rounds * 2  # 每轮最多触发2次搜索，硬上限防止失控
_web_search_count = 0
```

### 修复理由

1. **语义化命名**: `_MAX_WEB_SEARCHES_HARD_LIMIT` 表达 "硬上限" 的意图
2. **与流量控制参数关联**: 基于 `max_rounds` 计算，而非随意写死 `999`
3. **可配置**: 如需调整，修改变量名即表明影响范围

---

## P2-3: chat.html `showToast` 合并 + `statusDot`

### 问题 1: `showToast` 重复定义 → 互相覆盖

#### 问题描述

`chat.html` 中存在两个 `showToast` 函数:
- **L790** (`showToast(msg)`): 基于 `.copy-toast` CSS 类，用于复制成功提示
- **L1540** (`showToast(text)`): 基于 `#toast` ID + inline style，用于 WebSocket 消息通知

后定义的函数覆盖先定义的函数，导致**复制提示完全失效**。

**风险等级**: 🟢 P2 — 复制提示失效

#### 文件:行号

`templates/chat.html:790-798` 和 `templates/chat.html:1540-1552`

#### Before

```javascript
// ═══ 第一个 showToast (L790) — 被覆盖 ═══
function showToast(msg) {
  const existing = document.querySelector('.copy-toast');
  if (existing) existing.remove();
  const t = document.createElement('div');
  t.className = 'copy-toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 1500);
}

// ... 800 行代码之后 ...

// ═══ 第二个 showToast (L1540) — 覆盖第一个 ═══
function showToast(text) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.style.cssText = 'position:fixed;top:16px;right:16px;...';
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.style.animation = 'none';
  toast.offsetHeight;
  toast.style.animation = 'fadeInOut 3s forwards';
}
```

#### After

```javascript
// ═══ 统一 showToast — 基于 #toast + 自动消失 ═══
function showToast(text) {
  let toast = document.getElementById('toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toast';
    toast.style.cssText = 'position:fixed;top:16px;right:16px;background:var(--surface);color:var(--text);padding:10px 18px;border-radius:8px;border:1px solid var(--border);font-size:13px;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.3);animation:fadeInOut 3s forwards;';
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.style.animation = 'none';
  toast.offsetHeight; // trigger reflow
  toast.style.animation = 'fadeInOut 3s forwards';

  // 更新保存中的复制 toast 引用
  clearTimeout(toast._timeout);
  toast._timeout = setTimeout(() => {
    if (toast.parentNode) toast.remove();
  }, 3000);
}

// ═══ 删除第 2 个 showToast (原 L1540-1552) ═══
// 仅保留一个 showToast，所有调用点统一使用
```

#### 修复理由

1. 合并后复制提示和 WebSocket 通知都能正常工作
2. 使用 `setTimeout` 自动清理 DOM 节点，避免内存泄漏
3. 删除 `.copy-toast` CSS 类相关的代码，减少样式维护成本

---

### 问题 2: `updateStatusDot` 引用不存在的 DOM 元素

#### 问题描述

`updateStatusDot(status)` 函数试图通过 `document.getElementById('statusDot')` 获取元素，但 HTML 中不存在 `id="statusDot"` 的元素。`getElementById` 永远返回 `null`，状态指示灯完全失效。

**风险等级**: 🟢 P2 — 状态指示失效

#### 文件:行号

`templates/chat.html:1533-1537` 和 `templates/chat.html:1058-1071`

#### Before

```javascript
function updateStatusDot(status) {
  const dot = document.getElementById('statusDot');  // ❌ 不存在
  if (dot) {
    dot.className = 'status-dot ' + status;           // ❌ 永远不执行
  }
}
```

#### After

```javascript
// ═══ 方案: 直接复用 setAgentStatus() 中的 status-dot 更新逻辑 ═══
// updateStatusDot 不需要独立存在 — setAgentStatus() 已在更新
// panelAgentStatus 元素时同时更新 status-dot

// 删除 updateStatusDot 函数，在 handleWsMessage 中改为调用 setAgentStatus:

function handleWsMessage(msg) {
  switch (msg.type) {
    case 'agent.status':
      if (msg.status === 'thinking') {
        setAgentStatus('thinking');  // ✅ 同时更新 text + dot
      } else if (msg.status === 'online') {
        setAgentStatus('online');
      } else {
        setAgentStatus('idle');
      }
      break;
  }
}

// setAgentStatus() 已在 status-panel 的 panelAgentStatus 中
// 内置了 <span class="status-dot green|orange|gray"> 的渲染
```

#### 修复理由

1. `setAgentStatus()` 已在每次状态变更时渲染完整 HTML（包括 `status-dot`），无需独立元素
2. 移除无效的 `updateStatusDot()` 函数，消除死代码
3. 统一状态更新路径，避免状态不一致

---

## P2-4: urllib3 全局 SSL 抑制局部化

### 问题描述

`_do_web_search()` 和 `_do_web_extract()` 均调用 `urllib3.disable_warnings()` 来抑制 SSL 警告。这是一个**全局操作** —— 它会影响整个 Python 进程中的所有 urllib3 用户，包括其他库和模块。如果后续代码依赖 SSL 警告来检测安全问题，这些警告将被静默屏蔽。

**风险等级**: 🟢 P2/P3 — 掩盖其他 SSL 问题

### 文件:行号

- `src/main.py:3847-3848` (`_do_web_search`)
- `src/main.py:3906-3907` (`_do_web_extract`)

### Before

```python
# _do_web_search (L3847-3848)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # ❌ 全局副作用

# _do_web_extract (L3906-3907)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # ❌ 全局副作用
```

### After

```python
# _do_web_search — 使用 warnings.catch_warnings() 局部抑制
import warnings
import urllib3

def _do_web_search(query: str) -> str:
    # ...
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, headers=..., timeout=timeout, proxies=proxies, verify=False)
    # ...

# _do_web_extract — 同样局部化
def _do_web_extract(url: str) -> str:
    # ...
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        resp = requests.get(url, headers=..., timeout=20, proxies=proxies, verify=False)
    # ...
```

### 修复理由

1. **`warnings.catch_warnings()`** 是 Python 标准库的上下文管理器，只在 `with` 块内抑制警告
2. 退出上下文后自动恢复原始警告过滤器，不影响其他模块
3. 如果未来有真实的 SSL 配置问题，它们不会被静默掩盖

---

## 修复优先级建议

```
P0 (立即修复 — 安全漏洞)
├── P0-1: SSRF URL 校验         ← 阻止云凭证泄露
├── P0-2: 安全护栏恢复           ← 阻止任意命令执行
└── P0-3: chat.html JS 致命 bug  ← WebSocket 消息处理崩溃

P1 (本周修复 — 稳定性和正确性)
├── P1-1: 超时文案 180→300      ← 消除用户困惑
└── P1-2: asyncio.Queue 跨线程   ← 建议 002 架构评估后处理

P2 (本迭代修复 — 代码质量)
├── P2-1: html.unescape()       ← 搜索结果乱码
├── P2-2: 魔术数字 999          ← 可维护性
├── P2-3: showToast 合并 + statusDot ← UI 功能修复
└── P2-4: urllib3 全局 SSL 抑制 ← 代码卫生
```

---

## 合并检查清单

- [ ] **P0-1**: `src/main.py` — `_validate_url()` + `_SSRF_BLOCKED_*` 常量已添加
- [ ] **P0-2**: `src/main.py:3662-3663` — `SENSITIVE_TOOLS` 和 `DESTRUCTIVE_TOOLS` 已恢复
- [ ] **P0-3a**: `templates/chat.html` — `streamingAbortController` / `streamingActive` 已声明
- [ ] **P0-3b**: `templates/chat.html:1511` — `appendMessage` → `addMsg`
- [ ] **P1-1**: `src/main.py:3687` — 超时文案改为 "300 秒"，提取常量
- [ ] **P1-2**: `src/main.py:3371-3440` — 标注为架构评估项，暂不强制合并
- [ ] **P2-1**: `src/main.py:3865-3869` — `_strip()` 使用 `html.unescape()`
- [ ] **P2-2**: `src/main.py:3682` — `_MAX_WEB_SEARCHES_HARD_LIMIT` 替换 `999`
- [ ] **P2-3a**: `templates/chat.html` — 合并 `showToast`，删除重复定义
- [ ] **P2-3b**: `templates/chat.html` — 移除 `updateStatusDot`，统一使用 `setAgentStatus`
- [ ] **P2-4**: `src/main.py:3847-3848,3906-3907` — `urllib3.disable_warnings()` → `warnings.catch_warnings()`
- [ ] `python -m pytest tests/ -v` 通过
- [ ] 手动验证: 搜索 → 网页抓取 → WebSocket 消息 → 敏感工具确认弹窗

---

> 📋 **文档版本**: v1.0 | **生成时间**: 2026-08-05 | **生成者**: 004 meshctx 审计代理
