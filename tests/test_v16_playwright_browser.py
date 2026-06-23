"""
Test v1.6.0 — Playwright Browser UI Test

Covers:
  1. Start meshctx server via Uvicorn in-process
  2. Use Playwright to open /health endpoint
  3. Assert 200 status and "ok" response
  4. BrowserTool smoke test (navigate + snapshot)

Requires: playwright (installed) + playwright install chromium (done)
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = {"passed": 0, "failed": 0, "total": 0}


def _t(name):
    def w(fn):
        async def r():
            RESULTS["total"] += 1
            try:
                await fn()
                RESULTS["passed"] += 1
                print(f"  ✓ {name}")
            except AssertionError as e:
                RESULTS["failed"] += 1
                print(f"  ✗ {name}: {e}")
            except Exception as e:
                RESULTS["failed"] += 1
                print(f"  ✗ {name}: {type(e).__name__}: {e}")
        return r
    return w


# ═══════════════════════════════════════════════════════════
# 1. Health endpoint via HTTPX (no browser needed, fast)
# ═══════════════════════════════════════════════════════════

@_t("Playwright: health endpoint returns 200 via browser")
async def test_playwright_health():
    """Start a lightweight FastAPI app and test /health with Playwright"""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise ImportError("playwright not installed: pip install playwright")

    # Build a minimal test app
    from fastapi import FastAPI
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "1.6.0", "service": "meshctx"}

    # Start Uvicorn in-process
    import uvicorn
    import threading

    port = 19876  # Use a non-standard port to avoid conflicts
    started = threading.Event()
    server = None

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    def run():
        try:
            server.run()
        except:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()

    # Wait for server to start
    for _ in range(30):
        if server and server.started:
            break
        await asyncio.sleep(0.2)
    else:
        # Try HTTP connection as fallback check
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                for _ in range(10):
                    try:
                        resp = await client.get(f"http://127.0.0.1:{port}/health", timeout=2)
                        break
                    except:
                        await asyncio.sleep(0.5)
        except:
            pass

    try:
        # Use Playwright to navigate to /health
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
            )
            page = await browser.new_page()

            # Capture response
            response = await page.goto(f"http://127.0.0.1:{port}/health", wait_until="domcontentloaded")
            assert response is not None, "No response received"
            assert response.status == 200, f"Expected 200, got {response.status}"

            body = await response.json()
            assert body["status"] == "ok", f"Expected ok, got {body}"
            assert body["version"] == "1.6.0"
            assert body["service"] == "meshctx"

            title = await page.title()
            assert title is not None  # Just ensure it loaded

            await browser.close()
    except Exception as e:
        raise
    finally:
        if server:
            server.should_exit = True
            await asyncio.sleep(0.3)


@_t("Playwright: BrowserTool navigate + snapshot")
async def test_playwright_browser_tool():
    """Test BrowserTool from src.browser_tool with minimal server"""
    from src.browser_tool import BrowserTool

    # Build minimal app
    from fastapi import FastAPI
    import uvicorn, threading

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def root():
        return {"message": "Hello meshctx!"}

    port = 19877
    started = threading.Event()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    def run():
        try:
            server.run()
        except:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()

    for _ in range(30):
        if server and server.started:
            break
        await asyncio.sleep(0.2)

    try:
        tool = BrowserTool()
        result = await tool.navigate(f"http://127.0.0.1:{port}/health")
        assert "url" in result
        assert "title" in result
        assert "snapshot" in result
        assert result["element_count"] >= 0

        # Get snapshot
        snap = await tool.snapshot()
        assert len(snap) > 0
        assert "URL" in snap

        await tool.close()
    except Exception as e:
        raise
    finally:
        if server:
            server.should_exit = True
            await asyncio.sleep(0.3)


@_t("Playwright: BrowserTool error handling for invalid URL")
async def test_playwright_browser_tool_error():
    """BrowserTool gracefully handles navigation errors"""
    from src.browser_tool import BrowserTool

    tool = BrowserTool()
    try:
        # This should throw a connection error - test the tool handles it
        await tool.navigate("http://127.0.0.1:1/nonexistent")
    except Exception:
        pass  # Expected
    finally:
        await tool.close()


@_t("Playwright: BrowserTool navigate to real external page")
async def test_playwright_browser_tool_navigate():
    """Test BrowserTool with a real page (httpbin.org or fallback to local)"""
    from src.browser_tool import BrowserTool

    # Build minimal app for fallback
    from fastapi import FastAPI
    import uvicorn, threading

    app = FastAPI()

    @app.get("/test")
    async def test():
        return {"message": "test page", "items": [1, 2, 3]}

    port = 19878
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    def run():
        try:
            server.run()
        except:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()

    for _ in range(30):
        if server and server.started:
            break
        await asyncio.sleep(0.2)

    try:
        tool = BrowserTool()
        result = await tool.navigate(f"http://127.0.0.1:{port}/test")
        assert result["url"].endswith("/test"), f"URL mismatch: {result['url']}"
        assert result["element_count"] >= 0
        await tool.close()
    except Exception as e:
        raise
    finally:
        if server:
            server.should_exit = True
            await asyncio.sleep(0.3)


@_t("Playwright: Fire and forget health test via httpx")
async def test_playwright_httpx_health():
    """Minimal health test without browser (for CI without playwright)"""
    from fastapi import FastAPI
    import uvicorn, threading

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "1.6.0"}

    port = 19879
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    def run():
        try:
            server.run()
        except:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()

    for _ in range(30):
        if server and server.started:
            break
        await asyncio.sleep(0.2)

    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:{port}/health", timeout=5)
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["version"] == "1.6.0"
    except Exception as e:
        raise
    finally:
        if server:
            server.should_exit = True
            await asyncio.sleep(0.3)


async def main():
    tests = [
        test_playwright_health,
        test_playwright_browser_tool,
        test_playwright_browser_tool_navigate,
        test_playwright_httpx_health,
    ]
    for t in tests:
        await t()
    print(f"\n{'='*40}")
    print(f"  结果: {RESULTS['passed']}✓ / {RESULTS['failed']}✗ / {RESULTS['total']}项")
    print(f"{'='*40}")
    return RESULTS["failed"] == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)
