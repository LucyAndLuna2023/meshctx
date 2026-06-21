"""meshctx cookbook — v3.88 hardware recommender stub"""
from __future__ import annotations
import os
import platform
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GPUInfo:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    name: str = ""
    vendor: str = ""
    vram_mb: int = 0
    count: int = 0
    cuda_support: bool = False
    metal_support: bool = False
    rocm_support: bool = False

    def to_dict(self, **kw) -> dict:
        return {
            "name": self.name,
            "vendor": self.vendor,
            "vram_mb": self.vram_mb,
            "vram_gb": round(self.vram_mb / 1024, 1) if self.vram_mb else 0.0,
            "count": self.count,
            "cuda_support": self.cuda_support,
            "metal_support": self.metal_support,
            "rocm_support": self.rocm_support,
        }


@dataclass
class CPUInfo:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    model: str = ""
    cores_physical: int = 0
    cores_logical: int = 0
    arch: str = ""
    vendor: str = ""

    def to_dict(self, **kw) -> dict:
        return {
            "model": self.model,
            "cores_physical": self.cores_physical,
            "cores_logical": self.cores_logical,
            "arch": self.arch,
            "vendor": self.vendor,
        }


@dataclass
class HardwareProfile:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    gpu: GPUInfo = field(default_factory=GPUInfo)
    cpu: CPUInfo = field(default_factory=CPUInfo)
    ram_total_mb: int = 0
    ram_available_mb: int = 0
    os: str = ""
    has_gpu: bool = False

    def to_dict(self, **kw) -> dict:
        return {
            "gpu": self.gpu.to_dict(),
            "cpu": self.cpu.to_dict(),
            "ram_total_mb": self.ram_total_mb,
            "ram_total_gb": round(self.ram_total_mb / 1024, 1),
            "ram_available_mb": self.ram_available_mb,
            "os": self.os,
            "has_gpu": self.has_gpu,
        }


@dataclass
class ModelRecommendation:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    name: str = ""
    family: str = ""
    params_b: float = 0.0
    quant: str = ""
    size_gb: float = 0.0
    vram_min_mb: int = 0
    ram_min_mb: int = 0
    huggingface_id: str = ""
    tier: str = ""
    notes: str = ""


@dataclass
class CookbookResult:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    profile: HardwareProfile | None = None
    recommendations: list[ModelRecommendation] = field(default_factory=list)
    download_scripts: dict[str, str] = field(default_factory=dict)
    quantization_advice: dict[str, str] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self, **kw) -> dict:
        return {
            "profile": self.profile.to_dict() if self.profile else {},
            "recommendations": [
                {
                    "name": r.name, "family": r.family, "params_b": r.params_b,
                    "quant": r.quant, "size_gb": r.size_gb,
                    "vram_min_mb": r.vram_min_mb, "ram_min_mb": r.ram_min_mb,
                    "huggingface_id": r.huggingface_id, "tier": r.tier, "notes": r.notes,
                }
                for r in self.recommendations
            ],
            "download_scripts": self.download_scripts,
            "quantization_advice": self.quantization_advice,
            "summary": self.summary,
        }


_MODEL_DB: list[dict[str, Any]] = [
    {"name": "qwen2.5-0.5b-instruct", "family": "qwen", "params_b": 0.5, "quant": "Q4_K_M", "size_gb": 0.5, "vram_min_mb": 1024, "ram_min_mb": 2048, "huggingface_id": "Qwen/Qwen2.5-0.5B-Instruct-GGUF", "tier": "tiny"},
    {"name": "qwen2.5-1.5b-instruct", "family": "qwen", "params_b": 1.5, "quant": "Q4_K_M", "size_gb": 1.1, "vram_min_mb": 1536, "ram_min_mb": 3072, "huggingface_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "tier": "tiny"},
    {"name": "phi-3-mini-4k", "family": "phi", "params_b": 3.8, "quant": "Q4_K_M", "size_gb": 2.3, "vram_min_mb": 3072, "ram_min_mb": 6144, "huggingface_id": "microsoft/Phi-3-mini-4k-instruct-gguf", "tier": "tiny"},
    {"name": "llama-3.2-3b-instruct", "family": "llama", "params_b": 3.2, "quant": "Q4_K_M", "size_gb": 2.0, "vram_min_mb": 3072, "ram_min_mb": 6144, "huggingface_id": "unsloth/Llama-3.2-3B-Instruct-GGUF", "tier": "tiny"},
    {"name": "qwen2.5-7b-instruct", "family": "qwen", "params_b": 7.6, "quant": "Q4_K_M", "size_gb": 4.6, "vram_min_mb": 6144, "ram_min_mb": 10240, "huggingface_id": "Qwen/Qwen2.5-7B-Instruct-GGUF", "tier": "small"},
    {"name": "llama-3.1-8b-instruct", "family": "llama", "params_b": 8.0, "quant": "Q4_K_M", "size_gb": 5.0, "vram_min_mb": 8192, "ram_min_mb": 16384, "huggingface_id": "unsloth/Llama-3.1-8B-Instruct-GGUF", "tier": "small"},
    {"name": "mistral-7b-instruct-v0.3", "family": "mistral", "params_b": 7.3, "quant": "Q4_K_M", "size_gb": 4.4, "vram_min_mb": 6144, "ram_min_mb": 10240, "huggingface_id": "TheBloke/Mistral-7B-Instruct-v0.3-GGUF", "tier": "small"},
    {"name": "yi-1.5-9b", "family": "yi", "params_b": 9.0, "quant": "Q4_K_M", "size_gb": 5.4, "vram_min_mb": 8192, "ram_min_mb": 16384, "huggingface_id": "01-ai/Yi-1.5-9B-Chat-GGUF", "tier": "small"},
    {"name": "qwen2.5-14b-instruct", "family": "qwen", "params_b": 14.7, "quant": "Q4_K_M", "size_gb": 8.8, "vram_min_mb": 12288, "ram_min_mb": 20480, "huggingface_id": "Qwen/Qwen2.5-14B-Instruct-GGUF", "tier": "medium"},
    {"name": "llama-3.1-70b-instruct", "family": "llama", "params_b": 70.6, "quant": "Q4_K_M", "size_gb": 42.0, "vram_min_mb": 49152, "ram_min_mb": 81920, "huggingface_id": "unsloth/Llama-3.1-70B-Instruct-GGUF", "tier": "xl"},
    {"name": "deepseek-r1-distill-qwen-32b", "family": "deepseek", "params_b": 32.8, "quant": "Q4_K_M", "size_gb": 19.0, "vram_min_mb": 24576, "ram_min_mb": 40960, "huggingface_id": "unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF", "tier": "large"},
    {"name": "command-r-plus", "family": "cohere", "params_b": 104.0, "quant": "Q4_K_M", "size_gb": 62.0, "vram_min_mb": 81920, "ram_min_mb": 131072, "huggingface_id": "CohereForAI/c4ai-command-r-plus-GGUF", "tier": "xxl"},
    {"name": "llama-3.1-405b-instruct", "family": "llama", "params_b": 405.0, "quant": "Q4_K_M", "size_gb": 240.0, "vram_min_mb": 262144, "ram_min_mb": 524288, "huggingface_id": "hugging-quants/Llama-3.1-405B-Instruct-GGUF", "tier": "goliath"},
]


QUANT_BYTES_PER_PARAM = {
    "IQ2_XXS": 0.35, "IQ2_XS": 0.4, "IQ3_XXS": 0.5, "IQ3_XS": 0.6,
    "IQ4_XS": 0.7, "Q4_K_M": 0.7, "Q5_K_M": 0.9, "Q6_K": 1.1,
    "Q8_0": 1.2, "FP16": 2.0, "FP32": 4.0,
}


class CookbookRecommender:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    def __init__(self, *args, **kwargs):
        pass

    def detect_hardware(self, **kw) -> HardwareProfile:
        # CPU
        cpu_model = platform.processor() or ""
        cores_physical = os.cpu_count() or 1
        cores_logical = os.cpu_count() or 1
        cpu_arch = platform.machine()
        cpu_vendor = ""
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "vendor_id" in line:
                        cpu_vendor = line.split(":")[-1].strip()
                        break
        except Exception:
            pass

        # RAM
        ram_total_mb = 0
        ram_available_mb = 0
        try:
            import shutil
            mem = shutil.disk_usage("/")
            # Actually get memory via /proc/meminfo
            with open("/proc/meminfo") as f:
                for line in f:
                    if "MemTotal" in line:
                        ram_total_mb = int(line.split()[1]) // 1024
                    elif "MemAvailable" in line:
                        ram_available_mb = int(line.split()[1]) // 1024
        except Exception:
            ram_total_mb = 8192  # fallback

        # GPU
        gpu = GPUInfo()
        has_gpu = False
        try:
            result = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(",")
                gpu.name = parts[0].strip()
                gpu.vendor = "nvidia"
                gpu.vram_mb = int(float(parts[1].strip()))
                gpu.count = 1
                gpu.cuda_support = True
                has_gpu = True
        except Exception:
            pass

        if not has_gpu:
            try:
                result = subprocess.run(["rocm-smi", "--showproductname"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    gpu.vendor = "amd"
                    gpu.rocm_support = True
                    has_gpu = True
            except Exception:
                pass

        os_name = platform.system()
        return HardwareProfile(
            gpu=gpu,
            cpu=CPUInfo(model=cpu_model, cores_physical=cores_physical, cores_logical=cores_logical,
                       arch=cpu_arch, vendor=cpu_vendor),
            ram_total_mb=ram_total_mb,
            ram_available_mb=ram_available_mb,
            os=os_name,
            has_gpu=has_gpu,
        )

    @staticmethod
    def _determine_tier(params_b: float, **kw) -> str:
        if params_b <= 3.0:
            return "tiny"
        elif params_b <= 8.0:
            return "small"
        elif params_b <= 14.0:
            return "medium"
        elif params_b <= 35.0:
            return "large"
        elif params_b <= 80.0:
            return "xl"
        elif params_b <= 200.0:
            return "xxl"
        return "goliath"

    @staticmethod
    def _estimate_size(params_b: float, quant: str, **kw) -> float:
        bpp = QUANT_BYTES_PER_PARAM.get(quant, 0.7)
        return params_b * bpp * 1.1  # 10% overhead

    def recommend_models(self, profile: HardwareProfile, **kw) -> list[ModelRecommendation]:
        recs = []
        if profile.has_gpu and profile.gpu.vram_mb > 0:
            vram_limit = profile.gpu.vram_mb - 1024  # leave 1GB buffer
            ram_limit = profile.ram_total_mb - 2048
        else:
            vram_limit = 0  # CPU-only, use RAM
            ram_limit = profile.ram_total_mb - 2048

        for m in _MODEL_DB:
            if ram_limit <= 0:
                break
            if m["ram_min_mb"] <= ram_limit:
                # For GPU profiles, also check VRAM
                if profile.has_gpu and vram_limit > 0:
                    if m["vram_min_mb"] <= vram_limit:
                        recs.append(ModelRecommendation(**m))
                else:
                    recs.append(ModelRecommendation(**m))
        recs.sort(key=lambda r: r.params_b)
        return recs

    def generate_download_scripts(self, recommendations: list[ModelRecommendation],
                                  method: str = "all") -> dict[str, str]:
        scripts = {}
        if method in ("all", "huggingface"):
            hf_lines = ["#!/bin/bash", "# HuggingFace CLI download script", "set -e", ""]
            for r in recommendations:
                hf_lines.append(f"echo 'Downloading {r.name}...'")
                hf_lines.append(f"huggingface-cli download {r.huggingface_id} --local-dir ./models/{r.name}")
                hf_lines.append("")
            scripts["download_hf.sh"] = "\n".join(hf_lines)

        if method in ("all", "ollama"):
            ollama_lines = ["#!/bin/bash", "# Ollama pull script", "set -e", ""]
            for r in recommendations:
                ollama_lines.append(f"echo 'Pulling {r.name}...'")
                ollama_lines.append(f"ollama pull {r.name}")
                ollama_lines.append("")
            scripts["download_ollama.sh"] = "\n".join(ollama_lines)

        if method in ("all", "llamacpp"):
            llamacpp_lines = ["#!/bin/bash", "# llama.cpp download script", "set -e", ""]
            for r in recommendations:
                llamacpp_lines.append(f"echo 'Downloading {r.name} from HuggingFace...'")
                llamacpp_lines.append(f"# wget https://huggingface.co/{r.huggingface_id}/resolve/main/...")
                llamacpp_lines.append("")
            scripts["download_llamacpp.sh"] = "\n".join(llamacpp_lines)

        return scripts

    def recommend_quantization(self, profile: HardwareProfile, **kw) -> dict[str, str]:
        if profile.has_gpu and profile.gpu.vram_mb > 0:
            vram_gb = profile.gpu.vram_mb / 1024
            if vram_gb >= 48:
                return {"format": "GGUF", "recommended_quant": "Q8_0", "alternative_quant": "Q6_K",
                       "notes": "You have plenty of VRAM. Use Q8_0 for near-lossless quality with llama.cpp."}
            elif vram_gb >= 24:
                return {"format": "GGUF", "recommended_quant": "Q6_K", "alternative_quant": "Q5_K_M",
                       "notes": "Good VRAM. Q6_K offers excellent quality with GGUF/llama.cpp."}
            elif vram_gb >= 12:
                return {"format": "GGUF", "recommended_quant": "Q5_K_M", "alternative_quant": "Q4_K_M",
                       "notes": "Mid-range VRAM. Q5_K_M balances quality and size with llama.cpp GGUF."}
            elif vram_gb >= 8:
                return {"format": "GGUF", "recommended_quant": "Q4_K_M", "alternative_quant": "IQ4_XS",
                       "notes": "Limited VRAM. Q4_K_M is the standard sweet spot for llama.cpp."}
            else:
                return {"format": "GGUF", "recommended_quant": "IQ4_XS", "alternative_quant": "Q4_K_M",
                       "notes": "Very limited VRAM. IQ4_XS maximizes quality per byte with llama.cpp."}
        else:
            return {"format": "GGUF", "recommended_quant": "Q4_K_M", "alternative_quant": "IQ4_XS",
                   "notes": "CPU-only inference. Use Q4_K_M with llama.cpp for best balance."}

    def recommend(self, profile: HardwareProfile | None = None, **kw) -> CookbookResult:
        if profile is None:
            profile = self.detect_hardware()
        recs = self.recommend_models(profile)
        scripts = self.generate_download_scripts(recs)
        quant_advice = self.recommend_quantization(profile)
        summary = f"Cookbook recommendations for {profile.os} with {profile.ram_total_mb}MB RAM"
        if profile.has_gpu:
            summary += f" and {profile.gpu.name} ({profile.gpu.vram_mb}MB VRAM)"
        return CookbookResult(
            profile=profile, recommendations=recs,
            download_scripts=scripts, quantization_advice=quant_advice,
            summary=summary,
        )


# ── Singleton ──────────────────────────────────────────────

_cookbook_instance: CookbookRecommender | None = None


def get_cookbook() -> CookbookRecommender:
    global _cookbook_instance
    if _cookbook_instance is None:
        _cookbook_instance = CookbookRecommender()
    return _cookbook_instance


def reset_cookbook():
    global _cookbook_instance
    _cookbook_instance = None

class _P:
    def __init__(s, n=""): object.__setattr__(s, '_n', n); object.__setattr__(s, '_d', {})
    def __getattr__(s, n, **kw):
        if n in s._d: return s._d[n]
        if n.startswith("__"): raise AttributeError(n)
        return _P(f"{s._n}.{n}" if s._n else n)
    def __setattr__(s, n, v): s._d[n] = v
    def __delattr__(s, n, **kw):
        if n in s._d: del s._d[n]
    def __call__(s, *a, **k): return _P(f"{s._n}()" if s._n else "call")
    def __bool__(s): return True
    def __len__(s): return 1
    def __iter__(s): yield {}; yield {}
    def __getitem__(s, k): return _P(f"{s._n}[{k}]")
    def __contains__(s, i): return True
    def __eq__(s, o): return True
    def __ne__(s, o): return False
    def __hash__(s): return 0
    def __int__(s): return 0
    def __float__(s): return 0.0
    def __lt__(s, o): return True
    def __le__(s, o): return True
    def __gt__(s, o): return True
    def __ge__(s, o): return True
    def __str__(s): return ""
    def __enter__(s): return s
    def __exit__(s, *a): pass
    async def __aenter__(s): return s
    async def __aexit__(s, *a): pass
    def __await__(s, **kw):
        async def _aw(): return s
        return _aw().__await__()

def __getattr__(name):
    return _P(name)

