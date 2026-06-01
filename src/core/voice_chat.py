"""
meshctx v3.103 — Voice Chat Engine (语音对话引擎)

Features:
  1) TTS (Text-to-Speech) — text → speech audio via multiple providers
  2) STT (Speech-to-Text) — audio → text transcription via multiple providers
  3) Streaming Dialogue — real-time chunked TTS + incremental STT
  4) Multi-Language — 20+ languages with auto-detection

Architecture:
  - Provider abstraction: local (edge-tts/gTTS/pyttsx3/whisper) + cloud (OpenAI)
  - Lazy dependency loading: graceful degradation when deps missing
  - Async-first design with sync convenience wrappers
  - Session-based conversation context tracking
  - Streaming iterator pattern for chunked audio generation
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import os
import struct
import tempfile
import threading
import time
import uuid
import wave
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Generator, List, Optional, Tuple, Union

logger = logging.getLogger("meshctx.voice_chat")

# ═══════════════════════════════════════════════════════════════
# Optional dependency flags (lazy detection)
# ═══════════════════════════════════════════════════════════════

_HAS_EDGE_TTS = False
_HAS_GTTS = False
_HAS_PYTTSX3 = False
_HAS_WHISPER = False
_HAS_SPEECHRECOGNITION = False
_HAS_OPENAI = False
_HAS_PYAUDIO = False
_HAS_NUMPY = False
_CHECKS_DONE = False


def _lazy_check_deps() -> None:
    """One-time lazy check of all optional dependencies."""
    global _HAS_EDGE_TTS, _HAS_GTTS, _HAS_PYTTSX3
    global _HAS_WHISPER, _HAS_SPEECHRECOGNITION, _HAS_OPENAI
    global _HAS_PYAUDIO, _HAS_NUMPY, _CHECKS_DONE
    if _CHECKS_DONE:
        return
    _CHECKS_DONE = True

    try:
        import edge_tts  # noqa: F401
        _HAS_EDGE_TTS = True
    except ImportError:
        logger.debug("edge-tts not installed — Microsoft Edge TTS unavailable")

    try:
        from gtts import gTTS  # noqa: F401
        _HAS_GTTS = True
    except ImportError:
        logger.debug("gTTS not installed — Google TTS unavailable")

    try:
        import pyttsx3  # noqa: F401
        _HAS_PYTTSX3 = True
    except ImportError:
        logger.debug("pyttsx3 not installed — offline TTS unavailable")

    try:
        import whisper  # noqa: F401
        _HAS_WHISPER = True
    except ImportError:
        logger.debug("openai-whisper not installed — local STT unavailable")

    try:
        import speech_recognition  # noqa: F401
        _HAS_SPEECHRECOGNITION = True
    except ImportError:
        logger.debug("SpeechRecognition not installed — Google STT unavailable")

    try:
        import openai  # noqa: F401
        _HAS_OPENAI = True
    except ImportError:
        logger.debug("openai not installed — cloud TTS/STT unavailable")

    try:
        import pyaudio  # noqa: F401
        _HAS_PYAUDIO = True
    except ImportError:
        logger.debug("pyaudio not installed — microphone capture unavailable")

    try:
        import numpy  # noqa: F401
        _HAS_NUMPY = True
    except ImportError:
        logger.debug("numpy not installed — audio processing limited")


# ═══════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════

class TTSProvider(str, Enum):
    """Text-to-Speech backend providers."""
    EDGE_TTS = "edge_tts"        # Microsoft Edge free TTS (best quality, 100+ voices)
    GTTS = "gtts"                # Google Translate TTS (simple, free)
    PYTTSX3 = "pyttsx3"          # Offline system TTS (no network needed)
    OPENAI = "openai"            # OpenAI TTS API (tts-1 / tts-1-hd)


class STTProvider(str, Enum):
    """Speech-to-Text backend providers."""
    WHISPER = "whisper"          # OpenAI Whisper (local, high quality)
    WHISPER_API = "whisper_api"  # OpenAI Whisper API (cloud)
    GOOGLE = "google"            # Google Speech Recognition (free, requires internet)
    SPHINX = "sphinx"            # CMU PocketSphinx (offline, English only)


class VoiceLanguage(str, Enum):
    """Supported languages for voice chat."""
    EN = "en"          # English
    ZH = "zh"          # Chinese (Mandarin)
    JA = "ja"          # Japanese
    KO = "ko"          # Korean
    FR = "fr"          # French
    DE = "de"          # German
    ES = "es"          # Spanish
    PT = "pt"          # Portuguese
    RU = "ru"          # Russian
    AR = "ar"          # Arabic
    HI = "hi"          # Hindi
    IT = "it"          # Italian
    NL = "nl"          # Dutch
    PL = "pl"          # Polish
    TR = "tr"          # Turkish
    VI = "vi"          # Vietnamese
    TH = "th"          # Thai
    SV = "sv"          # Swedish
    AUTO = "auto"      # Auto-detect


class AudioFormat(str, Enum):
    """Output audio format."""
    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    PCM = "pcm"        # Raw 16-bit PCM


class VoiceGender(str, Enum):
    """Voice gender preference."""
    MALE = "male"
    FEMALE = "female"
    NEUTRAL = "neutral"


# ═══════════════════════════════════════════════════════════════
# Language → Voice mapping helpers
# ═══════════════════════════════════════════════════════════════

# Edge-TTS voice mapping: language → (voice_name, gender)
_EDGE_VOICES: Dict[str, Tuple[str, VoiceGender]] = {
    "en": ("en-US-JennyMultilingualNeural", VoiceGender.FEMALE),
    "zh": ("zh-CN-XiaoxiaoNeural", VoiceGender.FEMALE),
    "ja": ("ja-JP-NanamiNeural", VoiceGender.FEMALE),
    "ko": ("ko-KR-SunHiNeural", VoiceGender.FEMALE),
    "fr": ("fr-FR-DeniseNeural", VoiceGender.FEMALE),
    "de": ("de-DE-KatjaNeural", VoiceGender.FEMALE),
    "es": ("es-ES-ElviraNeural", VoiceGender.FEMALE),
    "pt": ("pt-BR-FranciscaNeural", VoiceGender.FEMALE),
    "ru": ("ru-RU-SvetlanaNeural", VoiceGender.FEMALE),
    "ar": ("ar-SA-ZariyahNeural", VoiceGender.FEMALE),
    "hi": ("hi-IN-SwaraNeural", VoiceGender.FEMALE),
    "it": ("it-IT-ElsaNeural", VoiceGender.FEMALE),
    "nl": ("nl-NL-FennaNeural", VoiceGender.FEMALE),
    "pl": ("pl-PL-ZofiaNeural", VoiceGender.FEMALE),
    "tr": ("tr-TR-EmelNeural", VoiceGender.FEMALE),
    "vi": ("vi-VN-HoaiMyNeural", VoiceGender.FEMALE),
    "th": ("th-TH-PremwadeeNeural", VoiceGender.FEMALE),
    "sv": ("sv-SE-SofieNeural", VoiceGender.FEMALE),
}

# gTTS language code mapping (gTTS uses IETF BCP-47 tags differently)
_GTTS_LANG_MAP: Dict[str, str] = {
    "en": "en",
    "zh": "zh-CN",
    "ja": "ja",
    "ko": "ko",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "pt": "pt",
    "ru": "ru",
    "ar": "ar",
    "hi": "hi",
    "it": "it",
    "nl": "nl",
    "pl": "pl",
    "tr": "tr",
    "vi": "vi",
    "th": "th",
    "sv": "sv",
}

# Whisper language detection mapping
_WHISPER_LANG_MAP: Dict[str, str] = {
    "english": "en", "chinese": "zh", "japanese": "ja",
    "korean": "ko", "french": "fr", "german": "de",
    "spanish": "es", "portuguese": "pt", "russian": "ru",
    "arabic": "ar", "hindi": "hi", "italian": "it",
    "dutch": "nl", "polish": "pl", "turkish": "tr",
    "vietnamese": "vi", "thai": "th", "swedish": "sv",
}


# ═══════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════

@dataclass
class TTSResult:
    """Result of a text-to-speech conversion."""
    audio_bytes: bytes = b""
    audio_format: AudioFormat = AudioFormat.MP3
    duration_ms: float = 0.0
    text_length: int = 0
    provider: TTSProvider = TTSProvider.EDGE_TTS
    language: str = "en"
    voice: str = ""
    success: bool = True
    error: str = ""
    request_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audio_size_bytes": len(self.audio_bytes),
            "audio_format": self.audio_format.value,
            "duration_ms": round(self.duration_ms, 1),
            "text_length": self.text_length,
            "provider": self.provider.value,
            "language": self.language,
            "voice": self.voice,
            "success": self.success,
            "error": self.error,
            "request_id": self.request_id,
        }

    def to_base64(self) -> str:
        """Return audio as base64 data URI."""
        mime = f"audio/{self.audio_format.value}"
        b64 = base64.b64encode(self.audio_bytes).decode("ascii")
        return f"data:{mime};base64,{b64}"

    def save(self, path: Union[str, Path]) -> str:
        """Save audio to file. Returns absolute path."""
        p = Path(path)
        p.write_bytes(self.audio_bytes)
        return str(p.resolve())


@dataclass
class STTResult:
    """Result of a speech-to-text transcription."""
    text: str = ""
    language: str = "en"
    confidence: float = 0.0
    duration_ms: float = 0.0
    provider: STTProvider = STTProvider.WHISPER
    segments: List[Dict[str, Any]] = field(default_factory=list)
    success: bool = True
    error: str = ""
    request_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "confidence": round(self.confidence, 3),
            "duration_ms": round(self.duration_ms, 1),
            "provider": self.provider.value,
            "segments": self.segments,
            "success": self.success,
            "error": self.error,
            "request_id": self.request_id,
        }


@dataclass
class VoiceChatSession:
    """A streaming voice conversation session."""
    session_id: str = ""
    language: str = "en"
    tts_provider: TTSProvider = TTSProvider.EDGE_TTS
    stt_provider: STTProvider = STTProvider.WHISPER
    turn_count: int = 0
    conversation: List[Dict[str, str]] = field(default_factory=list)
    created_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_turn(self, speaker: str, text: str) -> None:
        """Record a conversation turn."""
        self.turn_count += 1
        self.conversation.append({
            "turn": self.turn_count,
            "speaker": speaker,
            "text": text,
            "timestamp": time.time(),
        })

    def get_context(self, max_turns: int = 10) -> List[Dict[str, str]]:
        """Return recent conversation context."""
        return self.conversation[-max_turns:]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "language": self.language,
            "turn_count": self.turn_count,
            "conversation": self.conversation,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }


@dataclass
class VoiceChatConfig:
    """Global voice chat configuration."""
    default_tts_provider: TTSProvider = TTSProvider.EDGE_TTS
    default_stt_provider: STTProvider = STTProvider.WHISPER
    default_language: str = "en"
    default_audio_format: AudioFormat = AudioFormat.MP3
    tts_speed: float = 1.0           # 0.5–2.0
    stt_language: Optional[str] = None  # None = auto-detect
    max_text_length: int = 5000
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    whisper_model: str = "base"       # tiny/base/small/medium/large
    cache_enabled: bool = True
    cache_dir: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# Core Engine
# ═══════════════════════════════════════════════════════════════

class VoiceChat:
    """
    Voice Chat Engine — unified TTS + STT + streaming dialogue.

    Usage:
        vc = VoiceChat()
        result = await vc.speak("Hello world")
        text = await vc.transcribe(audio_bytes)
        async for chunk in vc.stream_speak("Long text..."):
            play(chunk.audio_bytes)
    """

    def __init__(
        self,
        config: Optional[VoiceChatConfig] = None,
        *,
        tts_provider: Optional[TTSProvider] = None,
        stt_provider: Optional[STTProvider] = None,
        language: Optional[str] = None,
        cache_enabled: bool = True,
        cache_dir: Optional[str] = None,
    ):
        _lazy_check_deps()
        self.config = config or VoiceChatConfig()
        if tts_provider:
            self.config.default_tts_provider = tts_provider
        if stt_provider:
            self.config.default_stt_provider = stt_provider
        if language:
            self.config.default_language = language
        self.config.cache_enabled = cache_enabled
        if cache_dir:
            self.config.cache_dir = cache_dir

        # Session registry
        self._sessions: Dict[str, VoiceChatSession] = {}
        self._sessions_lock = threading.Lock()

        # TTS cache: (text_hash, provider, lang, voice) → TTSResult
        self._tts_cache: Dict[str, TTSResult] = {}
        self._cache_lock = threading.Lock()

        # Provider runtime state
        self._whisper_model = None  # Lazy-loaded whisper model

    # ── Session Management ────────────────────────────────────

    def create_session(
        self,
        language: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> VoiceChatSession:
        """Create a new voice chat session."""
        sid = session_id or str(uuid.uuid4())[:12]
        session = VoiceChatSession(
            session_id=sid,
            language=language or self.config.default_language,
            tts_provider=self.config.default_tts_provider,
            stt_provider=self.config.default_stt_provider,
            created_at=time.time(),
            metadata=metadata or {},
        )
        with self._sessions_lock:
            self._sessions[sid] = session
        logger.info(f"VoiceChat session created: {sid} (lang={session.language})")
        return session

    def get_session(self, session_id: str) -> Optional[VoiceChatSession]:
        """Retrieve a session by ID."""
        with self._sessions_lock:
            return self._sessions.get(session_id)

    def close_session(self, session_id: str) -> bool:
        """Close and remove a session."""
        with self._sessions_lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"VoiceChat session closed: {session_id}")
                return True
        return False

    def list_sessions(self) -> List[VoiceChatSession]:
        """List all active sessions."""
        with self._sessions_lock:
            return list(self._sessions.values())

    # ── TTS: Text-to-Speech ───────────────────────────────────

    async def speak(
        self,
        text: str,
        *,
        language: Optional[str] = None,
        provider: Optional[TTSProvider] = None,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> TTSResult:
        """
        Convert text to speech.

        Args:
            text: Text to speak.
            language: Language code (en/zh/ja/...). Default: config.default_language.
            provider: TTS provider. Default: config.default_tts_provider.
            voice: Specific voice name (provider-dependent).
            speed: Speech speed 0.5–2.0.
            session_id: Session to log the utterance into.

        Returns:
            TTSResult with audio bytes and metadata.
        """
        lang = language or self.config.default_language
        prov = provider or self.config.default_tts_provider
        spd = speed or self.config.tts_speed
        request_id = str(uuid.uuid4())[:8]

        if not text.strip():
            return TTSResult(
                audio_format=self.config.default_audio_format,
                provider=prov,
                language=lang,
                success=False,
                error="Empty text",
                request_id=request_id,
            )

        text = text[:self.config.max_text_length]

        # Check cache
        if self.config.cache_enabled:
            cached = self._tts_cache_get(text, prov, lang, voice or "")
            if cached:
                logger.debug(f"TTS cache hit: {request_id}")
                result = cached
                result.request_id = request_id
                self._record_turn(session_id, "assistant", text)
                return result

        # Dispatch to provider
        try:
            start = time.monotonic()
            if prov == TTSProvider.EDGE_TTS:
                result = await self._speak_edge_tts(text, lang, voice, spd, request_id)
            elif prov == TTSProvider.GTTS:
                result = self._speak_gtts(text, lang, request_id)
            elif prov == TTSProvider.PYTTSX3:
                result = self._speak_pyttsx3(text, lang, voice, spd, request_id)
            elif prov == TTSProvider.OPENAI:
                result = await self._speak_openai(text, lang, voice, spd, request_id)
            else:
                return TTSResult(
                    success=False,
                    error=f"Unsupported TTS provider: {prov}",
                    provider=prov,
                    language=lang,
                    request_id=request_id,
                )
            result.duration_ms = (time.monotonic() - start) * 1000
        except Exception as e:
            logger.exception(f"TTS failed: {prov} — {e}")
            return TTSResult(
                audio_format=self.config.default_audio_format,
                provider=prov,
                language=lang,
                success=False,
                error=str(e),
                request_id=request_id,
            )

        # Cache result
        if self.config.cache_enabled and result.success:
            self._tts_cache_set(text, prov, lang, voice or "", result)

        self._record_turn(session_id, "assistant", text)
        return result

    def speak_sync(
        self,
        text: str,
        *,
        language: Optional[str] = None,
        provider: Optional[TTSProvider] = None,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> TTSResult:
        """Synchronous wrapper for speak()."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.speak(
                text, language=language, provider=provider,
                voice=voice, speed=speed, session_id=session_id,
            ))
        # Running loop: create a new event loop in thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                self.speak(
                    text, language=language, provider=provider,
                    voice=voice, speed=speed, session_id=session_id,
                ),
            )
            return future.result()

    async def stream_speak(
        self,
        text: str,
        *,
        language: Optional[str] = None,
        provider: Optional[TTSProvider] = None,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        chunk_size: int = 200,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[TTSResult]:
        """
        Stream TTS: split long text into chunks and yield TTSResult per chunk.

        Useful for real-time voice output where latency matters.
        """
        sentences = self._split_into_sentences(text, chunk_size)
        for sentence in sentences:
            result = await self.speak(
                sentence,
                language=language,
                provider=provider,
                voice=voice,
                speed=speed,
                session_id=session_id,
            )
            yield result

    # ── STT: Speech-to-Text ───────────────────────────────────

    async def transcribe(
        self,
        audio: Union[bytes, str, Path],
        *,
        language: Optional[str] = None,
        provider: Optional[STTProvider] = None,
        session_id: Optional[str] = None,
    ) -> STTResult:
        """
        Transcribe audio to text.

        Args:
            audio: Audio bytes, file path, or base64 data URI.
            language: Language hint (None = auto-detect).
            provider: STT provider. Default: config.default_stt_provider.
            session_id: Session to log transcription into.

        Returns:
            STTResult with transcribed text and metadata.
        """
        prov = provider or self.config.default_stt_provider
        request_id = str(uuid.uuid4())[:8]

        # Resolve audio to bytes
        audio_bytes = self._resolve_audio(audio)
        if not audio_bytes:
            return STTResult(
                provider=prov,
                success=False,
                error="Empty or unresolvable audio input",
                request_id=request_id,
            )

        # Check if audio is valid (non-empty, minimum size)
        if len(audio_bytes) < 44:  # Smaller than WAV header
            return STTResult(
                provider=prov,
                success=False,
                error=f"Audio too small ({len(audio_bytes)} bytes)",
                request_id=request_id,
            )

        try:
            start = time.monotonic()
            if prov == STTProvider.WHISPER:
                result = self._transcribe_whisper(audio_bytes, language, request_id)
            elif prov == STTProvider.WHISPER_API:
                result = await self._transcribe_whisper_api(audio_bytes, language, request_id)
            elif prov == STTProvider.GOOGLE:
                result = self._transcribe_google(audio_bytes, language, request_id)
            elif prov == STTProvider.SPHINX:
                result = self._transcribe_sphinx(audio_bytes, language, request_id)
            else:
                return STTResult(
                    success=False,
                    error=f"Unsupported STT provider: {prov}",
                    provider=prov,
                    request_id=request_id,
                )
            result.duration_ms = (time.monotonic() - start) * 1000
        except Exception as e:
            logger.exception(f"STT failed: {prov} — {e}")
            return STTResult(
                provider=prov,
                success=False,
                error=str(e),
                request_id=request_id,
            )

        if result.success:
            self._record_turn(session_id, "user", result.text)
        return result

    def transcribe_sync(
        self,
        audio: Union[bytes, str, Path],
        *,
        language: Optional[str] = None,
        provider: Optional[STTProvider] = None,
        session_id: Optional[str] = None,
    ) -> STTResult:
        """Synchronous wrapper for transcribe()."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.transcribe(
                audio, language=language, provider=provider, session_id=session_id,
            ))
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                self.transcribe(
                    audio, language=language, provider=provider, session_id=session_id,
                ),
            )
            return future.result()

    # ── Streaming Dialogue ────────────────────────────────────

    async def dialogue(
        self,
        audio: Optional[bytes] = None,
        text: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        language: Optional[str] = None,
        tts_provider: Optional[TTSProvider] = None,
        stt_provider: Optional[STTProvider] = None,
    ) -> Dict[str, Any]:
        """
        Full dialogue turn: transcribe audio → (process text) → speak response.

        If audio is provided, transcribe first; if text is provided, use it directly.
        Returns dict with stt_text, tts_result, session info.
        """
        sid = session_id
        if not sid:
            session = self.create_session(language=language)
            sid = session.session_id
        elif not self.get_session(sid):
            session = self.create_session(language=language or self.config.default_language, session_id=sid)
        else:
            session = self.get_session(sid)

        # Step 1: Transcribe if audio provided
        user_text = text
        stt_result = None
        if audio and not text:
            stt_result = await self.transcribe(
                audio,
                language=language,
                provider=stt_provider,
                session_id=sid,
            )
            user_text = stt_result.text if stt_result.success else ""

        if not user_text:
            return {
                "session_id": sid,
                "user_text": "",
                "response_text": "",
                "tts_result": None,
                "stt_result": stt_result.to_dict() if stt_result else None,
                "success": False,
                "error": "No speech input detected",
            }

        # Record user turn
        self._record_turn(sid, "user", user_text)

        # Step 2: Generate response (placeholder — real impl would call LLM)
        response_text = self._generate_response(user_text, session)

        # Step 3: Speak response
        tts_result = await self.speak(
            response_text,
            language=session.language,
            provider=tts_provider or session.tts_provider,
            session_id=sid,
        )

        return {
            "session_id": sid,
            "user_text": user_text,
            "response_text": response_text,
            "tts_result": tts_result.to_dict(),
            "stt_result": stt_result.to_dict() if stt_result else None,
            "session": session.to_dict(),
            "success": tts_result.success,
        }

    def dialogue_sync(
        self,
        audio: Optional[bytes] = None,
        text: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
        language: Optional[str] = None,
        tts_provider: Optional[TTSProvider] = None,
        stt_provider: Optional[STTProvider] = None,
    ) -> Dict[str, Any]:
        """Synchronous wrapper for dialogue()."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.dialogue(
                audio=audio, text=text, session_id=session_id,
                language=language, tts_provider=tts_provider, stt_provider=stt_provider,
            ))
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(
                asyncio.run,
                self.dialogue(
                    audio=audio, text=text, session_id=session_id,
                    language=language, tts_provider=tts_provider,
                    stt_provider=stt_provider,
                ),
            )
            return future.result()

    # ── Utilities ─────────────────────────────────────────────

    def available_tts_providers(self) -> List[TTSProvider]:
        """Return list of available TTS providers."""
        providers: List[TTSProvider] = []
        if _HAS_EDGE_TTS:
            providers.append(TTSProvider.EDGE_TTS)
        if _HAS_GTTS:
            providers.append(TTSProvider.GTTS)
        if _HAS_PYTTSX3:
            providers.append(TTSProvider.PYTTSX3)
        if _HAS_OPENAI:
            providers.append(TTSProvider.OPENAI)
        return providers

    def available_stt_providers(self) -> List[STTProvider]:
        """Return list of available STT providers."""
        providers: List[STTProvider] = []
        if _HAS_WHISPER:
            providers.append(STTProvider.WHISPER)
        if _HAS_OPENAI:
            providers.append(STTProvider.WHISPER_API)
        if _HAS_SPEECHRECOGNITION:
            providers.append(STTProvider.GOOGLE)
            providers.append(STTProvider.SPHINX)
        return providers

    def supported_languages(self) -> List[str]:
        """Return list of supported language codes."""
        return [lang.value for lang in VoiceLanguage if lang != VoiceLanguage.AUTO]

    def get_voice_for_language(
        self, language: str, provider: TTSProvider
    ) -> str:
        """Get default voice name for a language + provider combo."""
        if provider == TTSProvider.EDGE_TTS:
            entry = _EDGE_VOICES.get(language, _EDGE_VOICES["en"])
            return entry[0]
        return ""

    def get_language_name(self, code: str) -> str:
        """Get human-readable language name."""
        names = {
            "en": "English", "zh": "Chinese", "ja": "Japanese",
            "ko": "Korean", "fr": "French", "de": "German",
            "es": "Spanish", "pt": "Portuguese", "ru": "Russian",
            "ar": "Arabic", "hi": "Hindi", "it": "Italian",
            "nl": "Dutch", "pl": "Polish", "tr": "Turkish",
            "vi": "Vietnamese", "th": "Thai", "sv": "Swedish",
        }
        return names.get(code, code)

    def clear_cache(self) -> int:
        """Clear TTS cache. Returns number of entries cleared."""
        with self._cache_lock:
            count = len(self._tts_cache)
            self._tts_cache.clear()
        logger.info(f"TTS cache cleared ({count} entries)")
        return count

    def stats(self) -> Dict[str, Any]:
        """Return engine statistics."""
        with self._sessions_lock:
            session_count = len(self._sessions)
        with self._cache_lock:
            cache_count = len(self._tts_cache)
        return {
            "active_sessions": session_count,
            "tts_cache_entries": cache_count,
            "tts_providers": [p.value for p in self.available_tts_providers()],
            "stt_providers": [p.value for p in self.available_stt_providers()],
            "supported_languages": len(self.supported_languages()),
        }

    # ── Private: TTS Providers ────────────────────────────────

    async def _speak_edge_tts(
        self, text: str, lang: str, voice: Optional[str], speed: float,
        request_id: str,
    ) -> TTSResult:
        """TTS via Microsoft Edge TTS (edge-tts library)."""
        if not _HAS_EDGE_TTS:
            raise RuntimeError("edge-tts not installed. Run: pip install edge-tts")

        import edge_tts

        voice_name = voice or self.get_voice_for_language(lang, TTSProvider.EDGE_TTS)

        # Adjust rate string for speed: "-20%" to "+50%"
        rate_pct = int((speed - 1.0) * 100)
        rate_str = f"{rate_pct:+d}%" if rate_pct else "+0%"

        communicate = edge_tts.Communicate(
            text, voice_name, rate=rate_str,
        )
        chunks: List[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])

        audio_bytes = b"".join(chunks)

        return TTSResult(
            audio_bytes=audio_bytes,
            audio_format=AudioFormat.MP3,
            text_length=len(text),
            provider=TTSProvider.EDGE_TTS,
            language=lang,
            voice=voice_name,
            request_id=request_id,
        )

    def _speak_gtts(
        self, text: str, lang: str, request_id: str,
    ) -> TTSResult:
        """TTS via Google Translate TTS (gTTS library)."""
        if not _HAS_GTTS:
            raise RuntimeError("gTTS not installed. Run: pip install gtts")

        from gtts import gTTS

        gtts_lang = _GTTS_LANG_MAP.get(lang, "en")
        tts = gTTS(text=text, lang=gtts_lang)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        audio_bytes = buf.getvalue()

        return TTSResult(
            audio_bytes=audio_bytes,
            audio_format=AudioFormat.MP3,
            text_length=len(text),
            provider=TTSProvider.GTTS,
            language=lang,
            request_id=request_id,
        )

    def _speak_pyttsx3(
        self, text: str, lang: str, voice: Optional[str], speed: float,
        request_id: str,
    ) -> TTSResult:
        """TTS via offline pyttsx3 engine."""
        if not _HAS_PYTTSX3:
            raise RuntimeError("pyttsx3 not installed. Run: pip install pyttsx3")

        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", int(engine.getProperty("rate") * speed))

        # Try to set voice matching language
        if voice:
            engine.setProperty("voice", voice)
        else:
            voices = engine.getProperty("voices")
            if voices:
                engine.setProperty("voice", voices[0].id)

        # Save to temp WAV file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            engine.save_to_file(text, tmp_path)
            engine.runAndWait()
            audio_bytes = Path(tmp_path).read_bytes()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return TTSResult(
            audio_bytes=audio_bytes,
            audio_format=AudioFormat.WAV,
            text_length=len(text),
            provider=TTSProvider.PYTTSX3,
            language=lang,
            voice=voice or "default",
            request_id=request_id,
        )

    async def _speak_openai(
        self, text: str, lang: str, voice: Optional[str], speed: float,
        request_id: str,
    ) -> TTSResult:
        """TTS via OpenAI TTS API."""
        if not _HAS_OPENAI:
            raise RuntimeError("openai not installed. Run: pip install openai")

        import openai

        client = openai.AsyncOpenAI(
            api_key=self.config.openai_api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=self.config.openai_base_url or os.environ.get("OPENAI_BASE_URL"),
        )

        resp = await client.audio.speech.create(
            model="tts-1",
            voice=(voice or "alloy"),
            input=text,
            speed=speed,
            response_format="mp3",
        )

        audio_bytes = resp.content

        return TTSResult(
            audio_bytes=audio_bytes,
            audio_format=AudioFormat.MP3,
            text_length=len(text),
            provider=TTSProvider.OPENAI,
            language=lang,
            voice=voice or "alloy",
            request_id=request_id,
        )

    # ── Private: STT Providers ────────────────────────────────

    def _transcribe_whisper(
        self, audio_bytes: bytes, language: Optional[str], request_id: str,
    ) -> STTResult:
        """STT via local OpenAI Whisper model."""
        if not _HAS_WHISPER:
            raise RuntimeError("openai-whisper not installed. Run: pip install openai-whisper")

        import whisper

        # Lazy load model
        if self._whisper_model is None:
            model_name = self.config.whisper_model
            logger.info(f"Loading Whisper model: {model_name}")
            self._whisper_model = whisper.load_model(model_name)

        # Write audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(self._ensure_wav(audio_bytes))
            tmp_path = tmp.name

        try:
            options = {}
            if language and language != "auto":
                options["language"] = language
            result = self._whisper_model.transcribe(tmp_path, **options)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        detected_lang = _WHISPER_LANG_MAP.get(
            result.get("language", ""), result.get("language", "en")
        )

        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "text": seg.get("text", "").strip(),
            })

        return STTResult(
            text=result["text"].strip(),
            language=detected_lang,
            confidence=0.85,  # Whisper doesn't expose per-request confidence easily
            provider=STTProvider.WHISPER,
            segments=segments,
            request_id=request_id,
        )

    async def _transcribe_whisper_api(
        self, audio_bytes: bytes, language: Optional[str], request_id: str,
    ) -> STTResult:
        """STT via OpenAI Whisper API."""
        if not _HAS_OPENAI:
            raise RuntimeError("openai not installed. Run: pip install openai")

        import openai

        client = openai.AsyncOpenAI(
            api_key=self.config.openai_api_key or os.environ.get("OPENAI_API_KEY"),
            base_url=self.config.openai_base_url or os.environ.get("OPENAI_BASE_URL"),
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(self._ensure_wav(audio_bytes))
            tmp_path = tmp.name

        try:
            kwargs: Dict[str, Any] = {"model": "whisper-1", "file": open(tmp_path, "rb")}
            if language and language != "auto":
                kwargs["language"] = language
            resp = await client.audio.transcriptions.create(**kwargs)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return STTResult(
            text=resp.text.strip(),
            language=resp.language if hasattr(resp, "language") else (language or "en"),
            confidence=0.9,
            provider=STTProvider.WHISPER_API,
            request_id=request_id,
        )

    def _transcribe_google(
        self, audio_bytes: bytes, language: Optional[str], request_id: str,
    ) -> STTResult:
        """STT via Google Speech Recognition."""
        if not _HAS_SPEECHRECOGNITION:
            raise RuntimeError("SpeechRecognition not installed. Run: pip install SpeechRecognition")

        import speech_recognition as sr

        recognizer = sr.Recognizer()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(self._ensure_wav(audio_bytes))
            tmp_path = tmp.name

        try:
            with sr.AudioFile(tmp_path) as source:
                audio = recognizer.record(source)
            lang_code = language if language and language != "auto" else "en-US"
            text = recognizer.recognize_google(audio, language=lang_code)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return STTResult(
            text=text,
            language=language or "en",
            confidence=getattr(recognizer, "confidence", 0.8),
            provider=STTProvider.GOOGLE,
            request_id=request_id,
        )

    def _transcribe_sphinx(
        self, audio_bytes: bytes, language: Optional[str], request_id: str,
    ) -> STTResult:
        """STT via CMU PocketSphinx (offline, English only)."""
        if not _HAS_SPEECHRECOGNITION:
            raise RuntimeError("SpeechRecognition not installed. Run: pip install SpeechRecognition")
        if language and language not in ("en", "auto"):
            return STTResult(
                provider=STTProvider.SPHINX,
                language=language,
                success=False,
                error="PocketSphinx only supports English",
                request_id=request_id,
            )

        import speech_recognition as sr

        recognizer = sr.Recognizer()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(self._ensure_wav(audio_bytes))
            tmp_path = tmp.name

        try:
            with sr.AudioFile(tmp_path) as source:
                audio = recognizer.record(source)
            text = recognizer.recognize_sphinx(audio)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        return STTResult(
            text=text,
            language="en",
            confidence=0.6,
            provider=STTProvider.SPHINX,
            request_id=request_id,
        )

    # ── Private: Helpers ──────────────────────────────────────

    def _cache_key(
        self, text: str, provider: TTSProvider, lang: str, voice: str,
    ) -> str:
        """Generate cache key for TTS result."""
        raw = f"{text}|{provider.value}|{lang}|{voice}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _tts_cache_get(
        self, text: str, provider: TTSProvider, lang: str, voice: str,
    ) -> Optional[TTSResult]:
        """Retrieve from TTS cache."""
        key = self._cache_key(text, provider, lang, voice)
        with self._cache_lock:
            return self._tts_cache.get(key)

    def _tts_cache_set(
        self, text: str, provider: TTSProvider, lang: str, voice: str,
        result: TTSResult,
    ) -> None:
        """Store in TTS cache."""
        key = self._cache_key(text, provider, lang, voice)
        with self._cache_lock:
            self._tts_cache[key] = result

    def _resolve_audio(self, audio: Union[bytes, str, Path]) -> Optional[bytes]:
        """Resolve audio input to bytes."""
        if isinstance(audio, bytes):
            return audio if len(audio) > 0 else None

        s = str(audio)

        # data URI
        if s.startswith("data:"):
            try:
                # data:audio/wav;base64,AAAA...
                header, b64_data = s.split(",", 1)
                return base64.b64decode(b64_data)
            except Exception:
                logger.warning("Failed to decode base64 audio data URI")
                return None

        # File path
        try:
            p = Path(s)
            if p.exists() and p.is_file():
                return p.read_bytes()
        except (OSError, ValueError):
            pass  # Path too long or invalid — fall through to base64

        # Try as raw base64
        try:
            return base64.b64decode(s)
        except Exception:
            pass

        return None

    def _ensure_wav(self, audio_bytes: bytes) -> bytes:
        """Ensure audio is valid WAV format — pass through if already WAV, add header if raw PCM."""
        if len(audio_bytes) >= 4 and audio_bytes[:4] == b"RIFF":
            return audio_bytes
        # Assume raw 16-bit PCM 16kHz mono — wrap in WAV header
        return _wrap_pcm_to_wav(audio_bytes)

    def _split_into_sentences(
        self, text: str, max_chunk: int = 200,
    ) -> List[str]:
        """Split text into sentence-level chunks."""
        if len(text) <= max_chunk:
            return [text]

        chunks: List[str] = []
        current = ""

        # Sentence-ending punctuation
        enders = set(".!?。！？\n")

        for char in text:
            current += char
            if char in enders and len(current) >= max_chunk // 2:
                chunks.append(current.strip())
                current = ""
            elif len(current) >= max_chunk:
                # Force split at space or comma
                split_at = max(
                    current.rfind(" "),
                    current.rfind(","),
                    current.rfind("，"),
                )
                if split_at > max_chunk // 2:
                    chunks.append(current[:split_at].strip())
                    current = current[split_at:].strip()
                else:
                    chunks.append(current.strip())
                    current = ""

        if current.strip():
            if chunks and len(current) < max_chunk // 4:
                chunks[-1] += " " + current.strip()
            else:
                chunks.append(current.strip())

        return chunks

    def _record_turn(
        self, session_id: Optional[str], speaker: str, text: str,
    ) -> None:
        """Record a conversation turn in the session."""
        if not session_id:
            return
        session = self.get_session(session_id)
        if session:
            session.add_turn(speaker, text)

    def _generate_response(
        self, user_text: str, session: VoiceChatSession,
    ) -> str:
        """
        Generate a response for the dialogue.

        This is a placeholder — in production this would call an LLM.
        """
        # Simple echo for testing; real impl hooks into LLM pipeline
        context = session.get_context(max_turns=4)
        history = " ".join(t["text"] for t in context if t["speaker"] == "user")
        return f"Echo: {user_text}" if not history else f"Reply: {user_text}"


# ═══════════════════════════════════════════════════════════════
# Audio Utilities
# ═══════════════════════════════════════════════════════════════

def _wrap_pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,  # 16-bit
) -> bytes:
    """Wrap raw PCM data into a valid WAV container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def create_sine_wav(
    duration_ms: float = 500,
    frequency: float = 440.0,  # A4 note
    sample_rate: int = 16000,
    amplitude: float = 0.3,
) -> bytes:
    """Create a simple sine wave WAV file (for testing)."""
    if not _HAS_NUMPY:
        # Fallback: generate raw PCM with struct
        num_samples = int(sample_rate * duration_ms / 1000)
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            val = int(amplitude * 32767 * __import__("math").sin(2 * __import__("math").pi * frequency * t))
            samples.append(struct.pack("<h", val))
        pcm = b"".join(samples)
        return _wrap_pcm_to_wav(pcm, sample_rate=sample_rate)

    import numpy as np

    num_samples = int(sample_rate * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, num_samples, endpoint=False)
    samples = (amplitude * 32767 * np.sin(2 * np.pi * frequency * t)).astype(np.int16)
    pcm = samples.tobytes()
    return _wrap_pcm_to_wav(pcm, sample_rate=sample_rate)


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_voice_chat: Optional[VoiceChat] = None
_voice_chat_lock = threading.Lock()


def get_voice_chat(
    *,
    tts_provider: Optional[TTSProvider] = None,
    stt_provider: Optional[STTProvider] = None,
    language: Optional[str] = None,
    cache_enabled: bool = True,
    cache_dir: Optional[str] = None,
) -> VoiceChat:
    """Get or create the singleton VoiceChat instance."""
    global _voice_chat
    if _voice_chat is None:
        with _voice_chat_lock:
            if _voice_chat is None:
                _voice_chat = VoiceChat(
                    tts_provider=tts_provider,
                    stt_provider=stt_provider,
                    language=language,
                    cache_enabled=cache_enabled,
                    cache_dir=cache_dir,
                )
    return _voice_chat


def reset_voice_chat() -> None:
    """Reset the singleton (useful for testing)."""
    global _voice_chat
    with _voice_chat_lock:
        if _voice_chat is not None:
            _voice_chat.clear_cache()
            sessions = list(_voice_chat._sessions.keys())
            for sid in sessions:
                _voice_chat.close_session(sid)
        _voice_chat = None
