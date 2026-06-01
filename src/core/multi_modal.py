"""
meshctx v3.100 — Multi-Modal Engine (多模态统一引擎)

Features:
  1) Image Analysis (base64/URL) — vision-capable LLM reasoning
  2) Audio Transcription — speech-to-text via whisper or API
  3) File OCR — extract text from images, PDFs, documents
  4) Unified Multi-Modal Interface — single process() endpoint

Architecture:
  - Provider abstraction: local (whisper/tesseract) + cloud (OpenAI/DeepSeek)
  - Lazy dependency loading: graceful degradation when deps missing
  - Async-first design with sync convenience wrappers
  - Caching layer for repeated OCR/transcription results
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("meshctx.multi_modal")

# ── Optional dependency flags (lazy detection) ──
_HAS_PIL = False
_HAS_PYTESSERACT = False
_HAS_PDF2IMAGE = False
_HAS_WHISPER = False
_HAS_OPENAI = False
_CHECKS_DONE = False


def _lazy_check_deps():
    """One-time lazy check of all optional dependencies."""
    global _HAS_PIL, _HAS_PYTESSERACT, _HAS_PDF2IMAGE
    global _HAS_WHISPER, _HAS_OPENAI, _CHECKS_DONE
    if _CHECKS_DONE:
        return
    _CHECKS_DONE = True

    try:
        from PIL import Image  # noqa: F401
        _HAS_PIL = True
    except ImportError:
        logger.debug("PIL/Pillow not installed — image analysis limited")

    try:
        import pytesseract  # noqa: F401
        _HAS_PYTESSERACT = True
    except ImportError:
        logger.debug("pytesseract not installed — OCR unavailable")

    try:
        from pdf2image import convert_from_bytes  # noqa: F401
        _HAS_PDF2IMAGE = True
    except ImportError:
        logger.debug("pdf2image not installed — PDF OCR limited")

    try:
        import whisper  # noqa: F401
        _HAS_WHISPER = True
    except ImportError:
        logger.debug("openai-whisper not installed — local transcription unavailable")

    try:
        import openai  # noqa: F401
        _HAS_OPENAI = True
    except ImportError:
        logger.debug("openai not installed — cloud vision/transcription unavailable")


# ── Data Types ──

class Modality(Enum):
    """Input modality types."""
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"
    UNKNOWN = "unknown"


class TranscriptionProvider(Enum):
    """Supported transcription backends."""
    LOCAL_WHISPER = "local_whisper"
    OPENAI_WHISPER = "openai_whisper"
    DEEPSEEK_AUDIO = "deepseek_audio"


class OCRProvider(Enum):
    """Supported OCR backends."""
    TESSERACT = "tesseract"
    OPENAI_VISION = "openai_vision"
    DEEPSEEK_VISION = "deepseek_vision"


class VisionProvider(Enum):
    """Supported vision backends."""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    LOCAL = "local"


@dataclass
class ImageAnalysisResult:
    """Result from image analysis."""
    description: str = ""
    objects: List[str] = field(default_factory=list)
    text_found: str = ""
    raw_response: str = ""
    provider: str = ""
    model: str = ""
    tokens_used: int = 0
    latency_ms: float = 0.0
    success: bool = False
    error: str = ""


@dataclass
class TranscriptionResult:
    """Result from audio transcription."""
    text: str = ""
    language: str = ""
    segments: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    provider: str = ""
    model: str = ""
    confidence: float = 0.0
    success: bool = False
    error: str = ""


@dataclass
class OCRResult:
    """Result from OCR processing."""
    text: str = ""
    confidence: float = 0.0
    language: str = ""
    pages: int = 0
    paragraphs: List[str] = field(default_factory=list)
    provider: str = ""
    latency_ms: float = 0.0
    success: bool = False
    error: str = ""


@dataclass
class MultiModalResult:
    """Unified result from the multi-modal engine."""
    modality: Modality = Modality.UNKNOWN
    image: Optional[ImageAnalysisResult] = None
    transcription: Optional[TranscriptionResult] = None
    ocr: Optional[OCRResult] = None
    raw_input_type: str = ""
    processing_time_ms: float = 0.0
    success: bool = False
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultiModalInput:
    """Unified input container for multi-modal processing."""
    data: Union[str, bytes] = ""
    modality: Optional[Modality] = None
    source: str = ""          # file path, URL, or "inline"
    mime_type: str = ""
    prompt: str = ""          # additional instruction for vision/analysis
    language: str = ""        # hint for transcription/OCR
    options: Dict[str, Any] = field(default_factory=dict)


# ── Helpers ──

def _detect_modality(mime_type: str = "", data: Union[str, bytes] = "", source: str = "") -> Modality:
    """Auto-detect modality from mime type, source path, or data signature."""
    mime = mime_type.lower()
    src = source.lower()

    # Audio
    audio_mimes = {"audio/", "audio/wav", "audio/mpeg", "audio/mp3", "audio/mp4",
                   "audio/ogg", "audio/webm", "audio/flac", "audio/x-m4a"}
    audio_exts = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac", ".webm", ".opus"}
    if any(mime.startswith(a) for a in audio_mimes):
        return Modality.AUDIO
    if any(src.endswith(ext) for ext in audio_exts):
        return Modality.AUDIO

    # Image
    image_mimes = {"image/", "image/png", "image/jpeg", "image/gif",
                   "image/webp", "image/bmp", "image/tiff"}
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
    if any(mime.startswith(i) for i in image_mimes):
        return Modality.IMAGE
    if any(src.endswith(ext) for ext in image_exts):
        return Modality.IMAGE

    # Document
    doc_mimes = {"application/pdf", "application/msword",
                 "application/vnd.openxmlformats-officedocument",
                 "text/", "application/rtf"}
    doc_exts = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt"}
    if any(mime.startswith(d) for d in doc_mimes):
        return Modality.DOCUMENT
    if any(src.endswith(ext) for ext in doc_exts):
        return Modality.DOCUMENT

    # Video
    video_mimes = {"video/"}
    video_exts = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}
    if any(mime.startswith(v) for v in video_mimes):
        return Modality.VIDEO
    if any(src.endswith(ext) for ext in video_exts):
        return Modality.VIDEO

    # Try signature detection from raw bytes
    if isinstance(data, bytes) and len(data) >= 4:
        # PNG: 89 50 4E 47
        if data[:4] == b'\x89PNG':
            return Modality.IMAGE
        # JPEG: FF D8 FF
        if data[:3] == b'\xff\xd8\xff':
            return Modality.IMAGE
        # GIF: 47 49 46
        if data[:3] == b'GIF':
            return Modality.IMAGE
        # PDF: 25 50 44 46
        if data[:4] == b'%PDF':
            return Modality.DOCUMENT
        # RIFF/WAV: 52 49 46 46
        if data[:4] == b'RIFF':
            return Modality.AUDIO

    return Modality.UNKNOWN


def _is_base64(s: str) -> bool:
    """Check if string looks like base64 data (with or without data URI prefix)."""
    if s.startswith("data:"):
        return True
    # Quick heuristic: long string with base64 character set
    if len(s) > 64 and all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=' for c in s[:100]):
        return True
    return False


def _decode_base64(data: str) -> bytes:
    """Decode base64 data, stripping data URI prefix if present."""
    if data.startswith("data:"):
        # data:image/png;base64,xxxxx
        header, b64 = data.split(",", 1)
        return base64.b64decode(b64)
    return base64.b64decode(data)


def _cache_key(data: Union[str, bytes], modality: str, options: Dict[str, Any]) -> str:
    """Generate a deterministic cache key."""
    raw = data if isinstance(data, str) else data.hex()[:256]
    opts = json.dumps(options, sort_keys=True)
    return hashlib.sha256(f"{raw}:{modality}:{opts}".encode()).hexdigest()


# ── MultiModalEngine ──

class MultiModalEngine:
    """
    Unified multi-modal processing engine.

    Supports:
      - Image analysis via vision LLMs (base64 or URL)
      - Audio transcription via local whisper or cloud API
      - File OCR via tesseract or vision LLMs
      - Smart modality detection
      - Result caching
      - Graceful degradation when optional dependencies are missing

    Usage:
        engine = MultiModalEngine()
        result = engine.process("path/to/image.png", prompt="Describe this image")
        print(result.image.description)

        result = engine.process("path/to/audio.mp3")
        print(result.transcription.text)

        result = engine.process("path/to/document.pdf")
        print(result.ocr.text)
    """

    # Cache configuration
    _CACHE_SIZE = 128
    _CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(
        self,
        preferred_vision: Optional[str] = None,
        preferred_transcription: Optional[str] = None,
        preferred_ocr: Optional[str] = None,
        cache_enabled: bool = True,
        whisper_model_size: str = "base",
        tesseract_lang: str = "eng",
    ):
        _lazy_check_deps()

        self.preferred_vision = preferred_vision
        self.preferred_transcription = preferred_transcription
        self.preferred_ocr = preferred_ocr
        self.cache_enabled = cache_enabled
        self.whisper_model_size = whisper_model_size
        self.tesseract_lang = tesseract_lang

        # Lazy-loaded models
        self._whisper_model = None
        self._ocr_engine = None

        # Result cache: key → (timestamp, result)
        self._cache: Dict[str, Tuple[float, MultiModalResult]] = {}

        # Stats
        self.stats = {
            "images_analyzed": 0,
            "audio_transcribed": 0,
            "ocr_processed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0,
        }

        logger.info("MultiModalEngine v3.100 initialized (cache=%s)", cache_enabled)

    # ── Public API ──

    def process(
        self,
        data: Union[str, bytes],
        *,
        modality: Optional[str] = None,
        prompt: str = "",
        source: str = "",
        mime_type: str = "",
        language: str = "",
        **options,
    ) -> MultiModalResult:
        """
        Unified multi-modal processing endpoint.

        Args:
            data: File path, URL, base64 string, or raw bytes
            modality: Force modality ("image", "audio", "document", "video")
            prompt: Additional instruction for vision/OCR analysis
            source: Original source path or URL
            mime_type: MIME type hint
            language: Language hint (ISO 639-1)
            **options: Provider-specific options

        Returns:
            MultiModalResult with populated sub-results
        """
        t0 = time.monotonic()

        # Resolve input
        if isinstance(data, str) and os.path.isfile(data):
            source = source or data
            mime_type = mime_type or _guess_mime(data)
            with open(data, "rb") as f:
                raw_bytes = f.read()
            data = raw_bytes
        elif isinstance(data, str) and (data.startswith("http://") or data.startswith("https://")):
            source = data
            raw_bytes = _fetch_url(data)
            data = raw_bytes
        elif isinstance(data, str) and _is_base64(data):
            raw_bytes = _decode_base64(data)
            data = raw_bytes
        elif isinstance(data, bytes):
            raw_bytes = data
        else:
            raw_bytes = data.encode("utf-8") if isinstance(data, str) else data

        # Detect modality
        if modality:
            try:
                mod = Modality(modality.lower())
            except ValueError:
                mod = Modality.UNKNOWN
        else:
            mod = _detect_modality(mime_type, raw_bytes, source)

        # Check cache
        cache_key = _cache_key(raw_bytes, mod.value, options)
        if self.cache_enabled:
            cached = self._cache_get(cache_key)
            if cached:
                cached.processing_time_ms = (time.monotonic() - t0) * 1000
                return cached

        # Dispatch
        result = MultiModalResult(modality=mod, raw_input_type=mime_type)

        try:
            if mod == Modality.IMAGE:
                result.image = self.analyze_image(raw_bytes, prompt=prompt, source=source,
                                                   mime_type=mime_type, **options)
                result.success = result.image.success
                result.error = result.image.error
                self.stats["images_analyzed"] += 1

            elif mod == Modality.AUDIO:
                result.transcription = self.transcribe_audio(raw_bytes, language=language,
                                                              source=source, **options)
                result.success = result.transcription.success
                result.error = result.transcription.error
                self.stats["audio_transcribed"] += 1

            elif mod == Modality.DOCUMENT:
                result.ocr = self.ocr_file(raw_bytes, prompt=prompt, language=language,
                                            source=source, **options)
                result.success = result.ocr.success
                result.error = result.ocr.error
                self.stats["ocr_processed"] += 1

            elif mod == Modality.VIDEO:
                result.error = "Video modality: only keyframe extraction supported via image chaining"
                self.stats["errors"] += 1

            else:
                # Try heuristics: try all modalities
                result = self._process_unknown(raw_bytes, prompt=prompt, language=language,
                                                source=source, mime_type=mime_type, **options)

        except Exception as e:
            logger.exception("Multi-modal processing failed")
            result.success = False
            result.error = str(e)
            self.stats["errors"] += 1

        result.processing_time_ms = (time.monotonic() - t0) * 1000

        # Store in cache
        if self.cache_enabled and result.success:
            self._cache_set(cache_key, result)

        return result

    def analyze_image(
        self,
        data: Union[str, bytes],
        *,
        prompt: str = "Describe this image in detail.",
        source: str = "",
        mime_type: str = "",
        model: Optional[str] = None,
        **options,
    ) -> ImageAnalysisResult:
        """
        Analyze an image using a vision-capable LLM.

        Args:
            data: Image as file path, URL, base64 string, or raw bytes
            prompt: Instruction for the vision model
            source: Original source path or URL
            mime_type: MIME type (e.g. image/png)
            model: Override vision model

        Returns:
            ImageAnalysisResult
        """
        t0 = time.monotonic()
        result = ImageAnalysisResult()

        try:
            # Resolve image to base64 data URI
            b64_uri = _resolve_to_data_uri(data, mime_type)
            result.provider = self.preferred_vision or self._detect_vision_provider()
            result.model = model or "gpt-4o"

            if result.provider in ("openai", "deepseek") and _HAS_OPENAI:
                import openai

                client = openai.OpenAI(
                    api_key=os.getenv(
                        "OPENAI_API_KEY" if result.provider == "openai" else "DEEPSEEK_API_KEY"
                    ),
                    base_url=os.getenv("OPENAI_BASE_URL") if result.provider == "openai" else (
                        "https://api.deepseek.com/v1" if result.provider == "deepseek" else None
                    ),
                )

                response = client.chat.completions.create(
                    model=result.model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": b64_uri, "detail": "auto"}},
                        ],
                    }],
                    max_tokens=options.get("max_tokens", 1024),
                )

                result.raw_response = response.choices[0].message.content or ""
                result.success = True
                if hasattr(response, "usage"):
                    result.tokens_used = response.usage.total_tokens

                # Parse structured fields from response
                result.description = result.raw_response
                result.text_found = self._extract_text_mentions(result.raw_response)
                result.objects = self._extract_objects(result.raw_response)

            elif result.provider == "anthropic":
                # Anthropic Claude vision via messages API
                result = self._analyze_image_anthropic(data, prompt, result, options)

            elif result.provider == "local":
                # Local fallback: basic metadata extraction only
                result = self._analyze_image_local(data, prompt, result)

            else:
                result.error = f"No vision provider available. Tried: {result.provider}"
                return result

        except Exception as e:
            logger.exception("Image analysis failed")
            result.success = False
            result.error = str(e)

        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    def transcribe_audio(
        self,
        data: Union[str, bytes],
        *,
        language: str = "",
        source: str = "",
        provider: Optional[str] = None,
        **options,
    ) -> TranscriptionResult:
        """
        Transcribe audio to text.

        Args:
            data: Audio as file path, URL, or raw bytes
            language: ISO 639-1 language code hint
            source: Original file path or URL
            provider: Force provider (local_whisper, openai_whisper)

        Returns:
            TranscriptionResult
        """
        t0 = time.monotonic()
        result = TranscriptionResult()
        result.language = language

        try:
            # Resolve to file path (whisper needs a file)
            audio_path = _resolve_to_tempfile(data, suffix=".wav")

            chosen_provider = provider or self.preferred_transcription or self._detect_transcription_provider()

            if chosen_provider == "local_whisper" and _HAS_WHISPER:
                result = self._transcribe_local_whisper(audio_path, language, result, options)
            elif chosen_provider in ("openai_whisper", "deepseek_audio") and _HAS_OPENAI:
                result = self._transcribe_openai(audio_path, language, result, options)
            elif chosen_provider == "deepseek_audio":
                result.error = "DeepSeek audio API not yet available — use local_whisper or openai_whisper"
            else:
                result = self._transcribe_local_whisper(audio_path, language, result, options)

        except Exception as e:
            logger.exception("Audio transcription failed")
            result.success = False
            result.error = str(e)

        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    def ocr_file(
        self,
        data: Union[str, bytes],
        *,
        prompt: str = "Extract all text from this document.",
        language: str = "eng",
        source: str = "",
        provider: Optional[str] = None,
        **options,
    ) -> OCRResult:
        """
        Extract text from documents (images, PDFs) via OCR.

        Args:
            data: Document as file path, URL, bytes
            prompt: Instruction for vision-based OCR
            language: Tesseract language code(s), e.g. "eng" or "eng+chi_sim"
            source: Original path or URL
            provider: Force OCR provider

        Returns:
            OCRResult
        """
        t0 = time.monotonic()
        result = OCRResult()
        result.language = language

        try:
            chosen_provider = provider or self.preferred_ocr or self._detect_ocr_provider()

            if chosen_provider == "tesseract" and _HAS_PYTESSERACT and _HAS_PIL:
                result = self._ocr_tesseract(data, language, result, options)
            elif chosen_provider in ("openai_vision", "deepseek_vision"):
                # Use vision API for OCR — more accurate but slower/more expensive
                img_result = self.analyze_image(
                    data, prompt=prompt or "Extract ALL text visible in this image/document. Return ONLY the extracted text, preserving layout.",
                    **options,
                )
                if img_result.success:
                    result.text = img_result.raw_response
                    result.confidence = 0.9
                    result.provider = chosen_provider
                    result.success = True
                    result.paragraphs = [p.strip() for p in result.text.split("\n\n") if p.strip()]
                else:
                    result.error = img_result.error
            else:
                # Fallback to tesseract attempt
                result = self._ocr_tesseract(data, language, result, options)

        except Exception as e:
            logger.exception("OCR processing failed")
            result.success = False
            result.error = str(e)

        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    # ── Provider detection ──

    def available_providers(self) -> Dict[str, List[str]]:
        """Return dict of available providers per modality."""
        _lazy_check_deps()
        providers = {"vision": [], "transcription": [], "ocr": []}

        if _HAS_OPENAI and os.getenv("OPENAI_API_KEY"):
            providers["vision"].append("openai")
            providers["transcription"].append("openai_whisper")
            providers["ocr"].append("openai_vision")
        if os.getenv("DEEPSEEK_API_KEY"):
            providers["vision"].append("deepseek")
            providers["ocr"].append("deepseek_vision")
        if os.getenv("ANTHROPIC_API_KEY"):
            providers["vision"].append("anthropic")
        if _HAS_WHISPER:
            providers["transcription"].append("local_whisper")
        if _HAS_PYTESSERACT:
            providers["ocr"].append("tesseract")
        # Always have local fallback
        providers["vision"].append("local")

        return providers

    def _detect_vision_provider(self) -> str:
        """Auto-select best available vision provider."""
        available = self.available_providers()["vision"]
        for pref in ("openai", "deepseek", "anthropic", "local"):
            if pref in available:
                return pref
        return "local"

    def _detect_transcription_provider(self) -> str:
        """Auto-select best available transcription provider."""
        available = self.available_providers()["transcription"]
        for pref in ("openai_whisper", "local_whisper", "deepseek_audio"):
            if pref in available:
                return pref
        return "local_whisper"

    def _detect_ocr_provider(self) -> str:
        """Auto-select best available OCR provider."""
        available = self.available_providers()["ocr"]
        for pref in ("tesseract", "openai_vision", "deepseek_vision"):
            if pref in available:
                return pref
        return "tesseract"

    # ── Internal: Image Analysis ──

    def _analyze_image_anthropic(
        self, data: Union[str, bytes], prompt: str,
        result: ImageAnalysisResult, options: Dict[str, Any],
    ) -> ImageAnalysisResult:
        """Analyze image via Anthropic Claude."""
        try:
            import anthropic

            b64_uri = _resolve_to_data_uri(data)
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
            response = client.messages.create(
                model=options.get("model", "claude-3-opus-20240229"),
                max_tokens=options.get("max_tokens", 1024),
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64",
                            "media_type": _mime_from_data_uri(b64_uri),
                            "data": b64_uri.split(",", 1)[1] if "," in b64_uri else b64_uri,
                        }},
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            result.raw_response = response.content[0].text
            result.description = result.raw_response
            result.success = True
            result.provider = "anthropic"
            result.model = options.get("model", "claude-3-opus-20240229")
        except ImportError:
            result.error = "anthropic package not installed"
        except Exception as e:
            result.error = str(e)
        return result

    def _analyze_image_local(
        self, data: Union[str, bytes], prompt: str,
        result: ImageAnalysisResult,
    ) -> ImageAnalysisResult:
        """Local image analysis via PIL metadata extraction."""
        if not _HAS_PIL:
            result.error = "PIL not available for local image analysis"
            return result

        try:
            from PIL import Image

            if isinstance(data, str) and os.path.isfile(data):
                img = Image.open(data)
            elif isinstance(data, bytes):
                img = Image.open(io.BytesIO(data))
            else:
                result.error = "Unsupported data format for local analysis"
                return result

            info: Dict[str, Any] = {
                "format": img.format,
                "size": img.size,
                "mode": img.mode,
            }
            if hasattr(img, "info"):
                info.update({k: str(v) for k, v in img.info.items() if k != "icc_profile"})

            result.raw_response = json.dumps(info, indent=2, default=str)
            result.description = f"Image: {img.format} {img.size[0]}x{img.size[1]} {img.mode}"
            result.success = True
            result.provider = "local"
            result.model = "pil_metadata"
        except Exception as e:
            result.error = str(e)

        return result

    # ── Internal: Audio Transcription ──

    def _transcribe_local_whisper(
        self, audio_path: str, language: str,
        result: TranscriptionResult, options: Dict[str, Any],
    ) -> TranscriptionResult:
        """Transcribe using local whisper model."""
        if not _HAS_WHISPER:
            result.error = "openai-whisper not installed. Run: pip install openai-whisper"
            return result

        try:
            import whisper

            if self._whisper_model is None:
                logger.info("Loading whisper model: %s", self.whisper_model_size)
                self._whisper_model = whisper.load_model(self.whisper_model_size)

            transcribe_opts: Dict[str, Any] = {}
            if language:
                transcribe_opts["language"] = language

            raw = self._whisper_model.transcribe(audio_path, **transcribe_opts)

            result.text = raw["text"].strip()
            result.language = raw.get("language", language)
            result.segments = raw.get("segments", [])
            result.provider = "local_whisper"
            result.model = f"whisper-{self.whisper_model_size}"
            result.confidence = 0.85  # whisper doesn't expose per-file confidence
            result.success = True

        except Exception as e:
            result.error = str(e)

        return result

    def _transcribe_openai(
        self, audio_path: str, language: str,
        result: TranscriptionResult, options: Dict[str, Any],
    ) -> TranscriptionResult:
        """Transcribe using OpenAI Whisper API."""
        if not _HAS_OPENAI:
            result.error = "openai package not installed"
            return result

        try:
            import openai

            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            with open(audio_path, "rb") as f:
                response = client.audio.transcriptions.create(
                    model=options.get("model", "whisper-1"),
                    file=f,
                    language=language or None,
                    response_format="verbose_json" if options.get("verbose") else "text",
                )

            if hasattr(response, "text"):
                result.text = response.text.strip()
                result.language = getattr(response, "language", language)
                result.segments = [s.model_dump() for s in getattr(response, "segments", [])]
            else:
                result.text = str(response).strip()

            result.provider = "openai_whisper"
            result.model = options.get("model", "whisper-1")
            result.confidence = 0.95
            result.success = True

        except Exception as e:
            result.error = str(e)

        return result

    # ── Internal: OCR ──

    def _ocr_tesseract(
        self, data: Union[str, bytes], language: str,
        result: OCRResult, options: Dict[str, Any],
    ) -> OCRResult:
        """OCR using pytesseract (supports images; PDF via pdf2image)."""
        if not _HAS_PYTESSERACT or not _HAS_PIL:
            result.error = "pytesseract and Pillow required for Tesseract OCR. Run: pip install pytesseract Pillow"
            return result

        try:
            import pytesseract
            from PIL import Image

            images: List[Image.Image] = []

            # Handle PDF via pdf2image
            is_pdf = False
            if isinstance(data, bytes) and data[:4] == b'%PDF':
                is_pdf = True
            elif isinstance(data, str) and data.lower().endswith(".pdf") and os.path.isfile(data):
                is_pdf = True
                with open(data, "rb") as f:
                    data = f.read()

            if is_pdf and _HAS_PDF2IMAGE:
                from pdf2image import convert_from_bytes
                pdf_bytes = data if isinstance(data, bytes) else open(data, "rb").read()
                images = convert_from_bytes(pdf_bytes)
            elif isinstance(data, str) and os.path.isfile(data):
                images = [Image.open(data)]
            elif isinstance(data, bytes):
                images = [Image.open(io.BytesIO(data))]
            else:
                result.error = "Unsupported data format for OCR"
                return result

            all_text: List[str] = []
            for img in images:
                text = pytesseract.image_to_string(img, lang=language)
                all_text.append(text.strip())

            result.text = "\n\n".join(all_text)
            result.pages = len(images)
            result.paragraphs = [p.strip() for p in result.text.split("\n\n") if p.strip()]
            result.provider = "tesseract"
            result.success = True
            result.confidence = 0.7  # approximate

        except Exception as e:
            result.error = str(e)

        return result

    # ── Internal: Unknown modality ──

    def _process_unknown(
        self, data: bytes, prompt: str, language: str,
        source: str, mime_type: str, **options,
    ) -> MultiModalResult:
        """Try all modalities when type is unknown (heuristic fallback)."""
        # Try image first (most common)
        img_result = self.analyze_image(data, prompt=prompt, source=source, mime_type=mime_type, **options)
        if img_result.success and len(img_result.raw_response) > 10:
            return MultiModalResult(
                modality=Modality.IMAGE,
                image=img_result,
                success=True,
                raw_input_type=mime_type,
            )

        # Try OCR
        ocr_result = self.ocr_file(data, prompt=prompt, language=language, source=source, **options)
        if ocr_result.success:
            return MultiModalResult(
                modality=Modality.DOCUMENT,
                ocr=ocr_result,
                success=True,
                raw_input_type=mime_type,
            )

        # Try transcription
        trans_result = self.transcribe_audio(data, language=language, source=source, **options)
        if trans_result.success:
            return MultiModalResult(
                modality=Modality.AUDIO,
                transcription=trans_result,
                success=True,
                raw_input_type=mime_type,
            )

        return MultiModalResult(
            modality=Modality.UNKNOWN,
            success=False,
            error="Could not determine modality or all processing attempts failed",
            raw_input_type=mime_type,
        )

    # ── Text extraction helpers ──

    @staticmethod
    def _extract_text_mentions(raw: str) -> str:
        """Extract text that the vision model found in the image."""
        markers = ["text:", "text found:", "contains text:", "the image contains:", "reads:"]
        for marker in markers:
            idx = raw.lower().find(marker)
            if idx >= 0:
                return raw[idx + len(marker):].split("\n")[0].strip().strip('"\'')
        return ""

    @staticmethod
    def _extract_objects(raw: str) -> List[str]:
        """Extract object mentions from vision response."""
        # Simple heuristic: look for listed objects
        objects: List[str] = []
        markers = ["objects:", "contains:", "shows:", "depicts:", "items:"]
        for marker in markers:
            idx = raw.lower().find(marker)
            if idx >= 0:
                snippet = raw[idx + len(marker):].split("\n")[0]
                objects.extend([o.strip().strip('",.') for o in snippet.split(",") if o.strip()])
                break
        return objects[:10]  # cap at 10

    # ── Cache ──

    def _cache_get(self, key: str) -> Optional[MultiModalResult]:
        """Get cached result if not expired."""
        entry = self._cache.get(key)
        if entry is None:
            self.stats["cache_misses"] += 1
            return None
        ts, result = entry
        if time.monotonic() - ts > self._CACHE_TTL_SECONDS:
            del self._cache[key]
            self.stats["cache_misses"] += 1
            return None
        self.stats["cache_hits"] += 1
        return result

    def _cache_set(self, key: str, result: MultiModalResult) -> None:
        """Store result in cache with LRU eviction."""
        if len(self._cache) >= self._CACHE_SIZE:
            # Evict oldest
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[key] = (time.monotonic(), result)

    def clear_cache(self) -> int:
        """Clear all cached results. Returns number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def cache_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        return {
            "size": len(self._cache),
            "max_size": self._CACHE_SIZE,
            "ttl_seconds": self._CACHE_TTL_SECONDS,
            "hits": self.stats["cache_hits"],
            "misses": self.stats["cache_misses"],
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return engine statistics."""
        return {**self.stats, "cache": self.cache_stats()}


# ── Helpers ──

def _guess_mime(path: str) -> str:
    """Guess MIME type from file extension."""
    ext_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".svg": "image/svg+xml",
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
        ".flac": "audio/flac", ".m4a": "audio/x-m4a", ".aac": "audio/aac",
        ".webm": "audio/webm",
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain", ".rtf": "application/rtf",
    }
    ext = os.path.splitext(path)[1].lower()
    return ext_map.get(ext, "application/octet-stream")


def _resolve_to_data_uri(data: Union[str, bytes], mime_type: str = "") -> str:
    """Resolve data to a base64 data URI string."""
    if isinstance(data, str) and data.startswith("data:"):
        return data
    if isinstance(data, str) and (data.startswith("http://") or data.startswith("https://")):
        raw = _fetch_url(data)
        mime = mime_type or "image/png"
        b64 = base64.b64encode(raw).decode()
        return f"data:{mime};base64,{b64}"
    if isinstance(data, str) and os.path.isfile(data):
        mime = mime_type or _guess_mime(data)
        with open(data, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:{mime};base64,{b64}"
    if isinstance(data, bytes):
        mime = mime_type or "image/png"
        b64 = base64.b64encode(data).decode()
        return f"data:{mime};base64,{b64}"
    # Assume base64 string
    if _is_base64(data):
        return data if data.startswith("data:") else f"data:image/png;base64,{data}"
    return str(data)


def _mime_from_data_uri(uri: str) -> str:
    """Extract MIME type from data URI."""
    if uri.startswith("data:"):
        return uri.split(";")[0].replace("data:", "")
    return "image/png"


def _resolve_to_tempfile(data: Union[str, bytes], suffix: str = ".tmp") -> str:
    """Resolve input to a temporary file path."""
    if isinstance(data, str) and os.path.isfile(data):
        return data
    if isinstance(data, str) and (data.startswith("http://") or data.startswith("https://")):
        raw = _fetch_url(data)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(raw)
            return f.name
    if isinstance(data, bytes):
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(data)
            return f.name
    # String -> write to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(data.encode() if isinstance(data, str) else data)
        return f.name


def _fetch_url(url: str, timeout: int = 30) -> bytes:
    """Fetch URL content as bytes."""
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "meshctx/3.100"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ── Singleton ──

_engine: Optional[MultiModalEngine] = None


def get_multi_modal_engine(**kwargs) -> MultiModalEngine:
    """Get or create the singleton MultiModalEngine instance."""
    global _engine
    if _engine is None:
        _engine = MultiModalEngine(**kwargs)
    return _engine


def reset_multi_modal_engine() -> None:
    """Reset the singleton engine (useful for testing)."""
    global _engine
    _engine = None
