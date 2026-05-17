"""
meshctx v2.19 — 语音I/O模块
TTS (Text-to-Speech): edge-tts (Microsoft Edge TTS, 免费无需API Key)
STT (Speech-to-Text): faster-whisper (本地Whisper推理, GPU加速)

架构: 异步处理 + 文件缓存 + 多语言支持
"""
import asyncio
import io
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("meshctx.voice")

# ── 语音缓存目录 ──
VOICE_CACHE_DIR = Path(os.environ.get("MESHCTX_DATA_DIR", Path.home() / ".meshctx")) / "voice_cache"
VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── TTS状态 ──
_tts_available = False
_stt_available = False
_tts_check_done = False
_stt_check_done = False
_whisper_model = None  # lazy load


async def _check_tts():
    """检查 edge-tts 可用性"""
    global _tts_available, _tts_check_done
    if _tts_check_done:
        return _tts_available
    _tts_check_done = True
    try:
        import edge_tts  # noqa: F401
        _tts_available = True
        logger.info("✅ TTS: edge-tts 可用")
    except ImportError:
        _tts_available = False
        logger.warning("⚠️ TTS: edge-tts 未安装, pip install edge-tts")
    return _tts_available


async def _check_stt():
    """检查 faster-whisper 可用性"""
    global _stt_available, _stt_check_done
    if _stt_check_done:
        return _stt_available
    _stt_check_done = True
    try:
        from faster_whisper import WhisperModel  # noqa: F401
        _stt_available = True
        logger.info("✅ STT: faster-whisper 可用")
    except ImportError:
        _stt_available = False
        logger.warning("⚠️ STT: faster-whisper 未安装, pip install faster-whisper")
    return _stt_available


# ── 支持的语言/声音映射 ──
TTS_VOICES = {
    "zh": "zh-CN-XiaoxiaoNeural",     # 中文女声 (晓晓)
    "zh-male": "zh-CN-YunxiNeural",   # 中文男声 (云希)
    "en": "en-US-JennyNeural",        # 英文女声
    "en-male": "en-US-GuyNeural",     # 英文男声
    "ja": "ja-JP-NanamiNeural",       # 日文女声
    "ko": "ko-KR-SunHiNeural",        # 韩文女声
    "fr": "fr-FR-DeniseNeural",       # 法文女声
    "de": "de-DE-KatjaNeural",        # 德文女声
    "es": "es-ES-ElviraNeural",       # 西班牙文女声
}


async def text_to_speech(
    text: str,
    voice: str = "zh-CN-XiaoxiaoNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
    cache: bool = True,
) -> Optional[bytes]:
    """
    文本转语音 (TTS)
    
    Args:
        text: 要转换的文本
        voice: Edge TTS 声音名称
        rate: 语速 (-50% ~ +50%)
        pitch: 音调
        cache: 是否缓存结果
    
    Returns:
        MP3 音频字节, 或 None
    """
    if not await _check_tts():
        return None
    
    import hashlib
    import edge_tts
    
    # 缓存键
    cache_key = hashlib.md5(f"{text}|{voice}|{rate}|{pitch}".encode()).hexdigest()
    cache_file = VOICE_CACHE_DIR / f"{cache_key}.mp3"
    
    if cache and cache_file.exists():
        logger.debug(f"TTS 缓存命中: {cache_key[:8]}")
        return cache_file.read_bytes()
    
    try:
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )
        
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        
        if not audio_chunks:
            logger.warning("TTS: 无音频数据返回")
            return None
        
        audio_data = b"".join(audio_chunks)
        
        # 缓存
        if cache:
            cache_file.write_bytes(audio_data)
            # 清理旧缓存 (>1000个文件)
            _cleanup_cache()
        
        logger.info(f"TTS: 生成 {len(audio_data)} bytes, 文本长度 {len(text)}")
        return audio_data
        
    except Exception as e:
        logger.error(f"TTS 失败: {e}")
        return None


async def speech_to_text(
    audio_data: bytes,
    language: Optional[str] = None,
    model_size: str = "tiny",
    compute_type: str = "int8",
) -> Optional[str]:
    """
    语音转文本 (STT)
    
    Args:
        audio_data: 音频字节 (支持 mp3/wav/ogg)
        language: 语言代码 (zh/en/ja等), None为自动检测
        model_size: 模型大小 (tiny/base/small/medium/large-v3)
        compute_type: 计算精度 (int8/float16/int8_float16)
    
    Returns:
        识别文本, 或 None
    """
    global _whisper_model
    
    if not await _check_stt():
        return None
    
    try:
        from faster_whisper import WhisperModel
        
        # Lazy load model
        if _whisper_model is None or getattr(_whisper_model, '_model_size', None) != model_size:
            logger.info(f"加载 Whisper 模型: {model_size}...")
            _whisper_model = WhisperModel(
                model_size,
                device="cpu",
                compute_type=compute_type,
            )
            _whisper_model._model_size = model_size
        
        # 写入临时文件
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_data)
            tmp_path = f.name
        
        try:
            segments, info = _whisper_model.transcribe(
                tmp_path,
                language=language,
                beam_size=5,
            )
            
            text = " ".join([seg.text for seg in segments])
            logger.info(f"STT: 识别完成, 语言={info.language}, 概率={info.language_probability:.2f}")
            return text.strip()
        finally:
            os.unlink(tmp_path)
            
    except Exception as e:
        logger.error(f"STT 失败: {e}")
        return None


def _cleanup_cache(keep: int = 500):
    """清理旧缓存文件，保留最近N个"""
    try:
        files = sorted(
            VOICE_CACHE_DIR.glob("*.mp3"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for old_file in files[keep:]:
            old_file.unlink()
    except Exception:
        pass


def get_voice_status() -> dict:
    """获取语音模块状态"""
    return {
        "tts_available": _tts_available,
        "stt_available": _stt_available,
        "tts_voices": list(TTS_VOICES.keys()),
        "cache_dir": str(VOICE_CACHE_DIR),
        "cache_count": len(list(VOICE_CACHE_DIR.glob("*.mp3"))),
    }
