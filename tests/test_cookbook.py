"""v3.88 Cookbook Hardware Recommender — tests"""
import os
import platform
import pytest
from src.core.cookbook import (
    CookbookRecommender,
    GPUInfo,
    CPUInfo,
    HardwareProfile,
    ModelRecommendation,
    CookbookResult,
    get_cookbook,
    reset_cookbook,
)


class TestGPUInfo:
    """GPUInfo dataclass tests"""

    def test_defaults(self):
        gpu = GPUInfo()
        assert gpu.name == ""
        assert gpu.vendor == ""
        assert gpu.vram_mb == 0
        assert gpu.count == 0
        assert gpu.cuda_support is False
        assert gpu.metal_support is False
        assert gpu.rocm_support is False

    def test_to_dict(self):
        gpu = GPUInfo(name="RTX 4090", vendor="nvidia", vram_mb=24576,
                      cuda_support=True, count=1)
        d = gpu.to_dict()
        assert d["name"] == "RTX 4090"
        assert d["vendor"] == "nvidia"
        assert d["vram_mb"] == 24576
        assert d["vram_gb"] == 24.0
        assert d["cuda_support"] is True
        assert d["count"] == 1


class TestCPUInfo:
    """CPUInfo dataclass tests"""

    def test_defaults(self):
        cpu = CPUInfo()
        assert cpu.model == ""
        assert cpu.cores_physical == 0
        assert cpu.cores_logical == 0

    def test_to_dict(self):
        cpu = CPUInfo(model="Intel i9-13900K", cores_physical=24, cores_logical=32,
                      arch="x86_64", vendor="Intel")
        d = cpu.to_dict()
        assert d["model"] == "Intel i9-13900K"
        assert d["cores_physical"] == 24
        assert d["cores_logical"] == 32
        assert d["arch"] == "x86_64"
        assert d["vendor"] == "Intel"


class TestHardwareProfile:
    """HardwareProfile dataclass tests"""

    def test_defaults(self):
        hp = HardwareProfile()
        assert hp.gpu.vram_mb == 0
        assert hp.cpu.cores_physical == 0
        assert hp.ram_total_mb == 0
        assert hp.has_gpu is False

    def test_to_dict(self):
        gpu = GPUInfo(name="A100", vendor="nvidia", vram_mb=81920, cuda_support=True, count=1)
        cpu = CPUInfo(model="AMD EPYC", cores_physical=64, cores_logical=128)
        hp = HardwareProfile(gpu=gpu, cpu=cpu, ram_total_mb=262144,
                             ram_available_mb=131072, os="Linux",
                             has_gpu=True)
        d = hp.to_dict()
        assert d["ram_total_gb"] == 256.0
        assert d["has_gpu"] is True
        assert d["gpu"]["name"] == "A100"


class TestModelRecommendation:
    """ModelRecommendation dataclass tests"""

    def test_create(self):
        rec = ModelRecommendation(
            name="llama-3-8b", family="llama", params_b=8.0,
            quant="Q4_K_M", size_gb=5.0, vram_min_mb=8192,
            ram_min_mb=16384, huggingface_id="unsloth/Llama-3.1-8B-Instruct-GGUF",
            tier="small", notes="Good all-rounder",
        )
        assert rec.name == "llama-3-8b"
        assert rec.params_b == 8.0
        assert rec.quant == "Q4_K_M"
        assert rec.size_gb == 5.0
        assert rec.tier == "small"
        assert "Good" in rec.notes


class TestCookbookRecommender:
    """Core CookbookRecommender tests"""

    # ── Hardware Detection ──────────────────────────────────

    def test_detect_hardware_returns_profile(self):
        """Detect hardware returns a valid HardwareProfile."""
        recommender = CookbookRecommender()
        profile = recommender.detect_hardware()
        assert isinstance(profile, HardwareProfile)
        assert profile.os != ""
        assert profile.cpu.cores_physical >= 1
        assert profile.cpu.cores_logical >= 1
        assert profile.ram_total_mb >= 0

    def test_detect_hardware_has_cpu_model(self):
        """CPU model should be populated."""
        recommender = CookbookRecommender()
        profile = recommender.detect_hardware()
        assert profile.cpu.model != "" or profile.cpu.arch != ""
        assert profile.cpu.arch in ("x86_64", "aarch64", "arm64", "AMD64", "i386", "i686")

    def test_detect_hardware_to_dict(self):
        """Profile.to_dict() works."""
        recommender = CookbookRecommender()
        profile = recommender.detect_hardware()
        d = profile.to_dict()
        assert "gpu" in d
        assert "cpu" in d
        assert "ram_total_gb" in d
        assert "os" in d
        assert "has_gpu" in d

    # ── Static Helpers ──────────────────────────────────────

    def test_determine_tier(self):
        assert CookbookRecommender._determine_tier(1.5) == "tiny"
        assert CookbookRecommender._determine_tier(3.0) == "tiny"
        assert CookbookRecommender._determine_tier(7.0) == "small"
        assert CookbookRecommender._determine_tier(8.0) == "small"
        assert CookbookRecommender._determine_tier(12.0) == "medium"
        assert CookbookRecommender._determine_tier(30.0) == "large"
        assert CookbookRecommender._determine_tier(70.0) == "xl"
        assert CookbookRecommender._determine_tier(111.0) == "xxl"
        assert CookbookRecommender._determine_tier(405.0) == "goliath"

    def test_estimate_size(self):
        """Estimate GGUF size for different quants."""
        # 8B model with Q4_K_M should be ~4.8 GB
        size = CookbookRecommender._estimate_size(8.0, "Q4_K_M")
        assert 4.0 <= size <= 6.0

        # FP16 baseline: 2 bytes per param = 16 GB for 8B
        size_q8 = CookbookRecommender._estimate_size(8.0, "Q8_0")
        assert 7.0 <= size_q8 <= 10.0

        # IQ4_XS should be smaller than Q4_K_M
        size_iq4 = CookbookRecommender._estimate_size(8.0, "IQ4_XS")
        size_q4 = CookbookRecommender._estimate_size(8.0, "Q4_K_M")
        assert size_iq4 < size_q4 or abs(size_iq4 - size_q4) < 0.5

    # ── Model Recommendation ────────────────────────────────

    def test_recommend_models_with_gpu_profile(self):
        """Recommend models for a mid-range GPU profile."""
        recommender = CookbookRecommender()
        gpu = GPUInfo(name="RTX 4070", vendor="nvidia", vram_mb=12288,
                      cuda_support=True, count=1)
        cpu = CPUInfo(model="Intel i7", cores_physical=8, cores_logical=16)
        profile = HardwareProfile(gpu=gpu, cpu=cpu, ram_total_mb=32768, has_gpu=True)

        recs = recommender.recommend_models(profile)
        assert isinstance(recs, list)
        assert len(recs) >= 1

        # All should fit in 12GB VRAM
        for r in recs:
            assert r.vram_min_mb <= 12288
            assert isinstance(r, ModelRecommendation)
            assert r.name != ""
            assert r.params_b > 0
            assert r.quant != ""
            assert r.huggingface_id != ""

        # Sorted by params ascending
        for i in range(len(recs) - 1):
            assert recs[i].params_b <= recs[i + 1].params_b

    def test_recommend_models_cpu_only(self):
        """Recommend models for CPU-only with 16GB RAM."""
        recommender = CookbookRecommender()
        cpu = CPUInfo(model="Intel i5", cores_physical=4, cores_logical=8)
        profile = HardwareProfile(gpu=GPUInfo(), cpu=cpu, ram_total_mb=16384, has_gpu=False)

        recs = recommender.recommend_models(profile)
        assert len(recs) >= 1

        # CPU-only: RAM is the constraint
        for r in recs:
            assert r.ram_min_mb <= 16384

    def test_recommend_models_no_results_for_tiny_ram(self):
        """With very little RAM, may get few or no recommendations."""
        recommender = CookbookRecommender()
        profile = HardwareProfile(
            gpu=GPUInfo(), cpu=CPUInfo(model="weak", cores_physical=2),
            ram_total_mb=512, has_gpu=False
        )
        recs = recommender.recommend_models(profile)
        # May be empty or very few
        assert isinstance(recs, list)
        # All should fit; if none do, that's fine too
        for r in recs:
            assert r.ram_min_mb <= 512

    def test_recommend_models_high_end_gpu(self):
        """High-end GPU gets large model recommendations."""
        recommender = CookbookRecommender()
        gpu = GPUInfo(name="RTX 4090", vendor="nvidia", vram_mb=24576,
                      cuda_support=True, count=1)
        cpu = CPUInfo(model="Intel i9", cores_physical=24, cores_logical=32)
        profile = HardwareProfile(gpu=gpu, cpu=cpu, ram_total_mb=65536, has_gpu=True)

        recs = recommender.recommend_models(profile)
        assert len(recs) >= 3
        # Should include at least some models in 8-14B range or higher
        params_values = [r.params_b for r in recs]
        assert max(params_values) >= 12.0  # at least a medium-tier model

    # ── Download Scripts ────────────────────────────────────

    def test_generate_download_scripts_all(self):
        """Generate all download scripts."""
        recommender = CookbookRecommender()
        # Create some dummy recommendations
        recs = [
            ModelRecommendation(
                name="llama-3.1-8b-instruct", family="llama", params_b=8.0,
                quant="Q4_K_M", size_gb=5.0, vram_min_mb=8192, ram_min_mb=16384,
                huggingface_id="unsloth/Llama-3.1-8B-Instruct-GGUF",
                tier="small", notes="",
            ),
            ModelRecommendation(
                name="qwen2.5-7b-instruct", family="qwen", params_b=7.6,
                quant="Q4_K_M", size_gb=4.6, vram_min_mb=6144, ram_min_mb=10240,
                huggingface_id="Qwen/Qwen2.5-7B-Instruct-GGUF",
                tier="small", notes="",
            ),
        ]

        scripts = recommender.generate_download_scripts(recs, method="all")
        assert "download_hf.sh" in scripts
        assert "download_ollama.sh" in scripts
        assert "download_llamacpp.sh" in scripts

        # HF script should reference model IDs
        assert "Llama-3.1-8B-Instruct-GGUF" in scripts["download_hf.sh"]
        assert "huggingface-cli" in scripts["download_hf.sh"]

        # Ollama script
        assert "ollama pull" in scripts["download_ollama.sh"]

        # Llama.cpp script has URLs
        assert "huggingface.co" in scripts["download_llamacpp.sh"]

    def test_generate_download_scripts_huggingface_only(self):
        """Generate only huggingface script."""
        recommender = CookbookRecommender()
        recs = [
            ModelRecommendation(
                name="qwen2.5-1.5b-instruct", family="qwen", params_b=1.5,
                quant="Q4_K_M", size_gb=1.1, vram_min_mb=1536, ram_min_mb=3072,
                huggingface_id="Qwen/Qwen2.5-1.5B-Instruct-GGUF",
                tier="tiny", notes="",
            ),
        ]

        scripts = recommender.generate_download_scripts(recs, method="huggingface")
        assert len(scripts) == 1
        assert "download_hf.sh" in scripts
        assert scripts["download_hf.sh"].startswith("#!/bin/bash")

    def test_generate_download_scripts_empty(self):
        """Empty recommendations produce valid scripts."""
        recommender = CookbookRecommender()
        scripts = recommender.generate_download_scripts([], method="all")
        assert "download_hf.sh" in scripts
        assert "download_ollama.sh" in scripts
        # Scripts should be well-formed even with no models
        for name, content in scripts.items():
            assert content.startswith("#!/bin/bash")

    # ── Quantization Advice ─────────────────────────────────

    def test_recommend_quantization_gpu(self):
        """Quantization advice for GPU profile."""
        recommender = CookbookRecommender()
        gpu = GPUInfo(name="RTX 3080", vendor="nvidia", vram_mb=10240, cuda_support=True)
        profile = HardwareProfile(gpu=gpu, cpu=CPUInfo(), ram_total_mb=32768, has_gpu=True)

        advice = recommender.recommend_quantization(profile)
        assert "format" in advice
        assert "recommended_quant" in advice
        assert "alternative_quant" in advice
        assert "notes" in advice
        assert "GGUF" in advice["format"]

    def test_recommend_quantization_cpu_only(self):
        """Quantization advice for CPU-only."""
        recommender = CookbookRecommender()
        profile = HardwareProfile(
            gpu=GPUInfo(), cpu=CPUInfo(model="Intel", cores_physical=4),
            ram_total_mb=32768, has_gpu=False
        )

        advice = recommender.recommend_quantization(profile)
        assert "recommended_quant" in advice
        assert "llama.cpp" in advice["notes"].lower() or "GGUF" in advice["format"]

    def test_recommend_quantization_high_vram(self):
        """48GB+ GPU gets Q8_0 recommendation."""
        recommender = CookbookRecommender()
        gpu = GPUInfo(name="A100", vendor="nvidia", vram_mb=81920, cuda_support=True)
        profile = HardwareProfile(gpu=gpu, cpu=CPUInfo(), ram_total_mb=262144, has_gpu=True)

        advice = recommender.recommend_quantization(profile)
        assert advice["recommended_quant"] == "Q8_0"

    def test_recommend_quantization_low_vram(self):
        """6GB GPU gets IQ4_XS recommendation."""
        recommender = CookbookRecommender()
        gpu = GPUInfo(name="RTX 2060", vendor="nvidia", vram_mb=6144, cuda_support=True)
        profile = HardwareProfile(gpu=gpu, cpu=CPUInfo(), ram_total_mb=16384, has_gpu=True)

        advice = recommender.recommend_quantization(profile)
        assert advice["recommended_quant"] in ("IQ4_XS", "Q4_K_M")

    # ── Full Pipeline ───────────────────────────────────────

    def test_recommend_full_pipeline(self):
        """Full recommend() returns CookbookResult with all fields."""
        recommender = CookbookRecommender()
        gpu = GPUInfo(name="RTX 3070", vendor="nvidia", vram_mb=8192, cuda_support=True)
        cpu = CPUInfo(model="Intel i7", cores_physical=8, cores_logical=16)
        profile = HardwareProfile(gpu=gpu, cpu=cpu, ram_total_mb=32768, has_gpu=True)

        result = recommender.recommend(profile)
        assert isinstance(result, CookbookResult)
        assert hasattr(result, "profile")
        assert hasattr(result, "recommendations")
        assert hasattr(result, "download_scripts")
        assert hasattr(result, "quantization_advice")
        assert hasattr(result, "summary")
        assert len(result.recommendations) >= 1
        assert len(result.download_scripts) >= 1
        assert "Cookbook" in result.summary or "cookbook" in result.summary.lower()

    def test_recommend_to_dict(self):
        """CookbookResult.to_dict() works."""
        recommender = CookbookRecommender()
        cpu = CPUInfo(model="Intel i5", cores_physical=4, cores_logical=8)
        profile = HardwareProfile(gpu=GPUInfo(), cpu=cpu, ram_total_mb=16384, has_gpu=False)

        result = recommender.recommend(profile)
        d = result.to_dict()
        assert "profile" in d
        assert "recommendations" in d
        assert "download_scripts" in d
        assert "quantization_advice" in d
        assert "summary" in d
        assert isinstance(d["recommendations"], list)

    def test_recommend_auto_detect(self):
        """recommend() with no profile auto-detects hardware."""
        recommender = CookbookRecommender()
        result = recommender.recommend()
        assert isinstance(result, CookbookResult)
        assert result.profile.os != ""

    # ── Edge Cases ──────────────────────────────────────────

    def test_recommend_models_unknown_gpu_name(self):
        """Works with unknown GPU (no VRAM detected)."""
        recommender = CookbookRecommender()
        # GPU detected but VRAM unknown — falls back to CPU RAM
        gpu = GPUInfo(name="Unknown GPU", vendor="unknown", vram_mb=0)
        profile = HardwareProfile(gpu=gpu, cpu=CPUInfo(model="test"),
                                  ram_total_mb=16384, has_gpu=False)

        recs = recommender.recommend_models(profile)
        assert len(recs) >= 1

    def test_recommend_models_preserves_order(self):
        """Recommendations are sorted by params ascending."""
        recommender = CookbookRecommender()
        gpu = GPUInfo(name="RTX 4090", vendor="nvidia", vram_mb=24576, cuda_support=True)
        profile = HardwareProfile(gpu=gpu, cpu=CPUInfo(), ram_total_mb=65536, has_gpu=True)

        recs = recommender.recommend_models(profile)
        params = [r.params_b for r in recs]
        assert params == sorted(params)


class TestSingleton:
    """Singleton accessor tests"""

    def test_get_cookbook_returns_instance(self):
        reset_cookbook()  # Ensure clean state
        recommender = get_cookbook()
        assert isinstance(recommender, CookbookRecommender)

    def test_get_cookbook_is_singleton(self):
        reset_cookbook()
        a = get_cookbook()
        b = get_cookbook()
        assert a is b

    def test_reset_cookbook(self):
        reset_cookbook()
        a = get_cookbook()
        reset_cookbook()
        b = get_cookbook()
        assert a is not b


class TestCookbookResult:
    """CookbookResult dataclass tests"""

    def test_defaults(self):
        result = CookbookResult()
        assert result.recommendations == []
        assert result.download_scripts == {}
        assert result.quantization_advice == {}
        assert result.summary == ""

    def test_to_dict_empty(self):
        result = CookbookResult()
        d = result.to_dict()
        assert d["recommendations"] == []
        assert d["download_scripts"] == {}
