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
            except:
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
