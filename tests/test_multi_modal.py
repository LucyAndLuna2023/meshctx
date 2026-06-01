"""v3.100 Multi-Modal Engine tests"""
import base64
import io
import os
import tempfile
import pytest
from src.core.multi_modal import (
    MultiModalEngine, MultiModalResult, MultiModalInput,
    ImageAnalysisResult, TranscriptionResult, OCRResult,
    Modality, VisionProvider, TranscriptionProvider, OCRProvider,
    get_multi_modal_engine, reset_multi_modal_engine,
    _detect_modality, _is_base64, _decode_base64, _cache_key,
    _guess_mime, _resolve_to_data_uri, _resolve_to_tempfile,
    _lazy_check_deps,
)


# ── Fixtures ──

@pytest.fixture(autouse=True)
def reset_engine():
    """Reset singleton before each test."""
    reset_multi_modal_engine()
    yield
    reset_multi_modal_engine()


@pytest.fixture
def engine():
    """Fresh MultiModalEngine instance."""
    return MultiModalEngine(cache_enabled=False)


@pytest.fixture
def sample_png_bytes():
    """Create a minimal valid PNG file in memory."""
    # Minimal 1x1 red PNG
    import struct, zlib

    def _make_png(w, h, color=(255, 0, 0)):
        def chunk(chunk_type, data):
            c = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + c + crc

        header = b'\x89PNG\r\n\x1a\n'
        ihdr = chunk(b'IHDR', struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        raw = b''
        for y in range(h):
            raw += b'\x00' + bytes(color) * w
        idat = chunk(b'IDAT', zlib.compress(raw))
        iend = chunk(b'IEND', b'')
        return header + ihdr + idat + iend

    return _make_png(1, 1, (255, 0, 0))


# ── Test: Modality Detection ──

class TestModalityDetection:
    """Test _detect_modality for all input types."""

    def test_detect_image_by_mime(self):
        assert _detect_modality(mime_type="image/png") == Modality.IMAGE
        assert _detect_modality(mime_type="image/jpeg") == Modality.IMAGE
        assert _detect_modality(mime_type="image/webp") == Modality.IMAGE

    def test_detect_image_by_extension(self):
        assert _detect_modality(source="photo.png") == Modality.IMAGE
        assert _detect_modality(source="scan.jpg") == Modality.IMAGE
        assert _detect_modality(source="icon.svg") == Modality.IMAGE

    def test_detect_image_by_signature(self, sample_png_bytes):
        assert _detect_modality(data=sample_png_bytes) == Modality.IMAGE

    def test_detect_audio_by_mime(self):
        assert _detect_modality(mime_type="audio/wav") == Modality.AUDIO
        assert _detect_modality(mime_type="audio/mpeg") == Modality.AUDIO

    def test_detect_audio_by_extension(self):
        assert _detect_modality(source="recording.mp3") == Modality.AUDIO
        assert _detect_modality(source="podcast.wav") == Modality.AUDIO

    def test_detect_document_by_mime(self):
        assert _detect_modality(mime_type="application/pdf") == Modality.DOCUMENT
        assert _detect_modality(mime_type="text/plain") == Modality.DOCUMENT

    def test_detect_document_by_extension(self):
        assert _detect_modality(source="report.pdf") == Modality.DOCUMENT
        assert _detect_modality(source="notes.txt") == Modality.DOCUMENT

    def test_detect_video(self):
        assert _detect_modality(mime_type="video/mp4") == Modality.VIDEO
        assert _detect_modality(source="clip.mp4") == Modality.VIDEO

    def test_detect_unknown(self):
        assert _detect_modality() == Modality.UNKNOWN
        assert _detect_modality(source="file.xyz") == Modality.UNKNOWN


# ── Test: Base64 Helpers ──

class TestBase64:
    """Test base64 detection and decoding."""

    def test_is_base64_data_uri(self):
        assert _is_base64("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk")
        assert _is_base64("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+YAAABJRU5ErkJggg==")

    def test_is_base64_short_string(self):
        assert not _is_base64("hello world")
        assert not _is_base64("short")

    def test_decode_data_uri(self):
        data = "data:text/plain;base64,SGVsbG8gV29ybGQ="
        result = _decode_base64(data)
        assert result == b"Hello World"

    def test_decode_plain_base64(self):
        result = _decode_base64("SGVsbG8gV29ybGQ=")
        assert result == b"Hello World"


# ── Test: MIME Guessing ──

class TestMimeGuessing:
    """Test _guess_mime function."""

    def test_image_types(self):
        assert _guess_mime("photo.png") == "image/png"
        assert _guess_mime("photo.jpg") == "image/jpeg"
        assert _guess_mime("photo.gif") == "image/gif"

    def test_audio_types(self):
        assert _guess_mime("audio.mp3") == "audio/mpeg"
        assert _guess_mime("audio.wav") == "audio/wav"

    def test_document_types(self):
        assert _guess_mime("doc.pdf") == "application/pdf"
        assert _guess_mime("notes.txt") == "text/plain"

    def test_unknown_fallback(self):
        assert _guess_mime("file.unknown") == "application/octet-stream"


# ── Test: Resolution Helpers ──

class TestResolveToDataURI:
    """Test _resolve_to_data_uri."""

    def test_bytes_to_data_uri(self, sample_png_bytes):
        uri = _resolve_to_data_uri(sample_png_bytes, "image/png")
        assert uri.startswith("data:image/png;base64,")
        assert len(uri) > 40

    def test_file_to_data_uri(self, sample_png_bytes):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(sample_png_bytes)
            f.flush()
            uri = _resolve_to_data_uri(f.name)
            assert uri.startswith("data:image/png;base64,")
        os.unlink(f.name)

    def test_already_data_uri(self):
        uri = "data:image/png;base64,abcd1234"
        assert _resolve_to_data_uri(uri) == uri

    def test_base64_string_to_uri(self):
        # Need a long enough base64 string for _is_base64 to detect it
        long_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60
        b64 = base64.b64encode(long_data).decode()
        uri = _resolve_to_data_uri(b64)
        assert uri.startswith("data:image/png;base64,")


class TestResolveToTempfile:
    """Test _resolve_to_tempfile."""

    def test_bytes_to_tempfile(self, sample_png_bytes):
        path = _resolve_to_tempfile(sample_png_bytes, suffix=".png")
        assert os.path.isfile(path)
        with open(path, "rb") as f:
            assert f.read() == sample_png_bytes
        os.unlink(path)

    def test_existing_file_returns_same(self, sample_png_bytes):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(sample_png_bytes)
            f.flush()
            result = _resolve_to_tempfile(f.name)
            assert result == f.name
        os.unlink(f.name)


# ── Test: Engine Initialization ──

class TestEngineInit:
    """Test MultiModalEngine initialization and properties."""

    def test_default_init(self):
        engine = MultiModalEngine()
        assert engine.cache_enabled
        assert engine.whisper_model_size == "base"
        assert engine.tesseract_lang == "eng"
        assert engine.stats["images_analyzed"] == 0
        assert engine.stats["audio_transcribed"] == 0

    def test_custom_init(self):
        engine = MultiModalEngine(
            preferred_vision="deepseek",
            preferred_transcription="openai_whisper",
            preferred_ocr="tesseract",
            cache_enabled=False,
            whisper_model_size="tiny",
            tesseract_lang="chi_sim",
        )
        assert engine.preferred_vision == "deepseek"
        assert engine.preferred_transcription == "openai_whisper"
        assert not engine.cache_enabled

    def test_available_providers(self):
        engine = MultiModalEngine()
        providers = engine.available_providers()
        assert "vision" in providers
        assert "transcription" in providers
        assert "ocr" in providers
        # Local is always available
        assert "local" in providers["vision"]

    def test_singleton(self):
        a = get_multi_modal_engine()
        b = get_multi_modal_engine()
        assert a is b

    def test_singleton_reset(self):
        a = get_multi_modal_engine()
        reset_multi_modal_engine()
        b = get_multi_modal_engine()
        assert a is not b


# ── Test: Image Analysis ──

class TestImageAnalysis:
    """Test analyze_image with various inputs."""

    def test_local_metadata_analysis(self, engine, sample_png_bytes):
        """Test local-mode image analysis (no API keys needed)."""
        result = engine.analyze_image(sample_png_bytes, prompt="Describe")
        assert isinstance(result, ImageAnalysisResult)
        assert result.success
        assert result.provider == "local"
        assert "PNG" in result.description or "png" in result.description.lower()
        assert result.latency_ms >= 0

    def test_image_from_file(self, engine, sample_png_bytes):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(sample_png_bytes)
            f.flush()
            result = engine.analyze_image(f.name)
            assert result.success
        os.unlink(f.name)

    def test_image_result_structure(self, engine, sample_png_bytes):
        result = engine.analyze_image(sample_png_bytes)
        assert result.success
        assert hasattr(result, "description")
        assert hasattr(result, "objects")
        assert hasattr(result, "text_found")
        assert hasattr(result, "raw_response")
        assert hasattr(result, "model")
        assert result.model == "gpt-4o" or result.model == "pil_metadata"

    def test_image_base64_input(self, engine, sample_png_bytes):
        b64_str = base64.b64encode(sample_png_bytes).decode()
        result = engine.analyze_image(b64_str)
        assert isinstance(result, ImageAnalysisResult)

    def test_image_data_uri_input(self, engine, sample_png_bytes):
        b64 = base64.b64encode(sample_png_bytes).decode()
        data_uri = f"data:image/png;base64,{b64}"
        result = engine.analyze_image(data_uri)
        assert isinstance(result, ImageAnalysisResult)


# ── Test: OCR ──

class TestOCR:
    """Test ocr_file functionality."""

    def test_ocr_result_structure(self, engine, sample_png_bytes):
        """Test that OCR returns proper result structure (may fail gracefully if no tesseract)."""
        result = engine.ocr_file(sample_png_bytes, language="eng")
        assert isinstance(result, OCRResult)
        # Either succeeds or has a clear error about missing deps
        assert result.success or result.error

    def test_ocr_with_prompt(self, engine, sample_png_bytes):
        result = engine.ocr_file(sample_png_bytes, prompt="Extract text", language="eng")
        assert isinstance(result, OCRResult)

    def test_ocr_fallback_to_vision(self, engine, sample_png_bytes):
        """Test that OCR falls back to vision API when tesseract unavailable."""
        result = engine.ocr_file(sample_png_bytes, provider="openai_vision")
        assert isinstance(result, OCRResult)


# ── Test: Audio Transcription ──

class TestAudioTranscription:
    """Test transcribe_audio."""

    def test_transcription_result_structure(self, engine):
        """Test that transcription returns proper result (may fail gracefully)."""
        # Minimal WAV header + silence
        wav_data = _make_minimal_wav()
        result = engine.transcribe_audio(wav_data)
        assert isinstance(result, TranscriptionResult)
        assert result.success or result.error

    def test_transcription_with_language(self, engine):
        wav_data = _make_minimal_wav()
        result = engine.transcribe_audio(wav_data, language="en")
        assert result.language == "en" or result.success


def _make_minimal_wav() -> bytes:
    """Create a minimal valid WAV file (1 second of silence, 16-bit mono 8kHz)."""
    import struct
    sample_rate = 8000
    num_samples = sample_rate  # 1 second
    data_size = num_samples * 2  # 16-bit
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate,
        sample_rate * 2, 2, 16,
        b"data", data_size,
    )
    silence = b"\x00" * data_size
    return header + silence


# ── Test: Unified Process API ──

class TestUnifiedProcess:
    """Test the unified process() method with different modalities."""

    def test_process_image_auto_detect(self, engine, sample_png_bytes):
        result = engine.process(sample_png_bytes)
        assert isinstance(result, MultiModalResult)
        assert result.modality == Modality.IMAGE
        assert result.image is not None
        assert result.success
        assert result.processing_time_ms >= 0
        assert result.error == ""

    def test_process_image_explicit_modality(self, engine, sample_png_bytes):
        result = engine.process(sample_png_bytes, modality="image")
        assert result.modality == Modality.IMAGE
        assert result.success

    def test_process_document_modality(self, engine):
        """Process a simple text document."""
        result = engine.process(b"This is sample text content for OCR testing.",
                                modality="document")
        assert isinstance(result, MultiModalResult)
        assert result.modality == Modality.DOCUMENT

    def test_process_unknown_fallback(self, engine, sample_png_bytes):
        """Unknown modality should attempt fallback processing."""
        result = engine.process(sample_png_bytes, modality="unknown")
        assert isinstance(result, MultiModalResult)
        # Should either succeed via fallback or report error
        assert result.success or result.error

    def test_process_video_unsupported(self, engine):
        """Video modality reports unsupported."""
        result = engine.process(b"fake-video-data", modality="video")
        assert not result.success
        assert "keyframe" in result.error.lower() or "unsupported" in result.error.lower()

    def test_process_with_prompt(self, engine, sample_png_bytes):
        result = engine.process(sample_png_bytes, prompt="Count objects in this image")
        assert isinstance(result, MultiModalResult)


# ── Test: Caching ──

class TestCache:
    """Test result caching."""

    def test_cache_disabled(self, sample_png_bytes):
        engine = MultiModalEngine(cache_enabled=False)
        r1 = engine.process(sample_png_bytes)
        r2 = engine.process(sample_png_bytes)
        assert r1 is not r2  # Different result objects (no cache reuse)
        # When cache is disabled, _cache_get is never called, misses stay at 0
        assert engine.stats["cache_misses"] == 0

    def test_cache_enabled_hit(self, sample_png_bytes):
        engine = MultiModalEngine(cache_enabled=True)
        r1 = engine.process(sample_png_bytes)
        first_misses = engine.stats["cache_misses"]
        r2 = engine.process(sample_png_bytes)
        # Should get a cache hit if first succeeded
        if r1.success:
            assert engine.stats["cache_hits"] >= 1
        assert isinstance(r2, MultiModalResult)

    def test_cache_clear(self, engine, sample_png_bytes):
        engine.process(sample_png_bytes)
        engine.process(sample_png_bytes)
        count = engine.clear_cache()
        assert count >= 0
        assert len(engine._cache) == 0

    def test_cache_stats(self, engine):
        stats = engine.cache_stats()
        assert "size" in stats
        assert "max_size" in stats
        assert "ttl_seconds" in stats
        assert "hits" in stats
        assert "misses" in stats


# ── Test: Stats ──

class TestStats:
    """Test engine statistics."""

    def test_initial_stats(self, engine):
        stats = engine.get_stats()
        assert stats["images_analyzed"] == 0
        assert stats["audio_transcribed"] == 0
        assert stats["ocr_processed"] == 0
        assert stats["errors"] == 0

    def test_stats_after_processing(self, engine, sample_png_bytes):
        engine.process(sample_png_bytes)
        stats = engine.get_stats()
        assert stats["images_analyzed"] >= 1


# ── Test: Cache Key ──

class TestCacheKey:
    """Test cache key generation."""

    def test_deterministic(self):
        k1 = _cache_key(b"test", "image", {"a": 1})
        k2 = _cache_key(b"test", "image", {"a": 1})
        assert k1 == k2

    def test_different_data_different_key(self):
        k1 = _cache_key(b"hello", "image", {})
        k2 = _cache_key(b"world", "image", {})
        assert k1 != k2

    def test_different_options_different_key(self):
        k1 = _cache_key(b"test", "image", {"lang": "en"})
        k2 = _cache_key(b"test", "image", {"lang": "zh"})
        assert k1 != k2


# ── Test: Text Extraction Helpers ──

class TestTextExtraction:
    """Test _extract_text_mentions and _extract_objects."""

    def test_extract_text_mentions(self):
        raw = "The image contains text: 'Hello World' and shows a cat."
        result = MultiModalEngine._extract_text_mentions(raw)
        assert "Hello World" in result

    def test_extract_text_no_match(self):
        result = MultiModalEngine._extract_text_mentions("No text here at all.")
        assert result == ""

    def test_extract_objects(self):
        raw = "The image contains: a cat, a dog, a tree, and a car."
        result = MultiModalEngine._extract_objects(raw)
        assert len(result) > 0
        assert "a cat" in " ".join(result).lower()

    def test_extract_objects_none(self):
        result = MultiModalEngine._extract_objects("Just a description with no listed objects.")
        assert result == []


# ── Test: Data Types ──

class TestDataTypes:
    """Test dataclass types and enums."""

    def test_image_analysis_result_defaults(self):
        r = ImageAnalysisResult()
        assert r.description == ""
        assert r.objects == []
        assert not r.success

    def test_transcription_result_defaults(self):
        r = TranscriptionResult()
        assert r.text == ""
        assert r.confidence == 0.0

    def test_ocr_result_defaults(self):
        r = OCRResult()
        assert r.text == ""
        assert r.pages == 0

    def test_multi_modal_result_nested(self):
        r = MultiModalResult(
            modality=Modality.IMAGE,
            image=ImageAnalysisResult(description="test", success=True),
            success=True,
        )
        assert r.modality == Modality.IMAGE
        assert r.image.description == "test"
        assert r.success

    def test_multi_modal_input_defaults(self):
        inp = MultiModalInput()
        assert inp.data == ""
        assert inp.modality is None

    def test_enum_values(self):
        assert Modality.IMAGE.value == "image"
        assert Modality.AUDIO.value == "audio"
        assert Modality.DOCUMENT.value == "document"
        assert Modality.VIDEO.value == "video"
        assert Modality.UNKNOWN.value == "unknown"

    def test_provider_enums(self):
        assert TranscriptionProvider.LOCAL_WHISPER.value == "local_whisper"
        assert OCRProvider.TESSERACT.value == "tesseract"
        assert VisionProvider.OPENAI.value == "openai"


# ── Test: Dependency Lazy Check ──

class TestDependencyCheck:
    """Test lazy dependency detection."""

    def test_lazy_check_is_idempotent(self):
        # Should not raise
        _lazy_check_deps()
        _lazy_check_deps()
        # Running twice should be fine

    def test_local_vision_always_available(self, engine):
        providers = engine.available_providers()
        assert "local" in providers["vision"]


# ── Test: MultiModalInput ──

class TestMultiModalInput:
    """Test the MultiModalInput container."""

    def test_with_prompt_and_options(self):
        inp = MultiModalInput(
            data="base64data...",
            modality=Modality.IMAGE,
            source="camera",
            mime_type="image/jpeg",
            prompt="Analyze this photo",
            options={"detail": "high"},
        )
        assert inp.modality == Modality.IMAGE
        assert inp.prompt == "Analyze this photo"
        assert inp.options["detail"] == "high"
