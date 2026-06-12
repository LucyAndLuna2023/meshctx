"""
meshctx Desktop Tool — Screenshot & Input Control
==================================================
Cross-platform desktop automation: screenshot capture, mouse/keyboard
control. Graceful degradation when optional dependencies are missing.

Install optional deps:  pip install pyautogui pillow

Works on Linux, macOS, and Windows.
"""
import os
import sys
import base64
import subprocess
import tempfile
import platform
from pathlib import Path
from typing import Optional, Tuple

# ══════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════

_OS = platform.system()  # 'Linux', 'Darwin', 'Windows'

_PYAUTOGUI_AVAILABLE = False
try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
    # Safety: fail-safe so mouse doesn't get stuck at a corner
    pyautogui.FAILSAFE = True
except ImportError:
    pass

_PILLOW_AVAILABLE = False
try:
    from PIL import Image, ImageGrab
    _PILLOW_AVAILABLE = True
except ImportError:
    pass

_MSS_AVAILABLE = False
try:
    import mss
    _MSS_AVAILABLE = True
except ImportError:
    pass


def _ensure_pyautogui(operation: str):
    """Raise a helpful error if pyautogui is not installed."""
    if not _PYAUTOGUI_AVAILABLE:
        raise RuntimeError(
            f"desktop_{operation} requires pyautogui. "
            "Install it: pip install pyautogui"
        )


def _ensure_pillow(operation: str):
    """Raise a helpful error if Pillow is not installed."""
    if not _PILLOW_AVAILABLE:
        raise RuntimeError(
            f"desktop_{operation} requires Pillow (PIL). "
            "Install it: pip install pillow"
        )


def _take_screenshot_pillow() -> bytes:
    """Take screenshot using Pillow ImageGrab (cross-platform)."""
    img = ImageGrab.grab(all_screens=True)
    fd, buf = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        img.save(buf, format="PNG")
        with open(buf, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(buf)
        except OSError:
            pass


def _take_screenshot_mss() -> bytes:
    """Take screenshot using mss (fast, cross-platform)."""
    with mss.mss() as sct:
        monitor = sct.monitors[0]  # all monitors combined
        raw = sct.grab(monitor)
        return mss.tools.to_png(raw.rgb, raw.size)


def _take_screenshot_linux() -> bytes:
    """Take screenshot on Linux using built-in tools."""
    # Prefer import (ImageMagick), then scrot, then xfce4-screenshooter
    for cmd in [["import", "-window", "root", "png:-"],
                ["scrot", "-z", "-o", "-"],
                ["gnome-screenshot", "-f", "-"],
                ["xfce4-screenshooter", "-f", "-"]]:
        try:
            r = subprocess.run(
                cmd, capture_output=True, timeout=15,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            )
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    raise RuntimeError(
        "No screenshot tool found on Linux. Install one of:\n"
        "  sudo apt install scrot imagemagick gnome-screenshot\n"
        "Or install Pillow: pip install pillow"
    )


def _take_screenshot_mac() -> bytes:
    """Take screenshot on macOS using screencapture."""
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        r = subprocess.run(
            ["screencapture", "-x", tmp],
            capture_output=True, timeout=15
        )
        if r.returncode != 0:
            raise RuntimeError(f"screencapture failed: {r.stderr.decode()}")
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _take_screenshot_windows() -> bytes:
    """Take screenshot on Windows using win32 API."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # Get screen dimensions
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)

    # Device contexts
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    gdi32.SelectObject(hdc_mem, hbmp)

    # Copy screen to bitmap
    gdi32.BitBlt(
        hdc_mem, 0, 0, width, height,
        hdc_screen, 0, 0,
        0x00CC0020  # SRCCOPY
    )

    # Get bitmap bits
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = width
    bi.biHeight = -height  # top-down
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0  # BI_RGB

    buf_len = width * height * 4
    buf = (ctypes.c_ubyte * buf_len)()
    gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buf, ctypes.byref(bi), 0)

    # Build PNG from raw BGRA pixels using standard library
    # Minimal PNG encoder (no compression library needed)
    import struct
    import zlib

    def _make_png(raw_bgra: bytes, w: int, h: int) -> bytes:
        """Encode raw BGRA pixels as a PNG byte string (minimal valid PNG)."""
        # Process rows: BGRA -> RGBA, and flip vertical
        row_size = w * 4
        scanlines = []
        for y in range(h - 1, -1, -1):
            row = list(raw_bgra[y * row_size: (y + 1) * row_size])
            # BGRA -> RGBA: swap B and R
            for x in range(w):
                b, g, r, a = row[x * 4:x * 4 + 4]
                row[x * 4:x * 4 + 4] = [r, g, b, a]
            scanlines.append(bytes([0]) + bytes(row))  # filter byte 0

        raw_data = b"".join(scanlines)

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            chunk = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + chunk + crc

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
        ihdr = _chunk(b"IHDR", ihdr_data)
        idat = _chunk(b"IDAT", zlib.compress(raw_data))
        iend = _chunk(b"IEND", b"")
        return sig + ihdr + idat + iend

    png_bytes = _make_png(bytes(buf), width, height)

    # Cleanup
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)

    return png_bytes


# ══════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════

def desktop_screenshot(save_path: str = None) -> dict:
    """Take a screenshot of the entire desktop.

    Args:
        save_path: Optional file path to save the PNG. If None, returns
                   the image as base64-encoded PNG in the result dict.

    Returns:
        dict with keys:
            ok (bool): True on success
            format (str): 'png'
            base64 (str): base64-encoded PNG (if save_path is None)
            path (str): where the file was saved (if save_path given)
            error (str): error message (if any)
            hint (str): installation hint if deps are missing
    """
    png_bytes = None

    # Tier 1: Pillow (cross-platform, easiest)
    if _PILLOW_AVAILABLE:
        try:
            png_bytes = _take_screenshot_pillow()
        except Exception as e:
            return {"ok": False, "error": f"Pillow screenshot failed: {e}"}

    # Tier 2: mss (fast, cross-platform)
    if png_bytes is None and _MSS_AVAILABLE:
        try:
            png_bytes = _take_screenshot_mss()
        except Exception as e:
            return {"ok": False, "error": f"mss screenshot failed: {e}"}

    # Tier 3: pyautogui (cross-platform but requires both pyautogui + pillow)
    if png_bytes is None and _PYAUTOGUI_AVAILABLE:
        try:
            img = pyautogui.screenshot()
            fd, buf = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                img.save(buf, format="PNG")
                with open(buf, "rb") as f:
                    png_bytes = f.read()
            finally:
                try:
                    os.unlink(buf)
                except OSError:
                    pass
        except Exception as e:
            return {"ok": False, "error": f"pyautogui screenshot failed: {e}"}

    # Tier 4: OS-specific native fallback
    if png_bytes is None:
        try:
            if _OS == "Linux":
                png_bytes = _take_screenshot_linux()
            elif _OS == "Darwin":
                png_bytes = _take_screenshot_mac()
            elif _OS == "Windows":
                png_bytes = _take_screenshot_windows()
            else:
                return {
                    "ok": False,
                    "error": f"Unsupported platform: {_OS}",
                    "hint": "Install Pillow: pip install pillow"
                }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "hint": "Install Pillow and pyautogui: pip install pillow pyautogui"
            }

    if png_bytes is None:
        return {
            "ok": False,
            "error": "All screenshot methods failed.",
            "hint": "Install Pillow: pip install pillow"
        }

    # Save or encode
    if save_path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(save_path)) or ".", exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(png_bytes)
            return {"ok": True, "format": "png", "path": os.path.abspath(save_path)}
        except OSError as e:
            return {"ok": False, "error": f"Failed to save screenshot: {e}"}
    else:
        b64 = base64.b64encode(png_bytes).decode("ascii")
        return {"ok": True, "format": "png", "base64": b64}


def desktop_click(x: int, y: int, button: str = "left") -> dict:
    """Click at the given screen coordinates.

    Args:
        x: X coordinate (pixels)
        y: Y coordinate (pixels)
        button: Mouse button — 'left', 'right', or 'middle' (default 'left')

    Returns:
        dict with ok and optional error/hint.
    """
    _ensure_pyautogui("click")
    try:
        pyautogui.click(x, y, button=button)
        return {"ok": True, "x": x, "y": y, "button": button}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def desktop_type(text: str) -> dict:
    """Type the given text as keyboard input.

    Args:
        text: String to type. Supports newlines as Enter key presses.

    Returns:
        dict with ok and optional error/hint.
    """
    _ensure_pyautogui("type")
    try:
        pyautogui.typewrite(text)
        return {"ok": True, "length": len(text)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def desktop_press(key: str) -> dict:
    """Press a single key or key combination.

    Args:
        key: Key name (e.g. 'enter', 'escape', 'ctrl+c', 'alt+tab').
             See pyautogui docs for full key name list.

    Returns:
        dict with ok and optional error/hint.
    """
    _ensure_pyautogui("press")
    try:
        pyautogui.hotkey(*key.split("+"))
        return {"ok": True, "key": key}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def desktop_move(x: int, y: int) -> dict:
    """Move the mouse cursor to the given screen coordinates.

    Args:
        x: X coordinate (pixels)
        y: Y coordinate (pixels)

    Returns:
        dict with ok and optional error/hint.
    """
    _ensure_pyautogui("move")
    try:
        pyautogui.moveTo(x, y)
        return {"ok": True, "x": x, "y": y}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def desktop_scroll(amount: int) -> dict:
    """Scroll the mouse wheel.

    Args:
        amount: Number of scroll clicks. Positive = scroll up,
                negative = scroll down.

    Returns:
        dict with ok and optional error/hint.
    """
    _ensure_pyautogui("scroll")
    try:
        pyautogui.scroll(amount)
        return {"ok": True, "amount": amount}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def desktop_size() -> dict:
    """Get the screen dimensions.

    Returns:
        dict with:
            ok (bool)
            width (int): screen width in pixels
            height (int): screen height in pixels
            error (str): if measurement failed
            hint (str): installation hint if deps missing
    """
    # Tier 1: pyautogui
    if _PYAUTOGUI_AVAILABLE:
        try:
            w, h = pyautogui.size()
            return {"ok": True, "width": w, "height": h}
        except Exception as e:
            pass  # fall through

    # Tier 2: tkinter (built-in, cross-platform)
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        w = root.winfo_screenwidth()
        h = root.winfo_screenheight()
        root.destroy()
        if w and h:
            return {"ok": True, "width": w, "height": h}
    except Exception:
        pass

    # Tier 3: OS-specific
    try:
        if _OS == "Windows":
            import ctypes
            w = ctypes.windll.user32.GetSystemMetrics(0)
            h = ctypes.windll.user32.GetSystemMetrics(1)
            return {"ok": True, "width": w, "height": h}
        elif _OS == "Linux":
            r = subprocess.run(
                ["xrandr", "--current"],
                capture_output=True, text=True, timeout=5,
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    if " connected " in line and "primary" in line:
                        # e.g.: "HDMI-0 connected primary 1920x1080+0+0"
                        parts = line.split()
                        for part in parts:
                            if "x" in part and "+" in part:
                                geom = part.split("+")[0]
                                w_s, h_s = geom.split("x")
                                return {"ok": True, "width": int(w_s), "height": int(h_s)}
                # Try any connected line
                for line in r.stdout.splitlines():
                    if " connected " in line:
                        parts = line.split()
                        for part in parts:
                            if "x" in part and "+" in part:
                                geom = part.split("+")[0]
                                w_s, h_s = geom.split("x")
                                return {"ok": True, "width": int(w_s), "height": int(h_s)}
        elif _OS == "Darwin":
            r = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True, timeout=10
            )
            if r.returncode == 0:
                for line in r.stdout.splitlines():
                    line_stripped = line.strip()
                    if line_stripped.startswith("Resolution:"):
                        # e.g.: "Resolution: 2560 x 1600 Retina"
                        res = line_stripped.split(":")[1].strip()
                        nums = res.split("x")
                        if len(nums) >= 2:
                            w_s = nums[0].strip()
                            h_s = nums[1].split()[0].strip()  # drop "Retina" etc
                            return {"ok": True, "width": int(w_s), "height": int(h_s)}
    except Exception:
        pass

    # Nothing worked
    return {
        "ok": False,
        "error": "Could not determine screen size.",
        "hint": "Install pyautogui: pip install pyautogui"
    }
