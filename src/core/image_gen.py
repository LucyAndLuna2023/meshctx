import os
import json
import urllib.request
import tempfile
from typing import Dict, List, Optional

# Try openai
try:
    import openai
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


class ImageGenerator:
    """AI图片生成 — DALL-E / Stable Diffusion"""

    SUPPORTED_SIZES = ["1024x1024", "1792x1024", "1024x1792", "512x512", "256x256"]
    SUPPORTED_STYLES = ["vivid", "natural"]

    def __init__(self, provider: str = None):
        self._providers = self._detect_providers()
        self.provider = provider or (self._providers[0] if self._providers else None)

    def _detect_providers(self) -> List[str]:
        providers = []
        if _HAS_OPENAI and os.getenv("OPENAI_API_KEY"):
            providers.append("openai")
        if os.getenv("STABILITY_API_KEY"):
            providers.append("stability")
        if os.getenv("DEEPSEEK_API_KEY"):
            providers.append("deepseek")
        return providers

    def list_providers(self) -> List[str]:
        return self._providers

    def generate(self, prompt: str, size: str = "1024x1024",
                 style: str = None, quality: str = "standard") -> Dict:
        """生成图片，返回 {url, provider, revised_prompt}"""
        if not self._providers:
            return {"error": "没有可用的图片生成Provider，请设置 OPENAI_API_KEY 或 STABILITY_API_KEY"}

        if size not in self.SUPPORTED_SIZES:
            return {"error": f"不支持的尺寸: {size}，支持: {self.SUPPORTED_SIZES}"}

        if not prompt or not prompt.strip():
            return {"error": "prompt不能为空"}

        p = self.provider or self._providers[0]

        try:
            if p == "openai":
                return self._generate_dalle(prompt, size, style, quality)
            elif p == "stability":
                return self._generate_stability(prompt, size)
            else:
                return {"error": f"不支持的provider: {p}"}
        except Exception as e:
            return {"error": str(e)}

    def _generate_dalle(self, prompt, size, style, quality) -> Dict:
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        kwargs = {
            "model": "dall-e-3",
            "prompt": prompt,
            "size": size,
            "quality": quality,
            "n": 1,
        }
        if style:
            kwargs["style"] = style
        resp = client.images.generate(**kwargs)
        data = resp.data[0]
        return {
            "url": data.url,
            "provider": "openai",
            "revised_prompt": getattr(data, "revised_prompt", prompt),
        }

    def _generate_stability(self, prompt, size) -> Dict:
        api_key = os.getenv("STABILITY_API_KEY")
        w, h = size.split("x")
        req = urllib.request.Request(
            "https://api.stability.ai/v2beta/stable-image/generate/core",
            data=json.dumps({"prompt": prompt, "width": int(w), "height": int(h)}).encode(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "image/*",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            import base64
            data = resp.read()
            tmp = os.path.join(tempfile.gettempdir(), f"meshctx_img_{hash(prompt) & 0xFFFF}.png")
            with open(tmp, "wb") as f:
                f.write(data)
            return {
                "url": f"file://{tmp}",
                "provider": "stability",
                "revised_prompt": prompt,
            }

    def validate_size(self, size: str) -> bool:
        return size in self.SUPPORTED_SIZES
