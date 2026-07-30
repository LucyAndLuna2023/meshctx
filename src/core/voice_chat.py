"""meshctx voice_chat — v3.103 Voice Chat Engine

⚠️ 开源版 Stub 模式：TTS 语音合成和 STT 语音识别当前返回空数据。
完整语音引擎在 meshctx-core 私有核心中。
会话管理、语言映射、缓存系统为真实实现。"""

import base64
import hashlib
import json
import math
import os
import re
import struct
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class TTSProvider(Enum):
    EDGE_TTS = "edge_tts"
    GTTS = "gtts"
    PYTTSX3 = "pyttsx3"
    OPENAI = "openai"


class STTProvider(Enum):
    WHISPER = "whisper"
    WHISPER_API = "whisper_api"
    GOOGLE = "google"
    SPHINX = "sphinx"


class VoiceLanguage(Enum):
    EN = "en"
    ZH = "zh"
    JA = "ja"
    KO = "ko"
    FR = "fr"
    DE = "de"
    ES = "es"
    PT = "pt"
    IT = "it"
    RU = "ru"
    AR = "ar"
    HI = "hi"
    TH = "th"
    VI = "vi"
    TR = "tr"
    NL = "nl"
    PL = "pl"
    SV = "sv"
    DA = "da"
    AUTO = "auto"


class AudioFormat(Enum):
    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    PCM = "pcm"


class VoiceGender(Enum):
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


# ═══════════════════════════════════════════════════════════════
# Language maps
# ═══════════════════════════════════════════════════════════════

_EDGE_VOICES: Dict[str, str] = {
    "en": "en-US-JennyNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "es": "es-ES-ElviraNeural",
    "pt": "pt-BR-FranciscaNeural",
    "it": "it-IT-ElsaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ar": "ar-SA-ZariyahNeural",
    "hi": "hi-IN-SwaraNeural",
    "th": "th-TH-PremwadeeNeural",
    "vi": "vi-VN-HoaiMyNeural",
    "tr": "tr-TR-EmelNeural",
    "nl": "nl-NL-FennaNeural",
    "pl": "pl-PL-AgnieszkaNeural",
    "sv": "sv-SE-SofieNeural",
    "da": "da-DK-ChristelNeural",
}

_GTTS_LANG_MAP: Dict[str, str] = {
    "en": "en",
    "zh": "zh-CN",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "pt": "pt",
    "it": "it",
    "ru": "ru",
    "ar": "ar",
    "hi": "hi",
    "th": "th",
    "vi": "vi",
    "tr": "tr",
    "nl": "nl",
    "pl": "pl",
    "sv": "sv",
    "da": "da",
}

_WHISPER_LANG_MAP: Dict[str, str] = {
    "english": "en",
    "chinese": "zh",
    "japanese": "ja",
    "korean": "ko",
    "french": "fr",
    "german": "de",
    "spanish": "es",
    "portuguese": "pt",
    "italian": "it",
    "russian": "ru",
    "arabic": "ar",
    "hindi": "hi",
    "thai": "th",
    "vietnamese": "vi",
    "turkish": "tr",
    "dutch": "nl",
    "polish": "pl",
    "swedish": "sv",
    "danish": "da",
}


# ═══════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════

@dataclass
class TTSResult:
    audio_bytes: bytes = b""
    audio_format: AudioFormat = AudioFormat.MP3
    duration_ms: float = 0.0
    text_length: int = 0
    provider: TTSProvider = TTSProvider.EDGE_TTS
    language: str = "en"
    voice: str = ""
    request_id: str = ""
    success: bool = True
    error: str = ""

    def __post_init__(self, **kw):
        if not self.request_id:
            self.request_id = str(uuid.uuid4())[:8]

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "audio_size_bytes": len(self.audio_bytes),
            "audio_format": self.audio_format.value,
            "duration_ms": self.duration_ms,
            "text_length": self.text_length,
            "provider": self.provider.value,
            "language": self.language,
            "voice": self.voice,
            "request_id": self.request_id,
            "success": self.success,
            "error": self.error,
        }

    def to_base64(self, **kw) -> str:
        b64 = base64.b64encode(self.audio_bytes).decode("ascii")
        mime = f"audio/{self.audio_format.value}"
        return f"data:{mime};base64,{b64}"

    def save(self, path: str, **kw) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.audio_bytes)
        return str(p)


@dataclass
class STTResult:
    text: str = ""
    language: str = "en"
    confidence: float = 0.0
    duration_ms: float = 0.0
    provider: STTProvider = STTProvider.WHISPER
    segments: List[Dict[str, Any]] = field(default_factory=list)
    request_id: str = ""
    success: bool = True
    error: str = ""

    def __post_init__(self, **kw):
        if not self.request_id:
            self.request_id = str(uuid.uuid4())[:8]

    def to_dict(self, **kw) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "provider": self.provider.value,
            "segments": self.segments,
            "request_id": self.request_id,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class VoiceChatConfig:
    default_tts_provider: TTSProvider = TTSProvider.EDGE_TTS
    default_stt_provider: STTProvider = STTProvider.WHISPER
    default_language: str = "en"
    default_audio_format: AudioFormat = AudioFormat.MP3
    max_text_length: int = 5000
    tts_speed: float = 1.0
    cache_enabled: bool = True


@dataclass
class VoiceChatSession:
    session_id: str = ""
    language: str = "en"
    tts_provider: TTSProvider = TTSProvider.EDGE_TTS
    turn_count: int = 0
    conversation: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, speaker: str, text: str, **kw):
        self.conversation.append({"speaker": speaker, "text": text})
        self.turn_count += 1

    def get_context(self, max_turns: int = 10, **kw) -> List[Dict[str, str]]:
        return self.conversation[-max_turns:]


# ═══════════════════════════════════════════════════════════════
# Audio utilities
# ═══════════════════════════════════════════════════════════════

def _wrap_pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, num_channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Wrap raw PCM data into a WAV container."""
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = len(pcm_data)

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm_data


def create_sine_wav(duration_ms: int = 500, frequency: float = 440.0, sample_rate: int = 16000) -> bytes:
    """Generate a WAV file with a sine tone."""
    num_samples = int(sample_rate * duration_ms / 1000.0)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = int(0.3 * 32767 * math.sin(2 * math.pi * frequency * t))
        samples.append(struct.pack("<h", val))
    pcm = b"".join(samples)
    return _wrap_pcm_to_wav(pcm, sample_rate=sample_rate)


# ═══════════════════════════════════════════════════════════════
# VoiceChat Engine
# ═══════════════════════════════════════════════════════════════

class VoiceChat:
    """Voice chat engine supporting TTS, STT, multi-language, sessions."""

    def __init__(
        self,
        config: Optional[VoiceChatConfig] = None,
        tts_provider: Optional[TTSProvider] = None,
        language: Optional[str] = None,
        cache_enabled: Optional[bool] = None,
    ):
        self.config = config or VoiceChatConfig()
        if tts_provider:
            self.config.default_tts_provider = tts_provider
        if language:
            self.config.default_language = language
        if cache_enabled is not None:
            self.config.cache_enabled = cache_enabled

        self._sessions: Dict[str, VoiceChatSession] = {}
        self._tts_cache: Dict[str, TTSResult] = {}

    # ── Session management ────────────────────────────────────

    def create_session(
        self,
        language: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceChatSession:
        sid = session_id or str(uuid.uuid4())[:12]
        session = VoiceChatSession(
            session_id=sid,
            language=language or self.config.default_language,
            tts_provider=self.config.default_tts_provider,
            metadata=metadata or {},
        )
        self._sessions[sid] = session
        return session

    def get_session(self, session_id: str, **kw) -> Optional[VoiceChatSession]:
        return self._sessions.get(session_id)

    def close_session(self, session_id: str, **kw) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def list_sessions(self, **kw) -> List[VoiceChatSession]:
        return list(self._sessions.values())

    # ── TTS ───────────────────────────────────────────────────

    def speak_sync(self, text: str, provider: Optional[str] = None, **kw) -> TTSResult:
        """Synthesize speech synchronously."""
        tts_provider = self.config.default_tts_provider
        if provider:
            try:
                tts_provider = TTSProvider(provider)
            except ValueError:
                return TTSResult(
                    success=False,
                    error=f"unsupported provider: {provider}",
                    provider=self.config.default_tts_provider,
                    text_length=len(text),
                )

        # Validate input
        if not text or not text.strip():
            return TTSResult(
                success=False,
                error="empty text",
                provider=self.config.default_tts_provider,
                language=self.config.default_language,
                text_length=len(text),
            )

        # Truncate
        if len(text) > self.config.max_text_length:
            text = text[: self.config.max_text_length]

        # Unsupported provider
        if tts_provider and tts_provider not in (TTSProvider.EDGE_TTS, TTSProvider.GTTS, TTSProvider.PYTTSX3, TTSProvider.OPENAI):
            return TTSResult(
                success=False,
                error=f"unsupported provider: {provider}",
                provider=tts_provider,
                text_length=len(text),
            )

        # Check cache
        if self.config.cache_enabled:
            cache_key = self._cache_key(text, tts_provider, self.config.default_language, "")
            if cache_key in self._tts_cache:
                return self._tts_cache[cache_key]

        # Stub: return empty audio
        result = TTSResult(
            audio_bytes=b"",
            audio_format=self.config.default_audio_format,
            text_length=len(text),
            provider=tts_provider,
            language=self.config.default_language,
            success=True,
        )

        if self.config.cache_enabled:
            cache_key = self._cache_key(text, tts_provider, self.config.default_language, "")
            self._tts_cache[cache_key] = result

        return result

    # ── STT ───────────────────────────────────────────────────

    def transcribe_sync(self, audio: bytes, provider: Optional[str] = None, **kw) -> STTResult:
        """Transcribe speech to text synchronously."""
        stt_provider = self.config.default_stt_provider
        if provider:
            try:
                stt_provider = STTProvider(provider)
            except ValueError:
                return STTResult(
                    success=False,
                    error=f"unsupported provider: {provider}",
                    provider=self.config.default_stt_provider,
                )

        # Validate input
        if not audio:
            return STTResult(
                success=False,
                error="empty audio",
                provider=self.config.default_stt_provider,
            )

        if len(audio) < 100:
            return STTResult(
                success=False,
                error="audio too small",
                provider=self.config.default_stt_provider,
            )

        # Unsupported provider
        if stt_provider not in (STTProvider.WHISPER, STTProvider.WHISPER_API, STTProvider.GOOGLE, STTProvider.SPHINX):
            return STTResult(
                success=False,
                error=f"unsupported provider: {provider}",
                provider=stt_provider,
            )

        # Stub: return empty result
        return STTResult(
            text="",
            provider=stt_provider,
            success=True,
        )

    # ── Dialogue ──────────────────────────────────────────────

    def dialogue_sync(
        self,
        audio: Optional[bytes] = None,
        text: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a complete dialogue turn."""
        sid = session_id or str(uuid.uuid4())[:12]

        # Resolve audio input
        if audio is not None:
            audio = self._resolve_audio(audio)

        # No speech input
        if not audio and not text:
            return {
                "success": False,
                "error": "no speech input detected",
                "session_id": sid,
            }

        # Get or create session
        session = self.get_session(sid)
        if session is None:
            session = self.create_session(session_id=sid)

        user_text = text or ""
        if user_text:
            session.add_turn("user", user_text)

        # Stub assistant response
        session.add_turn("assistant", f"Response to: {user_text}")

        return {
            "success": True,
            "session_id": sid,
            "user_text": user_text,
            "session": session,
        }

    # ── Languages ─────────────────────────────────────────────

    def supported_languages(self, **kw) -> List[str]:
        return sorted(_EDGE_VOICES.keys())

    def get_voice_for_language(self, lang: str, provider: TTSProvider, **kw) -> str:
        if provider == TTSProvider.EDGE_TTS:
            return _EDGE_VOICES.get(lang, _EDGE_VOICES.get("en", ""))
        return ""

    def get_language_name(self, code: str, **kw) -> str:
        names = {
            "en": "English", "zh": "Chinese", "ja": "Japanese",
            "ko": "Korean", "fr": "French", "de": "German",
            "es": "Spanish", "pt": "Portuguese", "it": "Italian",
            "ru": "Russian", "ar": "Arabic", "hi": "Hindi",
            "th": "Thai", "vi": "Vietnamese", "tr": "Turkish",
            "nl": "Dutch", "pl": "Polish", "sv": "Swedish",
            "da": "Danish",
        }
        return names.get(code, code)

    # ── Providers ─────────────────────────────────────────────

    def available_tts_providers(self, **kw) -> List[TTSProvider]:
        return [TTSProvider.EDGE_TTS]  # Stub: only edge-tts

    def available_stt_providers(self, **kw) -> List[STTProvider]:
        return [STTProvider.WHISPER]  # Stub: only whisper

    def stats(self, **kw) -> Dict[str, Any]:
        return {
            "active_sessions": len(self._sessions),
            "tts_cache_entries": len(self._tts_cache),
            "tts_providers": len(self.available_tts_providers()),
            "stt_providers": len(self.available_stt_providers()),
            "supported_languages": len(self.supported_languages()),
        }

    # ── Cache ─────────────────────────────────────────────────

    def _cache_key(self, text: str, provider: TTSProvider, language: str, voice: str, **kw) -> str:
        raw = f"{text}|{provider.value}|{language}|{voice}"
        return hashlib.md5(raw.encode()).hexdigest()

    def clear_cache(self, **kw) -> int:
        count = len(self._tts_cache)
        self._tts_cache.clear()
        return count

    # ── Audio utilities ───────────────────────────────────────

    def _split_into_sentences(self, text: str, max_chunk: int = 200, **kw) -> List[str]:
        """Split text into sentence-level chunks."""
        if not text:
            return []
        if len(text) <= max_chunk:
            return [text]

        # Split on sentence boundaries
        chunks = []
        current = ""
        # Split on Chinese + English sentence endings
        parts = re.split(r'(?<=[。！？.!?])\s*', text)
        for part in parts:
            if len(current) + len(part) <= max_chunk:
                current += part
            else:
                if current:
                    chunks.append(current)
                # If a single part exceeds max_chunk, force split
                while len(part) > max_chunk:
                    chunks.append(part[:max_chunk])
                    part = part[max_chunk:]
                current = part
        if current:
            chunks.append(current)
        return chunks if chunks else [text]

    def _ensure_wav(self, audio: bytes, **kw) -> bytes:
        """Ensure audio data is in WAV format."""
        if not audio:
            return audio
        if audio[:4] == b"RIFF":
            return audio
        return _wrap_pcm_to_wav(audio)

    def _resolve_audio(self, audio: Any, **kw) -> Optional[bytes]:
        """Resolve audio from various input formats (bytes, base64, data URI, file path)."""
        if isinstance(audio, bytes):
            if not audio:
                return None
            return audio

        if isinstance(audio, str):
            # Try as file path
            if os.path.exists(audio):
                try:
                    return Path(audio).read_bytes()
                except Exception:
                    pass

            # Try as data URI
            if audio.startswith("data:"):
                try:
                    header, b64 = audio.split(",", 1)
                    return base64.b64decode(b64)
                except Exception:
                    pass

            # Try as raw base64
            try:
                return base64.b64decode(audio)
            except Exception:
                pass

        return None


# ═══════════════════════════════════════════════════════════════
# Lazy dependency check
# ═══════════════════════════════════════════════════════════════

_deps_checked: bool = False


def _lazy_check_deps():
    """Check optional dependencies. Non-fatal on missing deps."""
    global _deps_checked
    if _deps_checked:
        return
    _deps_checked = True


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_voice_chat_instance: Optional[VoiceChat] = None


def get_voice_chat() -> VoiceChat:
    global _voice_chat_instance
    if _voice_chat_instance is None:
        _voice_chat_instance = VoiceChat()
    return _voice_chat_instance


def reset_voice_chat():
    global _voice_chat_instance
    _voice_chat_instance = None

