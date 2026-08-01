"""
meshctx Browser 工具 — 基于 Playwright 的浏览器自动化

用法:
    meshctx browser open https://example.com
    meshctx browser snap     # 页面快照
    meshctx browser click @e5  # 点击元素
    meshctx browser type @e3 "hello"  # 输入文本
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.browser")

@dataclass
class BrowserState:
    """浏览器状态"""
    url: str = ""
    title: str = ""
    snapshot: str = ""
    element_count: int = 0
    console_errors: List[str] = None
    
    def __post_init__(self):
        if self.console_errors is None:
            self.console_errors = []


class BrowserTool:
    """浏览器工具 — Playwright 封装"""
    
    def __init__(self):
        self._browser = None
        self._page = None
        self._playwright = None
        self.state = BrowserState()
    
    async def _ensure_browser(self):
        """延迟加载浏览器"""
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-gpu'],
            )
            self._page = await self._browser.new_page()
            logger.info("Browser 已启动")
        except ImportError:
            raise ImportError("需要安装: pip install playwright && playwright install chromium")
        except Exception as e:
            logger.error(f"Browser 启动失败: {e}")
            raise
    
    async def navigate(self, url: str) -> Dict:
        """导航到 URL"""
        await self._ensure_browser()
        
        if not url.startswith("http"):
            url = "https://" + url
        
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self.state.url = self._page.url
        self.state.title = await self._page.title()
        
        # 获取可交互元素快照
        await self._update_snapshot()
        
        return {
            "url": self.state.url,
            "title": self.state.title,
            "element_count": self.state.element_count,
            "snapshot": self.state.snapshot[:2000],
        }
    
    async def snapshot(self, full: bool = False) -> str:
        """获取页面快照"""
        await self._ensure_browser()
        await self._update_snapshot()
        
        if full:
            try:
                return await self._page.content()
            except Exception:
                logger.debug("browser_tool error", exc_info=True)
                return self.state.snapshot
        return self.state.snapshot
    
    async def click(self, ref: str) -> Dict:
        """点击元素 (ref 格式: @e5 或 CSS选择器)"""
        await self._ensure_browser()
        
        try:
            if ref.startswith("@e"):
                # data-ref 属性
                await self._page.click(f'[data-ref="{ref}"]', timeout=5000)
            else:
                await self._page.click(ref, timeout=5000)
            
            await self._page.wait_for_timeout(500)
            await self._update_snapshot()
            
            return {"clicked": ref, "url": self.state.url}
        except Exception as e:
            return {"error": str(e), "clicked": ref}
    
    async def type_text(self, ref: str, text: str) -> Dict:
        """在元素中输入文本"""
        await self._ensure_browser()
        
        try:
            if ref.startswith("@e"):
                selector = f'[data-ref="{ref}"]'
            else:
                selector = ref
            
            await self._page.fill(selector, text, timeout=5000)
            await self._update_snapshot()
            
            return {"typed": text, "into": ref}
        except Exception as e:
            return {"error": str(e)}
    
    async def press_key(self, key: str) -> Dict:
        """按键 (Enter, Tab, Escape等)"""
        await self._ensure_browser()
        await self._page.keyboard.press(key)
        await self._page.wait_for_timeout(300)
        await self._update_snapshot()
        return {"key": key}
    
    async def evaluate(self, js: str) -> Any:
        """执行 JavaScript"""
        await self._ensure_browser()
        try:
            result = await self._page.evaluate(js)
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_console(self) -> List[str]:
        """获取控制台输出"""
        await self._ensure_browser()
        return self.state.console_errors
    
    async def screenshot(self, path: str = None) -> bytes:
        """截图"""
        await self._ensure_browser()
        return await self._page.screenshot(path=path, full_page=True)
    
    async def close(self):
        """关闭浏览器"""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._page = None
        logger.info("Browser 已关闭")

    # ── P1: CDP 登录态复用 + Cookie 注入 ──────────────
    async def connect_cdp(self, cdp_url: str = "http://127.0.0.1:9222") -> Dict:
        """连接用户已开的 Chrome (需 --remote-debugging-port=9222)
        复用其登录态/标签页, 免重复登录"""
        if self._browser is not None:
            await self.close()
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
            contexts = self._browser.contexts
            if not contexts:
                return {"error": "CDP 连接成功但无 context", "cdp": cdp_url}
            self._page = contexts[0].pages[0] if contexts[0].pages else await contexts[0].new_page()
            await self._update_snapshot()
            logger.info(f"CDP 已连接: {cdp_url}, 标签数={len(contexts[0].pages)}")
            return {"connected": True, "cdp": cdp_url, "tabs": len(contexts[0].pages),
                    "url": self.state.url}
        except ImportError:
            raise ImportError("需要安装: pip install playwright && playwright install chromium")
        except Exception as e:
            logger.error(f"CDP 连接失败: {e}")
            return {"error": f"CDP 连接失败: {e}. 请用 --remote-debugging-port=9222 启动 Chrome"}

    async def get_cookies(self) -> List[Dict]:
        """获取当前 context 全部 cookie (供 vault 加密保存)"""
        if self._browser is None:
            return []
        try:
            context = self._browser.contexts[0]
            return await context.cookies()
        except Exception as e:
            logger.warning(f"get_cookies 失败: {e}")
            return []

    async def add_cookies(self, cookies: List[Dict]) -> bool:
        """注入 cookie (授权恢复登录态)"""
        if self._browser is None or not cookies:
            return False
        try:
            context = self._browser.contexts[0]
            await context.add_cookies(cookies)
            return True
        except Exception as e:
            logger.warning(f"add_cookies 失败: {e}")
            return False

    # ── P1: 多标签管理 ────────────────────────────────
    async def list_tabs(self) -> Dict:
        """列出当前 context 全部标签页"""
        if self._browser is None:
            return {"tabs": []}
        try:
            pages = self._browser.contexts[0].pages
            tabs = [{"index": i, "url": p.url, "title": await p.title(),
                     "active": p is self._page} for i, p in enumerate(pages)]
            return {"tabs": tabs, "active": self._page.url if self._page else ""}
        except Exception as e:
            return {"error": str(e)}

    async def new_tab(self, url: str = "") -> Dict:
        """新开标签页"""
        await self._ensure_browser()
        try:
            context = self._browser.contexts[0]
            page = await context.new_page()
            if url:
                if not url.startswith("http"):
                    url = "https://" + url
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self._page = page
            await self._update_snapshot()
            return {"new_tab": True, "url": self.state.url}
        except Exception as e:
            return {"error": str(e)}

    async def switch_tab(self, index: int) -> Dict:
        """切换到指定标签页 (0-based)"""
        if self._browser is None:
            return {"error": "浏览器未启动"}
        try:
            pages = self._browser.contexts[0].pages
            if index < 0 or index >= len(pages):
                return {"error": f"标签索引 {index} 超出范围 (共 {len(pages)} 个)"}
            self._page = pages[index]
            self.state.url = self._page.url
            self.state.title = await self._page.title()
            await self._update_snapshot()
            return {"switched": index, "url": self.state.url}
        except Exception as e:
            return {"error": str(e)}

    async def close_tab(self, index: int = -1) -> Dict:
        """关闭标签页 (默认当前)"""
        if self._browser is None:
            return {"error": "浏览器未启动"}
        try:
            pages = self._browser.contexts[0].pages
            if len(pages) <= 1:
                return {"error": "至少保留一个标签页"}
            idx = index if index >= 0 else pages.index(self._page)
            if idx < 0 or idx >= len(pages):
                return {"error": f"标签索引 {idx} 超出范围"}
            await pages[idx].close()
            # 切到剩余第一个
            pages = self._browser.contexts[0].pages
            self._page = pages[0]
            self.state.url = self._page.url
            self.state.title = await self._page.title()
            await self._update_snapshot()
            return {"closed": idx, "remaining": len(pages)}
        except Exception as e:
            return {"error": str(e)}

    # ── P1: frame 支持 (evaluate 可指定 frame) ────────
    async def evaluate_frame(self, js: str, frame_selector: str = "") -> Any:
        """在指定 frame 内执行 JS (frame_selector 空 → 主 frame)"""
        await self._ensure_browser()
        try:
            if frame_selector:
                frame = self._page.frames[0]  # 简单取首个子 frame 兜底
                for f in self._page.frames:
                    if frame_selector in (f.name or "") or frame_selector in (f.url or ""):
                        frame = f
                        break
                result = await frame.evaluate(js)
            else:
                result = await self._page.evaluate(js)
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}
    
    async def _update_snapshot(self):
        """更新页面快照"""
        try:
            # 注入 data-ref 属性到可交互元素
            await self._page.evaluate("""
                document.querySelectorAll('a,button,input,select,textarea,[role="button"]').forEach((el, i) => {
                    el.setAttribute('data-ref', '@e' + (i + 1));
                });
            """)
            
            # 收集交互元素列表
            elements = await self._page.evaluate("""
                Array.from(document.querySelectorAll('[data-ref]')).map(el => ({
                    ref: el.getAttribute('data-ref'),
                    tag: el.tagName.toLowerCase(),
                    text: (el.textContent || '').trim().substring(0, 80),
                    type: el.type || '',
                    href: el.href || '',
                }))
            """)
            
            self.state.element_count = len(elements)
            
            # 生成快照文本
            lines = [f"URL: {self.state.url}", f"Title: {self.state.title}", ""]
            for el in elements[:100]:
                tag_icon = {"a": "🔗", "button": "🔘", "input": "📝", "select": "📋"}.get(el["tag"], "  ")
                lines.append(f"  [{el['ref']}] {tag_icon} {el['text'][:60]}")
            
            self.state.snapshot = "\n".join(lines)
            
        except Exception as e:
            logger.error(f"快照更新失败: {e}")


class BrowserPlugin(Plugin):
    """Browser 工具插件"""
    
    info = PluginInfo(
        name="browser",
        version="1.0.0",
        description="Browser 自动化工具 — 基于 Playwright",
        author="meshctx",
    )
    
    def __init__(self):
        self.tool = BrowserTool()
    
    async def on_load(self):
        self.kernel.bus.subscribe("browser.navigate", self._on_navigate, plugin_name="browser")
        self.kernel.bus.subscribe("browser.snapshot", self._on_snapshot, plugin_name="browser")
        self.kernel.bus.subscribe("browser.click", self._on_click, plugin_name="browser")
        self.kernel.bus.subscribe("browser.type", self._on_type, plugin_name="browser")
        self.kernel.bus.subscribe("browser.evaluate", self._on_evaluate, plugin_name="browser")
    
    async def on_unload(self):
        await self.tool.close()
    
    async def _on_navigate(self, event: Event):
        result = await self.tool.navigate(event.data.get("url", ""))
        await self._reply(event, result)
    
    async def _on_snapshot(self, event: Event):
        result = await self.tool.snapshot(event.data.get("full", False))
        await self._reply(event, {"snapshot": result})
    
    async def _on_click(self, event: Event):
        result = await self.tool.click(event.data.get("ref", ""))
        await self._reply(event, result)
    
    async def _on_type(self, event: Event):
        result = await self.tool.type_text(
            event.data.get("ref", ""), event.data.get("text", "")
        )
        await self._reply(event, result)
    
    async def _on_evaluate(self, event: Event):
        result = await self.tool.evaluate(event.data.get("js", ""))
        await self._reply(event, result)
    
    async def _reply(self, event: Event, data: Any):
        await self.kernel.bus.publish(Event(
            type=f"{event.type}_result",
            source="browser",
            correlation_id=event.id,
            data=data if isinstance(data, dict) else {"result": data},
        ))
