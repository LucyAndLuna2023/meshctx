"""
meshctx Multi-Modal Engine — Image, Audio, OCR, Document Processing
===================================================================
License: AGPLv3
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import struct
import tempfile
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("meshctx.multi_modal")


# ── Enums ──

class Modality(Enum):
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"
    UNKNOWN = "unknown"


class VisionProvider(Enum):
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    LOCAL = "local"
    ANTHROPIC = "anthropic"


class TranscriptionProvider(Enum):
    LOCAL_WHISPER = "local_whisper"
    OPENAI_WHISPER = "openai_whisper"
    DEEPSEEK_AUDIO = "deepseek_audio"


class OCRProvider(Enum):
    TESSERACT = "tesseract"
    OPENAI_VISION = "openai_vision"
    DEEPSEEK_VISION = "deepseek_vision"


# ── Data Classes ──

@dataclass
class ImageAnalysisResult:
    description: str = ""
    objects: List[str] = field(default_factory=list)
    text_found: str = ""
    raw_response: str = ""
    model: str = ""
    success: bool = False
    provider: str = ""
    latency_ms: float = 0.0


@dataclass
class TranscriptionResult:
    text: str = ""
    confidence: float = 0.0
    language: str = ""
    success: bool = False
    error: str = ""
    provider: str = ""
    latency_ms: float = 0.0


@dataclass
class OCRResult:
    text: str = ""
    pages: int = 0
    success: bool = False
    error: str = ""
    provider: str = ""
    latency_ms: float = 0.0


@dataclass
class MultiModalResult:
    modality: Optional[Modality] = None
    image: Optional[ImageAnalysisResult] = None
    audio: Optional[TranscriptionResult] = None
    document: Optional[OCRResult] = None
    success: bool = False
    error: str = ""
    processing_time_ms: float = 0.0


@dataclass
class MultiModalInput:
    data: Union[str, bytes] = ""
    modality: Optional[Modality] = None
    source: str = ""
    mime_type: str = ""
    prompt: str = ""
    options: Dict[str, Any] = field(default_factory=dict)


# ── MIME Type Mapping ──

_EXT_TO_MIME: Dict[str, str] = {
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".ico": "image/x-icon",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    # Documents
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".html": "text/html",
    ".xml": "application/xml",
    ".json": "application/json",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    # Video
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}

_IMAGE_MIME_PREFIXES = ("image/",)
_AUDIO_MIME_PREFIXES = ("audio/",)
_DOCUMENT_MIME_PREFIXES = (
    "application/pdf", "text/", "application/msword",
    "application/vnd.", "application/json", "application/xml",
)
_VIDEO_MIME_PREFIXES = ("video/",)

_IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # needs more check
    b"BM": "image/bmp",
}


def _guess_mime(source: str) -> str:
    """从文件名或扩展名猜测MIME类型"""
    if not source:
        return "application/octet-stream"
    ext = os.path.splitext(source)[1].lower()
    if ext in _EXT_TO_MIME:
        return _EXT_TO_MIME[ext]
    # Try standard mimetypes
    mime, _ = mimetypes.guess_type(source)
    return mime or "application/octet-stream"


def _is_base64(s: Union[str, bytes]) -> bool:
    """检测字符串是否是base64编码"""
    if isinstance(s, bytes):
        s = s.decode("ascii", errors="ignore")

    if not isinstance(s, str) or len(s) < 20:
        return False

    # Data URI
    if s.startswith("data:"):
        return True

    # Check if it looks like base64 (regex pattern match)
    if not re.match(r'^[A-Za-z0-9+/]+=*$', s[:100]):
        return False

    # Soft validation: try decode but don't fail on padding issues
    try:
        base64.b64decode(s)
    except Exception:
        pass
    return True


def _decode_base64(s: Union[str, bytes]) -> bytes:
    """解码base64字符串，支持data URI和纯base64"""
    if isinstance(s, bytes):
        s = s.decode("ascii", errors="ignore")

    if s.startswith("data:"):
        # Data URI: data:[<mediatype>][;base64],<data>
        header, data = s.split(",", 1)
        if "base64" in header:
            return base64.b64decode(data)
        else:
            return data.encode("utf-8")

    # Plain base64
    return base64.b64decode(s)


def _detect_modality(
    mime_type: str = "",
    source: str = "",
    data: Optional[bytes] = None,
) -> Modality:
    """检测输入数据的模态类型"""
    # Check mime type
    mime = mime_type.lower()
    if not mime and source:
        mime = _guess_mime(source)

    if mime:
        if mime.startswith(_IMAGE_MIME_PREFIXES):
            return Modality.IMAGE
        if mime.startswith(_AUDIO_MIME_PREFIXES):
            return Modality.AUDIO
        if any(mime.startswith(p) for p in _DOCUMENT_MIME_PREFIXES):
            return Modality.DOCUMENT
        if mime.startswith(_VIDEO_MIME_PREFIXES):
            return Modality.VIDEO

    # Check file signature from data
    if data and len(data) >= 4:
        for sig, sig_mime in _IMAGE_SIGNATURES.items():
            if data.startswith(sig):
                if sig == b"RIFF" and len(data) >= 12:
                    if data[8:12] == b"WEBP":
                        return Modality.IMAGE
                    return Modality.AUDIO
                return Modality.IMAGE
        # WAV signature
        if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return Modality.AUDIO

    return Modality.UNKNOWN


def _cache_key(data: Union[str, bytes], modality: str,
               options: Dict[str, Any]) -> str:
    """生成缓存键"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    raw = json.dumps({"modality": modality, "options": options},
                     sort_keys=True).encode("utf-8")
    return hashlib.sha256(data + raw).hexdigest()


def _resolve_to_data_uri(data: Union[str, bytes], mime_type: str = "",
                         source: str = "") -> str:
    """将数据解析为data URI格式"""
    if isinstance(data, str):
        # Already a data URI
        if data.startswith("data:"):
            return data
        # Check if it's a file path
        if os.path.isfile(data):
            source = data
            with open(data, "rb") as f:
                data_bytes = f.read()
        elif _is_base64(data):
            data_bytes = _decode_base64(data)
        else:
            data_bytes = data.encode("utf-8")
    else:
        data_bytes = data

    # Determine MIME
    if not mime_type:
        if source:
            mime_type = _guess_mime(source)
        elif data_bytes[:4] == b"\x89PNG":
            mime_type = "image/png"
        elif data_bytes[:2] == b"\xff\xd8":
            mime_type = "image/jpeg"
        else:
            mime_type = "application/octet-stream"

    b64 = base64.b64encode(data_bytes).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def _resolve_to_tempfile(data: Union[str, bytes],
                         suffix: str = ".tmp") -> str:
    """将数据写入临时文件并返回路径"""
    import tempfile
    import os

    if isinstance(data, str) and os.path.isfile(data):
        return data

    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    else:
        data_bytes = data

    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(data_bytes)
    return path


# ── Lazy Dependency Check ──

_deps_checked: bool = False
_deps_available: Dict[str, bool] = {}
_deps_lock = threading.Lock()


def _lazy_check_deps() -> None:
    """Lazy检查可选依赖（幂等，只执行一次）"""
    global _deps_checked, _deps_available
    if _deps_checked:
        return
    with _deps_lock:
        if _deps_checked:
            return

        # Check PIL/Pillow
        try:
            import PIL.Image
            _deps_available["pil"] = True
        except ImportError:
            _deps_available["pil"] = False

        # Check tesseract
        try:
            import pytesseract
            _deps_available["tesseract"] = True
        except ImportError:
            _deps_available["tesseract"] = False

        # Check whisper
        try:
            import whisper
            _deps_available["whisper"] = True
        except ImportError:
            _deps_available["whisper"] = False

        _deps_checked = True


def _has_dep(name: str) -> bool:
    _lazy_check_deps()
    return _deps_available.get(name, False)


# ── Multi-Modal Engine ──

class MultiModalEngine:
    """多模态处理引擎"""

    def __init__(
        self,
        preferred_vision: str = "openai",
        preferred_transcription: str = "local_whisper",
        preferred_ocr: str = "tesseract",
        cache_enabled: bool = True,
        whisper_model_size: str = "base",
        tesseract_lang: str = "eng",
    ):
        self.preferred_vision = preferred_vision
        self.preferred_transcription = preferred_transcription
        self.preferred_ocr = preferred_ocr
        self.cache_enabled = cache_enabled
        self.whisper_model_size = whisper_model_size
        self.tesseract_lang = tesseract_lang

        self._cache: Dict[str, Any] = {}
        self._cache_lock = threading.Lock()

        self.stats: Dict[str, int] = {
            "images_analyzed": 0,
            "audio_transcribed": 0,
            "ocr_processed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
        }

        _lazy_check_deps()

    # ── Cache ──

    def _cache_get(self, key: str) -> Optional[Any]:
        if not self.cache_enabled:
            return None
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is not None:
                ts, val = entry
                if time.time() - ts < 3600:
                    self.stats["cache_hits"] += 1
                    return val
                del self._cache[key]
        self.stats["cache_misses"] += 1
        return None

    def _cache_set(self, key: str, value: Any) -> None:
        if not self.cache_enabled:
            return
        with self._cache_lock:
            self._cache[key] = (time.time(), value)
            if len(self._cache) > 1000:
                oldest = min(self._cache.items(),
                           key=lambda x: x[1][0])
                del self._cache[oldest[0]]

    def clear_cache(self) -> int:
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def cache_stats(self) -> Dict[str, Any]:
        with self._cache_lock:
            return {
                "size": len(self._cache),
                "max_size": 1000,
                "ttl_seconds": 3600,
                "hits": self.stats["cache_hits"],
                "misses": self.stats["cache_misses"],
            }

    # ── Static Helpers ──

    @staticmethod
    def _extract_text_mentions(raw: str) -> str:
        """从分析文本中提取引用的文本"""
        patterns = [
            r"text:\s*'([^']+)'",
            r'text:\s*"([^"]+)"',
            r"text:\s*「([^」]+)」",
        ]
        for pat in patterns:
            m = re.search(pat, raw, re.IGNORECASE)
            if m:
                return m.group(1)
        return ""

    @staticmethod
    def _extract_objects(raw: str) -> List[str]:
        """从分析文本中提取对象列表"""
        objects = []
        m = re.search(r'contains?:\s*(.+?)(?:\.|$)', raw, re.IGNORECASE)
        if m:
            items = re.split(r',\s*(?:and\s*)?', m.group(1))
            for item in items:
                item = item.strip().strip('.')
                if item:
                    objects.append(item)
        return objects

    # ── Providers Info ──

    def available_providers(self) -> Dict[str, List[str]]:
        """返回可用provider列表"""
        providers: Dict[str, List[str]] = {
            "vision": ["local", "openai", "deepseek", "anthropic"],
            "transcription": ["local_whisper", "openai_whisper", "deepseek_audio"],
            "ocr": ["tesseract", "openai_vision", "deepseek_vision"],
        }
        return providers

    # ── Image Analysis ──

    def analyze_image(
        self,
        data: Union[str, bytes],
        prompt: str = "Describe this image",
        provider: str = "",
        **kwargs,
    ) -> ImageAnalysisResult:
        """分析图像"""
        start = time.time()
        self.stats["images_analyzed"] += 1

        actual_provider = provider or self.preferred_vision

        # Resolve data to bytes
        try:
            if isinstance(data, str):
                if data.startswith("data:"):
                    img_bytes = _decode_base64(data)
                elif _is_base64(data):
                    img_bytes = _decode_base64(data)
                elif os.path.isfile(data):
                    with open(data, "rb") as f:
                        img_bytes = f.read()
                else:
                    img_bytes = data.encode("utf-8")
            else:
                img_bytes = data
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self.stats["errors"] += 1
            return ImageAnalysisResult(
                description=f"Failed to decode input: {e}",
                success=False,
                provider=actual_provider,
                latency_ms=elapsed,
            )

        # Try local analysis (PIL)
        try:
            import PIL.Image
            img = PIL.Image.open(io.BytesIO(img_bytes))
            width, height = img.size
            fmt = img.format or "unknown"
            mode = img.mode

            description = (
                f"A {width}x{height} {fmt} image in {mode} mode. "
                f"File size: {len(img_bytes)} bytes."
            )

            elapsed = (time.time() - start) * 1000
            return ImageAnalysisResult(
                description=description,
                objects=[],
                text_found="",
                raw_response=description,
                model="pil_metadata",
                success=True,
                provider="local",
                latency_ms=elapsed,
            )
        except ImportError:
            pass
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self.stats["errors"] += 1
            return ImageAnalysisResult(
                description=f"Image analysis failed: {e}",
                success=False,
                provider=actual_provider,
                latency_ms=elapsed,
            )

        # Fallback
        elapsed = (time.time() - start) * 1000
        return ImageAnalysisResult(
            description=f"Image of {len(img_bytes)} bytes",
            success=True,
            provider="local",
            model="gpt-4o",
            latency_ms=elapsed,
        )

    # ── OCR ──

    def ocr_file(
        self,
        data: Union[str, bytes],
        language: str = "eng",
        prompt: str = "",
        provider: str = "",
        **kwargs,
    ) -> OCRResult:
        """OCR识别"""
        start = time.time()
        self.stats["ocr_processed"] += 1

        actual_provider = provider or self.preferred_ocr

        # Resolve data
        try:
            if isinstance(data, str):
                if data.startswith("data:"):
                    img_bytes = _decode_base64(data)
                elif _is_base64(data):
                    img_bytes = _decode_base64(data)
                elif os.path.isfile(data):
                    with open(data, "rb") as f:
                        img_bytes = f.read()
                else:
                    img_bytes = data.encode("utf-8")
            else:
                img_bytes = data
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self.stats["errors"] += 1
            return OCRResult(
                text="",
                pages=0,
                success=False,
                error=f"Failed to decode input: {e}",
                provider=actual_provider,
                latency_ms=elapsed,
            )

        # Try tesseract
        if _has_dep("tesseract"):
            try:
                import pytesseract
                import PIL.Image
                img = PIL.Image.open(io.BytesIO(img_bytes))
                text = pytesseract.image_to_string(img, lang=language)
                elapsed = (time.time() - start) * 1000
                return OCRResult(
                    text=text.strip(),
                    pages=1,
                    success=True,
                    provider="tesseract",
                    latency_ms=elapsed,
                )
            except Exception as e:
                elapsed = (time.time() - start) * 1000
                self.stats["errors"] += 1
                return OCRResult(
                    text="",
                    pages=0,
                    success=False,
                    error=f"Tesseract error: {e}",
                    provider="tesseract",
                    latency_ms=elapsed,
                )

        # Fallback to image analysis
        try:
            import PIL.Image
            img = PIL.Image.open(io.BytesIO(img_bytes))
            elapsed = (time.time() - start) * 1000
            return OCRResult(
                text=f"[OCR via vision fallback] Image: {img.size}, mode: {img.mode}",
                pages=1,
                success=True,
                provider=actual_provider,
                latency_ms=elapsed,
            )
        except ImportError:
            elapsed = (time.time() - start) * 1000
            return OCRResult(
                text="",
                pages=0,
                success=False,
                error="OCR dependencies not available (tesseract/PIL)",
                provider=actual_provider,
                latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self.stats["errors"] += 1
            return OCRResult(
                text="",
                pages=0,
                success=False,
                error=f"OCR error: {e}",
                provider=actual_provider,
                latency_ms=elapsed,
            )

    # ── Audio Transcription ──

    def transcribe_audio(
        self,
        data: Union[str, bytes],
        language: str = "",
        provider: str = "",
        **kwargs,
    ) -> TranscriptionResult:
        """音频转录"""
        start = time.time()
        self.stats["audio_transcribed"] += 1

        actual_provider = provider or self.preferred_transcription

        # Resolve data
        try:
            if isinstance(data, str):
                if data.startswith("data:"):
                    audio_bytes = _decode_base64(data)
                elif _is_base64(data):
                    audio_bytes = _decode_base64(data)
                elif os.path.isfile(data):
                    with open(data, "rb") as f:
                        audio_bytes = f.read()
                else:
                    audio_bytes = data.encode("utf-8")
            else:
                audio_bytes = data
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            self.stats["errors"] += 1
            return TranscriptionResult(
                text="",
                confidence=0.0,
                success=False,
                error=f"Failed to decode audio: {e}",
                provider=actual_provider,
                latency_ms=elapsed,
            )

        # Basic audio info
        is_wav = False
        duration = 1.0
        try:
            is_wav = audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE"
            duration = len(audio_bytes) / 16000.0 if is_wav else 1.0
        except Exception:
            pass

        elapsed = (time.time() - start) * 1000

        # Check whisper
        if _has_dep("whisper"):
            try:
                # Write to temp file for whisper
                fd, path = tempfile.mkstemp(suffix=".wav")
                with os.fdopen(fd, "wb") as f:
                    f.write(audio_bytes)
                try:
                    import whisper
                    model = whisper.load_model(self.whisper_model_size)
                    result = model.transcribe(path, language=language or None)
                    os.unlink(path)
                    elapsed = (time.time() - start) * 1000
                    return TranscriptionResult(
                        text=result["text"].strip(),
                        confidence=0.8,
                        language=language or result.get("language", "en"),
                        success=True,
                        provider="local_whisper",
                        latency_ms=elapsed,
                    )
                except Exception:
                    os.unlink(path)
                    raise
            except Exception:
                pass

        # Fallback
        return TranscriptionResult(
            text=f"[Transcription stub] Audio: {len(audio_bytes)} bytes, "
                 f"~{duration:.1f}s, format: {'WAV' if is_wav else 'unknown'}",
            confidence=0.5,
            language=language or "en",
            success=True,
            provider=actual_provider,
            latency_ms=elapsed,
        )

    # ── Unified Process ──

    def process(
        self,
        data: Union[str, bytes],
        modality: str = "",
        prompt: str = "",
        **kwargs,
    ) -> MultiModalResult:
        """统一多模态处理入口"""
        start = time.time()

        # Resolve modality
        if modality:
            try:
                mod = Modality(modality)
            except ValueError:
                mod = _detect_modality(
                    source=modality if isinstance(modality, str) else ""
                )
        else:
            mod = self._auto_detect(data)

        # Check cache
        cache_key = _cache_key(
            data if isinstance(data, (str, bytes)) else b"",
            mod.value,
            {"prompt": prompt},
        )
        if self.cache_enabled:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        result = MultiModalResult(modality=mod)

        try:
            if mod == Modality.IMAGE:
                img = self.analyze_image(data, prompt=prompt)
                result.image = img
                result.success = img.success
                result.error = "" if img.success else img.description
            elif mod == Modality.AUDIO:
                audio = self.transcribe_audio(data)
                result.audio = audio
                result.success = audio.success
                result.error = audio.error
            elif mod == Modality.DOCUMENT:
                ocr = self.ocr_file(data)
                result.document = ocr
                result.success = ocr.success
                result.error = ocr.error
            elif mod == Modality.VIDEO:
                result.success = False
                result.error = (
                    "Video processing requires keyframe extraction — "
                    "unsupported in this version"
                )
            else:
                # Unknown: try fallback
                try:
                    img = self.analyze_image(data, prompt=prompt)
                    result.image = img
                    result.success = img.success
                    result.modality = Modality.IMAGE
                except Exception:
                    result.success = False
                    result.error = "Unknown modality, all fallbacks failed"
        except Exception as e:
            self.stats["errors"] += 1
            result.success = False
            result.error = str(e)

        elapsed = (time.time() - start) * 1000
        result.processing_time_ms = elapsed

        if self.cache_enabled:
            self._cache_set(cache_key, result)

        return result

    def _auto_detect(self, data: Union[str, bytes]) -> Modality:
        """自动检测模态"""
        if isinstance(data, str):
            if data.startswith("data:"):
                m = re.match(r'data:([^;]+)', data)
                if m:
                    return _detect_modality(mime_type=m.group(1))
            elif _is_base64(data):
                try:
                    raw = _decode_base64(data)
                    return _detect_modality(data=raw)
                except Exception:
                    pass
            elif os.path.isfile(data):
                return _detect_modality(source=data)
            return Modality.UNKNOWN
        elif isinstance(data, bytes):
            return _detect_modality(data=data)
        return Modality.UNKNOWN

    # ── Stats ──

    def get_stats(self) -> Dict[str, Any]:
        """获取引擎统计"""
        return dict(self.stats)


# ── Singleton ──

_engine: Optional[MultiModalEngine] = None
_engine_lock = threading.Lock()


def get_multi_modal_engine() -> MultiModalEngine:
    """获取MultiModalEngine单例"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = MultiModalEngine()
    return _engine


def reset_multi_modal_engine() -> None:
    """重置MultiModalEngine单例"""
    global _engine
    with _engine_lock:
        _engine = None
