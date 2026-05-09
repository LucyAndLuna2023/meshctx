"""
meshctx TTS 语音合成 — 多Provider统一接口

支持:
    bailian  — 阿里百炼 CosyVoice (免费额度)
    openai   — OpenAI TTS
    edge     — Microsoft Edge TTS (免费, 无限制)
    local    — 本地 pyttsx3 (离线)
"""
import asyncio
import base64
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

try:
    from .kernel import Event, EventPriority, Plugin, PluginInfo
except ImportError:
    from src.core.kernel import Event, EventPriority, Plugin, PluginInfo

logger = logging.getLogger("meshctx.tts")


class TTSEngine:
    """多Provider TTS引擎"""
    
    def __init__(self, provider: str = "edge"):
        self.provider = provider
        
    async def synthesize(self, text: str, voice: str = None, 
                         speed: float = 1.0, output_path: str = None) -> str:
        """
        合成语音, 返回音频文件路径
        
        Args:
            text: 要合成的文本
            voice: 音色 (默认根据provider)
            speed: 语速 (0.5-2.0)
            output_path: 输出路径 (默认临时文件)
        """
        if self.provider == "edge":
            return await self._edge_tts(text, voice or "zh-CN-XiaoxiaoNeural", speed, output_path)
        elif self.provider == "openai":
            return await self._openai_tts(text, voice or "alloy", speed, output_path)
        elif self.provider == "bailian":
            return await self._bailian_tts(text, voice or "longxiaochun", output_path)
        elif self.provider == "local":
            return self._local_tts(text, output_path)
        else:
            raise ValueError(f"不支持的 TTS provider: {self.provider}")
    
    async def _edge_tts(self, text: str, voice: str, speed: float, 
                        output: str = None) -> str:
        """Microsoft Edge TTS — 免费, 高质量, 无限制"""
        output = output or self._temp_path("edge", text)
        
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice, rate=f"{int((speed-1)*100):+d}%")
            await communicate.save(output)
            return output
        except ImportError:
            # 回退: 使用 REST API
            return await self._edge_tts_rest(text, voice, output)
    
    async def _edge_tts_rest(self, text: str, voice: str, output: str) -> str:
        """Edge TTS REST API 回退"""
        import httpx
        
        # 构建 SSML
        ssml = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">
            <voice name="{voice}">{text}</voice>
        </speak>"""
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1",
                params={"TrustedClientToken": "6A5AA1D9EAFF4E9FB37E23D68491D6F4"},
                headers={
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
                    "User-Agent": "Mozilla/5.0",
                },
                content=ssml.encode("utf-8"),
                timeout=30,
            )
            if resp.status_code == 200:
                with open(output, "wb") as f:
                    f.write(resp.content)
                return output
        
        raise Exception(f"Edge TTS 失败: {resp.status_code}")
    
    async def _openai_tts(self, text: str, voice: str, speed: float,
                          output: str = None) -> str:
        """OpenAI TTS"""
        from openai import AsyncOpenAI
        
        output = output or self._temp_path("openai", text)
        client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        
        resp = await client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            speed=speed,
        )
        resp.stream_to_file(output)
        return output
    
    async def _bailian_tts(self, text: str, voice: str,
                           output: str = None) -> str:
        """阿里百炼 CosyVoice TTS"""
        import httpx
        
        output = output or self._temp_path("bailian", text)
        api_key = os.environ.get("BAILIAN_API_KEY", "")
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-to-speech/synthesis",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "cosyvoice-v1",
                    "input": {"text": text},
                    "parameters": {"voice": voice, "format": "mp3"},
                },
                timeout=30,
            )
            data = resp.json()
            if data.get("output", {}).get("audio"):
                audio_bytes = base64.b64decode(data["output"]["audio"])
                with open(output, "wb") as f:
                    f.write(audio_bytes)
                return output
        
        raise Exception("百炼 TTS 失败")
    
    def _local_tts(self, text: str, output: str = None) -> str:
        """本地离线 TTS (pyttsx3)"""
        output = output or self._temp_path("local", text)
        
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(text, output)
            engine.runAndWait()
            return output
        except ImportError:
            raise ImportError("pip install pyttsx3")
    
    def _temp_path(self, provider: str, text: str) -> str:
        """生成临时音频文件路径"""
        h = hashlib.md5(text.encode()).hexdigest()[:8]
        path = Path(tempfile.gettempdir()) / f"meshctx_tts_{provider}_{h}.mp3"
        return str(path)


class TTSPlugin(Plugin):
    """TTS 语音合成插件"""
    
    info = PluginInfo(
        name="tts",
        version="1.0.0",
        description="多Provider TTS: Edge(免费)/OpenAI/百炼/本地",
        author="meshctx",
    )
    
    def __init__(self):
        self.engine = TTSEngine()
    
    async def on_load(self):
        self.kernel.bus.subscribe("tts.synthesize", self._on_synthesize, plugin_name="tts")
        logger.info("TTS 已就绪")
    
    async def on_unload(self):
        pass
    
    async def _on_synthesize(self, event: Event):
        data = event.data
        text = data.get("text", "")
        if not text:
            return
        
        try:
            path = await self.engine.synthesize(
                text=text,
                voice=data.get("voice"),
                speed=data.get("speed", 1.0),
                output_path=data.get("output"),
            )
            await self.kernel.bus.publish(Event(
                type="tts.result",
                source="tts",
                correlation_id=event.id,
                data={"audio_path": path, "text": text[:50]},
            ))
        except Exception as e:
            logger.error(f"TTS 失败: {e}")
