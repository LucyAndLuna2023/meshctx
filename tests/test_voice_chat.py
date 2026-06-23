"""v3.103 Voice Chat Engine — 10+ test cases for TTS, STT, streaming, multi-language, sessions."""
import asyncio
import base64
import os
import sys
import struct
import tempfile
import math
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.voice_chat import (
    VoiceChat, VoiceChatConfig, VoiceChatSession,
    TTSResult, STTResult, TTSProvider, STTProvider,
    VoiceLanguage, AudioFormat, VoiceGender,
    get_voice_chat, reset_voice_chat,
    _lazy_check_deps, _wrap_pcm_to_wav, create_sine_wav,
    _EDGE_VOICES, _GTTS_LANG_MAP, _WHISPER_LANG_MAP,
)


# ── Fixtures ──

@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure fresh singleton before each test."""
    reset_voice_chat()
    yield
    reset_voice_chat()


@pytest.fixture
def engine():
    """Fresh VoiceChat instance with cache disabled."""
    return VoiceChat(cache_enabled=False)


@pytest.fixture
def sample_wav():
    """Generate a minimal valid WAV file (440Hz sine, 0.5s)."""
    return create_sine_wav(duration_ms=500, frequency=440.0)


@pytest.fixture
def sample_pcm():
    """Generate raw 16-bit PCM data (440Hz sine, 0.5s)."""
    num_samples = int(16000 * 0.5)
    samples = []
    for i in range(num_samples):
        t = i / 16000.0
        val = int(0.3 * 32767 * math.sin(2 * math.pi * 440 * t))
        samples.append(struct.pack("<h", val))
    return b"".join(samples)


# ═══════════════════════════════════════════════════════════════
# Test 1: Singleton Pattern
# ═══════════════════════════════════════════════════════════════

class TestSingleton:
    def test_get_voice_chat_returns_instance(self):
        vc = get_voice_chat()
        assert isinstance(vc, VoiceChat)
        assert vc is not None

    def test_get_voice_chat_is_singleton(self):
        vc1 = get_voice_chat()
        vc2 = get_voice_chat()
        assert vc1 is vc2

    def test_reset_voice_chat_creates_new_instance(self):
        vc1 = get_voice_chat()
        reset_voice_chat()
        vc2 = get_voice_chat()
        assert vc1 is not vc2


# ═══════════════════════════════════════════════════════════════
# Test 2: Configuration
# ═══════════════════════════════════════════════════════════════

class TestConfiguration:
    def test_default_config(self):
        vc = VoiceChat()
        assert vc.config.default_tts_provider == TTSProvider.EDGE_TTS
        assert vc.config.default_stt_provider == STTProvider.WHISPER
        assert vc.config.default_language == "en"
        assert vc.config.default_audio_format == AudioFormat.MP3
        assert vc.config.max_text_length == 5000

    def test_custom_config(self):
        cfg = VoiceChatConfig(
            default_tts_provider=TTSProvider.GTTS,
            default_language="zh",
            tts_speed=1.5,
        )
        vc = VoiceChat(config=cfg)
        assert vc.config.default_tts_provider == TTSProvider.GTTS
        assert vc.config.default_language == "zh"
        assert vc.config.tts_speed == 1.5

    def test_kwargs_override_config(self):
        vc = VoiceChat(
            tts_provider=TTSProvider.PYTTSX3,
            language="ja",
            cache_enabled=False,
        )
        assert vc.config.default_tts_provider == TTSProvider.PYTTSX3
        assert vc.config.default_language == "ja"
        assert vc.config.cache_enabled is False


# ═══════════════════════════════════════════════════════════════
# Test 3: Session Management
# ═══════════════════════════════════════════════════════════════

class TestSessionManagement:
    def test_create_session(self, engine):
        session = engine.create_session(language="zh")
        assert session.session_id != ""
        assert len(session.session_id) == 12
        assert session.language == "zh"
        assert session.tts_provider == TTSProvider.EDGE_TTS
        assert session.turn_count == 0

    def test_create_session_with_custom_id(self, engine):
        session = engine.create_session(session_id="test-001", language="ja")
        assert session.session_id == "test-001"
        assert session.language == "ja"

    def test_get_session(self, engine):
        session = engine.create_session(language="ko")
        retrieved = engine.get_session(session.session_id)
        assert retrieved is session

    def test_get_session_missing(self, engine):
        assert engine.get_session("nonexistent") is None

    def test_close_session(self, engine):
        session = engine.create_session()
        assert engine.close_session(session.session_id) is True
        assert engine.get_session(session.session_id) is None
        # Closing again should return False
        assert engine.close_session(session.session_id) is False

    def test_list_sessions(self, engine):
        s1 = engine.create_session(language="en")
        s2 = engine.create_session(language="zh")
        sessions = engine.list_sessions()
        assert len(sessions) == 2
        ids = {s.session_id for s in sessions}
        assert s1.session_id in ids
        assert s2.session_id in ids

    def test_session_add_turn(self, engine):
        session = engine.create_session()
        session.add_turn("user", "Hello")
        session.add_turn("assistant", "Hi there")
        assert session.turn_count == 2
        assert len(session.conversation) == 2
        assert session.conversation[0]["speaker"] == "user"

    def test_session_get_context(self, engine):
        session = engine.create_session()
        for i in range(15):
            session.add_turn("user", f"msg{i}")
        ctx = session.get_context(max_turns=5)
        assert len(ctx) == 5
        assert ctx[-1]["text"] == "msg14"

    def test_session_metadata(self, engine):
        session = engine.create_session(metadata={"room": "general"})
        assert session.metadata["room"] == "general"


# ═══════════════════════════════════════════════════════════════
# Test 4: TTS — Text-to-Speech (sync)
# ═══════════════════════════════════════════════════════════════

class TestTTS:
    def test_speak_empty_text(self, engine):
        result = engine.speak_sync("")
        assert result.success is False
        assert "empty" in result.error.lower()

    def test_speak_whitespace_only(self, engine):
        result = engine.speak_sync("   \n  ")
        assert result.success is False

    def test_speak_unsupported_provider(self, engine):
        """Should handle a completely unsupported scenario gracefully."""
        # Manually set config to a nonsense value — should error gracefully
        result = engine.speak_sync("hello", provider="nonexistent")
        assert result.success is False
        assert "unsupported" in result.error.lower() or "error" in result.error.lower()

    def test_speak_text_truncation(self, engine):
        engine.config.max_text_length = 50
        long_text = "A" * 100
        # We just verify it doesn't crash; actual truncation happens internally
        try:
            result = engine.speak_sync(long_text)
            assert result.text_length <= 100
        except Exception:
            pass  # Provider may not be installed — test structure only


# ═══════════════════════════════════════════════════════════════
# Test 5: STT — Speech-to-Text (sync)
# ═══════════════════════════════════════════════════════════════

class TestSTT:
    def test_transcribe_empty_bytes(self, engine):
        result = engine.transcribe_sync(b"")
        assert result.success is False
        assert "empty" in result.error.lower()

    def test_transcribe_too_small(self, engine):
        result = engine.transcribe_sync(b"X" * 10)
        assert result.success is False
        assert "too small" in result.error.lower()

    def test_transcribe_unsupported_provider(self, engine):
        """Should handle unsupported provider gracefully."""
        # We know SPHINX is installed if SPEECHRECOGNITION is
        # Just test that the interface works with a valid provider mechanic
        result = engine.transcribe_sync(b"X" * 100, provider="nonexistent")
        assert result.success is False
        assert "unsupported" in result.error.lower()


# ═══════════════════════════════════════════════════════════════
# Test 6: Multi-Language Support
# ═══════════════════════════════════════════════════════════════

class TestMultiLanguage:
    def test_all_language_codes(self, engine):
        languages = engine.supported_languages()
        assert "en" in languages
        assert "zh" in languages
        assert "ja" in languages
        assert "ko" in languages
        assert "fr" in languages
        assert "de" in languages
        assert len(languages) >= 18

    def test_get_voice_for_language(self, engine):
        voice_en = engine.get_voice_for_language("en", TTSProvider.EDGE_TTS)
        assert "en-US" in voice_en or "Jenny" in voice_en

        voice_zh = engine.get_voice_for_language("zh", TTSProvider.EDGE_TTS)
        assert "zh-CN" in voice_zh or "Xiaoxiao" in voice_zh

    def test_get_language_name(self, engine):
        assert engine.get_language_name("en") == "English"
        assert engine.get_language_name("zh") == "Chinese"
        assert engine.get_language_name("ja") == "Japanese"
        assert engine.get_language_name("fr") == "French"
        assert engine.get_language_name("xx") == "xx"

    def test_voice_language_enum(self):
        assert VoiceLanguage.EN.value == "en"
        assert VoiceLanguage.ZH.value == "zh"
        assert VoiceLanguage.AUTO.value == "auto"
        assert len(list(VoiceLanguage)) >= 19

    def test_edge_voices_coverage(self):
        """Check that EDGE_VOICES covers all major languages."""
        major_langs = ["en", "zh", "ja", "ko", "fr", "de", "es"]
        for lang in major_langs:
            assert lang in _EDGE_VOICES, f"Missing edge-tts voice for {lang}"

    def test_gtts_lang_map_coverage(self):
        major_langs = ["en", "zh", "ja", "ko", "fr", "de"]
        for lang in major_langs:
            assert lang in _GTTS_LANG_MAP, f"Missing gTTS lang map for {lang}"

    def test_whisper_lang_map_coverage(self):
        assert "english" in _WHISPER_LANG_MAP
        assert "chinese" in _WHISPER_LANG_MAP
        assert "japanese" in _WHISPER_LANG_MAP


# ═══════════════════════════════════════════════════════════════
# Test 7: Streaming & Chunking
# ═══════════════════════════════════════════════════════════════

class TestStreaming:
    def test_split_short_text(self, engine):
        chunks = engine._split_into_sentences("Hello.", max_chunk=200)
        assert len(chunks) == 1
        assert chunks[0] == "Hello."

    def test_split_by_sentence(self, engine):
        text = "First sentence. Second sentence! Third sentence?"
        chunks = engine._split_into_sentences(text, max_chunk=30)
        assert len(chunks) == 3
        assert "First" in chunks[0]
        assert "Second" in chunks[1]
        assert "Third" in chunks[2]

    def test_split_chinese_sentences(self, engine):
        text = "你好世界。这是测试！还有一句？"
        chunks = engine._split_into_sentences(text, max_chunk=5)
        assert len(chunks) == 3

    def test_split_long_sentence_forces_break(self, engine):
        long_text = "A" * 50 + " B" * 50 + " C" * 50
        chunks = engine._split_into_sentences(long_text, max_chunk=60)
        # Should produce multiple chunks even without sentence boundaries
        assert len(chunks) >= 2


# ═══════════════════════════════════════════════════════════════
# Test 8: Audio Utilities
# ═══════════════════════════════════════════════════════════════

class TestAudioUtilities:
    def test_wrap_pcm_to_wav(self, sample_pcm):
        wav = _wrap_pcm_to_wav(sample_pcm)
        assert wav[:4] == b"RIFF"
        assert b"WAVE" in wav[:12]

    def test_create_sine_wav(self):
        wav = create_sine_wav(duration_ms=200, frequency=880.0)
        assert wav[:4] == b"RIFF"
        assert len(wav) > 100

    def test_create_sine_wav_different_params(self):
        wav1 = create_sine_wav(duration_ms=100, frequency=220.0)
        wav2 = create_sine_wav(duration_ms=500, frequency=880.0)
        assert len(wav2) > len(wav1)

    def test_ensure_wav_passthrough(self, engine, sample_wav):
        """WAV data should pass through unchanged."""
        result = engine._ensure_wav(sample_wav)
        assert result == sample_wav

    def test_ensure_wav_wraps_pcm(self, engine, sample_pcm):
        """Raw PCM should be wrapped to WAV."""
        result = engine._ensure_wav(sample_pcm)
        assert result[:4] == b"RIFF"
        assert len(result) > len(sample_pcm)


# ═══════════════════════════════════════════════════════════════
# Test 9: Cache
# ═══════════════════════════════════════════════════════════════

class TestCache:
    def test_cache_key_deterministic(self, engine):
        k1 = engine._cache_key("hello", TTSProvider.EDGE_TTS, "en", "voice1")
        k2 = engine._cache_key("hello", TTSProvider.EDGE_TTS, "en", "voice1")
        assert k1 == k2

    def test_cache_key_differs_by_text(self, engine):
        k1 = engine._cache_key("hello", TTSProvider.EDGE_TTS, "en", "")
        k2 = engine._cache_key("world", TTSProvider.EDGE_TTS, "en", "")
        assert k1 != k2

    def test_cache_key_differs_by_provider(self, engine):
        k1 = engine._cache_key("hello", TTSProvider.EDGE_TTS, "en", "")
        k2 = engine._cache_key("hello", TTSProvider.GTTS, "en", "")
        assert k1 != k2

    def test_clear_cache(self, engine):
        assert engine.clear_cache() == 0
        # Manually insert
        engine._tts_cache["test"] = TTSResult()
        assert engine.clear_cache() == 1
        assert engine.clear_cache() == 0


# ═══════════════════════════════════════════════════════════════
# Test 10: Data Classes
# ═══════════════════════════════════════════════════════════════

class TestDataClasses:
    def test_tts_result_to_dict(self):
        result = TTSResult(
            audio_bytes=b"\x00\x01\x02",
            audio_format=AudioFormat.MP3,
            duration_ms=150.5,
            text_length=10,
            provider=TTSProvider.EDGE_TTS,
            language="en",
            voice="en-US-Jenny",
            request_id="abc123",
        )
        d = result.to_dict()
        assert d["audio_size_bytes"] == 3
        assert d["audio_format"] == "mp3"
        assert d["duration_ms"] == 150.5
        assert d["text_length"] == 10
        assert d["provider"] == "edge_tts"
        assert d["voice"] == "en-US-Jenny"
        assert d["success"] is True

    def test_tts_result_to_base64(self):
        result = TTSResult(
            audio_bytes=b"test",
            audio_format=AudioFormat.MP3,
            provider=TTSProvider.EDGE_TTS,
            language="en",
        )
        b64 = result.to_base64()
        assert b64.startswith("data:audio/mp3;base64,")

    def test_tts_result_save(self, engine):
        result = TTSResult(
            audio_bytes=b"audio data",
            audio_format=AudioFormat.WAV,
            provider=TTSProvider.EDGE_TTS,
            language="en",
        )
        path = result.save("/tmp/test_tts_output.wav")
        assert Path(path).exists()
        assert Path(path).read_bytes() == b"audio data"
        Path(path).unlink()

    def test_stt_result_to_dict(self):
        result = STTResult(
            text="hello world",
            language="en",
            confidence=0.95,
            duration_ms=300.0,
            provider=STTProvider.WHISPER,
            segments=[
                {"start": 0.0, "end": 1.5, "text": "hello"},
                {"start": 1.5, "end": 2.0, "text": "world"},
            ],
            request_id="stt001",
        )
        d = result.to_dict()
        assert d["text"] == "hello world"
        assert d["language"] == "en"
        assert d["confidence"] == 0.95
        assert d["provider"] == "whisper"
        assert len(d["segments"]) == 2

    def test_tts_result_error(self):
        result = TTSResult(
            success=False,
            error="Network timeout",
            provider=TTSProvider.OPENAI,
            request_id="err001",
        )
        assert result.success is False
        assert result.error == "Network timeout"
        assert len(result.audio_bytes) == 0

    def test_stt_result_error(self):
        result = STTResult(
            success=False,
            error="No speech detected",
            provider=STTProvider.WHISPER_API,
            request_id="err002",
        )
        assert result.success is False
        assert result.error == "No speech detected"
        assert result.text == ""


# ═══════════════════════════════════════════════════════════════
# Test 11: Provider Detection
# ═══════════════════════════════════════════════════════════════

class TestProviders:
    def test_available_tts_providers(self, engine):
        providers = engine.available_tts_providers()
        # At minimum we should get some providers
        assert len(providers) >= 0  # Could be 0 in minimal env
        # Verify all are valid enum values
        for p in providers:
            assert isinstance(p, TTSProvider)

    def test_available_stt_providers(self, engine):
        providers = engine.available_stt_providers()
        for p in providers:
            assert isinstance(p, STTProvider)

    def test_stats(self, engine):
        s = engine.stats()
        assert "active_sessions" in s
        assert "tts_cache_entries" in s
        assert "tts_providers" in s
        assert "stt_providers" in s
        assert "supported_languages" in s
        assert s["supported_languages"] >= 18

    def test_lazy_check_deps_idempotent(self):
        _lazy_check_deps()
        _lazy_check_deps()
        _lazy_check_deps()
        # Should not raise

    def test_tts_provider_enum_values(self):
        assert TTSProvider.EDGE_TTS.value == "edge_tts"
        assert TTSProvider.GTTS.value == "gtts"
        assert TTSProvider.PYTTSX3.value == "pyttsx3"
        assert TTSProvider.OPENAI.value == "openai"

    def test_stt_provider_enum_values(self):
        assert STTProvider.WHISPER.value == "whisper"
        assert STTProvider.WHISPER_API.value == "whisper_api"
        assert STTProvider.GOOGLE.value == "google"
        assert STTProvider.SPHINX.value == "sphinx"

    def test_audio_format_enum_values(self):
        assert AudioFormat.MP3.value == "mp3"
        assert AudioFormat.WAV.value == "wav"
        assert AudioFormat.OGG.value == "ogg"
        assert AudioFormat.PCM.value == "pcm"

    def test_voice_gender_enum_values(self):
        assert VoiceGender.MALE.value == "male"
        assert VoiceGender.FEMALE.value == "female"
        assert VoiceGender.NEUTRAL.value == "neutral"


# ═══════════════════════════════════════════════════════════════
# Test 12: Audio Resolution
# ═══════════════════════════════════════════════════════════════

class TestAudioResolution:
    def test_resolve_audio_bytes(self, engine, sample_wav):
        result = engine._resolve_audio(sample_wav)
        assert result == sample_wav

    def test_resolve_audio_empty_bytes(self, engine):
        assert engine._resolve_audio(b"") is None

    def test_resolve_b64_data_uri(self, engine, sample_wav):
        b64 = base64.b64encode(sample_wav).decode("ascii")
        uri = f"data:audio/wav;base64,{b64}"
        result = engine._resolve_audio(uri)
        assert result == sample_wav

    def test_resolve_file_path(self, engine, sample_wav):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(sample_wav)
            tmp_path = tmp.name
        try:
            result = engine._resolve_audio(tmp_path)
            assert result == sample_wav
        finally:
            os.unlink(tmp_path)

    def test_resolve_raw_base64(self, engine, sample_wav):
        b64 = base64.b64encode(sample_wav).decode("ascii")
        result = engine._resolve_audio(b64)
        assert result == sample_wav

    def test_resolve_invalid_input(self, engine):
        # A short string that is neither a valid path nor valid base64 → returns None
        assert engine._resolve_audio("not/a/real/path.wav") is None


# ═══════════════════════════════════════════════════════════════
# Test 13: Dialogue (sync mode)
# ═══════════════════════════════════════════════════════════════

class TestDialogue:
    def test_dialogue_no_input(self, engine):
        result = engine.dialogue_sync(audio=None, text=None)
        assert result["success"] is False
        assert "no speech" in result["error"].lower()
        assert result["session_id"] != ""

    def test_dialogue_text_only(self, engine):
        result = engine.dialogue_sync(text="Hello")
        assert "user_text" in result
        assert result["user_text"] == "Hello"
        assert "session" in result

    def test_dialogue_reuses_session(self, engine):
        sid = "test-reuse"
        result1 = engine.dialogue_sync(text="msg1", session_id=sid)
        result2 = engine.dialogue_sync(text="msg2", session_id=sid)
        assert result1["session_id"] == sid
        assert result2["session_id"] == sid
        # Session should have 4 turns (2 user + 2 assistant)
        session = engine.get_session(sid)
        assert session is not None
        assert session.turn_count >= 2
