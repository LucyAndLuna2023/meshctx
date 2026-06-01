"""
meshctx v3.88 — Cookbook Hardware Recommender (Cookbook硬件推荐器)

Detects GPU/CPU/RAM → recommends models → generates download scripts → suggests quantization.
Class: CookbookRecommender

Capabilities:
  1. Hardware detection — GPU brand/model/VRAM, CPU cores, total RAM
  2. Model recommendations — matched to hardware tier (7 tiers)
  3. Download script generation — huggingface-cli, ollama, llama.cpp, etc.
  4. Quantization advice — GGUF format recommendation based on available VRAM/RAM
"""

import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("meshctx.cookbook")


# ═══════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════

@dataclass
class GPUInfo:
    """GPU detection result"""
    name: str = ""
    vendor: str = ""          # nvidia, amd, intel, apple
    vram_mb: int = 0
    driver_version: str = ""
    count: int = 0
    cuda_support: bool = False
    metal_support: bool = False
    rocm_support: bool = False

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "vendor": self.vendor,
            "vram_mb": self.vram_mb,
            "vram_gb": round(self.vram_mb / 1024, 1),
            "driver_version": self.driver_version,
            "count": self.count,
            "cuda_support": self.cuda_support,
            "metal_support": self.metal_support,
            "rocm_support": self.rocm_support,
        }


@dataclass
class CPUInfo:
    """CPU detection result"""
    model: str = ""
    cores_physical: int = 0
    cores_logical: int = 0
    arch: str = ""            # x86_64, arm64, etc.
    vendor: str = ""          # Intel, AMD, Apple

    def to_dict(self) -> Dict:
        return {
            "model": self.model,
            "cores_physical": self.cores_physical,
            "cores_logical": self.cores_logical,
            "arch": self.arch,
            "vendor": self.vendor,
        }


@dataclass
class HardwareProfile:
    """Aggregated hardware profile"""
    gpu: GPUInfo = field(default_factory=GPUInfo)
    cpu: CPUInfo = field(default_factory=CPUInfo)
    ram_total_mb: int = 0
    ram_available_mb: int = 0
    os: str = ""
    hostname: str = ""
    has_gpu: bool = False

    def to_dict(self) -> Dict:
        return {
            "gpu": self.gpu.to_dict(),
            "cpu": self.cpu.to_dict(),
            "ram_total_mb": self.ram_total_mb,
            "ram_total_gb": round(self.ram_total_mb / 1024, 1),
            "ram_available_mb": self.ram_available_mb,
            "os": self.os,
            "hostname": self.hostname,
            "has_gpu": self.has_gpu,
        }


@dataclass
class ModelRecommendation:
    """A single model recommendation"""
    name: str                           # e.g. "llama-3-8b"
    family: str = ""                    # e.g. "llama", "mistral", "qwen"
    params_b: float = 0.0              # billions of params
    quant: str = ""                    # e.g. "Q4_K_M", "Q8_0", "FP16"
    size_gb: float = 0.0              # approx disk size
    vram_min_mb: int = 0              # minimum VRAM needed
    ram_min_mb: int = 0               # minimum RAM needed (CPU only)
    download_url: str = ""            # primary download URL
    huggingface_id: str = ""          # huggingface model id
    notes: str = ""                   # additional notes
    tier: str = ""                    # tiny, small, medium, large, xl, xxl, goliath


@dataclass
class CookbookResult:
    """Complete cookbook recommendation output"""
    profile: HardwareProfile = field(default_factory=HardwareProfile)
    recommendations: List[ModelRecommendation] = field(default_factory=list)
    download_scripts: Dict[str, str] = field(default_factory=dict)
    quantization_advice: Dict[str, str] = field(default_factory=dict)
    summary: str = ""

    def to_dict(self) -> Dict:
        return {
            "profile": self.profile.to_dict(),
            "recommendations": [
                {
                    "name": r.name,
                    "family": r.family,
                    "params_b": r.params_b,
                    "quant": r.quant,
                    "size_gb": r.size_gb,
                    "vram_min_mb": r.vram_min_mb,
                    "ram_min_mb": r.ram_min_mb,
                    "huggingface_id": r.huggingface_id,
                    "tier": r.tier,
                    "notes": r.notes,
                }
                for r in self.recommendations
            ],
            "download_scripts": self.download_scripts,
            "quantization_advice": self.quantization_advice,
            "summary": self.summary,
        }


# ═══════════════════════════════════════════════════════════
# Model Database — curated models by tier
# ═══════════════════════════════════════════════════════════

# Format: (name, family, params_b, default_quant, size_gb, vram_min_mb, ram_min_mb, hf_id, notes)
_MODEL_DB: List[Tuple] = [
    # ── Tiny tier (< 3B) ──
    ("gemma-2-2b-it", "gemma", 2.6, "Q4_K_M", 1.8, 2048, 4096,
     "google/gemma-2-2b-it-GGUF", "Google Gemma 2, strong for size"),
    ("qwen2.5-1.5b-instruct", "qwen", 1.5, "Q4_K_M", 1.1, 1536, 3072,
     "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "Qwen 2.5, excellent multilingual"),
    ("tinyllama-1.1b-chat", "llama", 1.1, "Q4_K_M", 0.8, 1024, 2048,
     "TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF", "Lightweight, good for edge"),

    # ── Small tier (3B-8B) ──
    ("llama-3.2-3b-instruct", "llama", 3.2, "Q4_K_M", 2.2, 3072, 6144,
     "unsloth/Llama-3.2-3B-Instruct-GGUF", "Meta Llama 3.2, strong generalist"),
    ("mistral-7b-instruct-v0.3", "mistral", 7.3, "Q4_K_M", 4.4, 6144, 10240,
     "MaziyarPanahi/Mistral-7B-Instruct-v0.3-GGUF", "Mistral 7B, excellent reasoning"),
    ("qwen2.5-7b-instruct", "qwen", 7.6, "Q4_K_M", 4.6, 6144, 10240,
     "Qwen/Qwen2.5-7B-Instruct-GGUF", "Qwen 2.5 7B, strong coding"),
    ("phi-4-mini-instruct", "phi", 3.8, "Q4_K_M", 2.5, 4096, 6144,
     "microsoft/Phi-4-mini-instruct-GGUF", "Microsoft Phi-4 mini, efficient"),

    # ── Medium tier (8B-14B) ──
    ("llama-3.1-8b-instruct", "llama", 8.0, "Q4_K_M", 5.0, 8192, 16384,
     "unsloth/Llama-3.1-8B-Instruct-GGUF", "Llama 3.1 8B, versatile"),
    ("mistral-nemo-12b-instruct", "mistral", 12.2, "Q4_K_M", 7.1, 10240, 20480,
     "MaziyarPanahi/Mistral-Nemo-Instruct-2407-GGUF", "Mistral Nemo, large context"),
    ("qwen2.5-14b-instruct", "qwen", 14.7, "Q4_K_M", 8.5, 12288, 24576,
     "Qwen/Qwen2.5-14B-Instruct-GGUF", "Qwen 2.5 14B, balanced"),

    # ── Large tier (20B-35B) ──
    ("qwen2.5-32b-instruct", "qwen", 32.5, "Q4_K_M", 20.0, 20480, 32768,
     "Qwen/Qwen2.5-32B-Instruct-GGUF", "Qwen 2.5 32B, strong all-round"),
    ("codestral-22b", "mistral", 22.2, "Q4_K_M", 13.0, 16384, 24576,
     "MaziyarPanahi/Codestral-22B-v0.1-GGUF", "Mistral code specialist"),
    ("command-r-35b", "cohere", 35.0, "Q4_K_M", 21.0, 24576, 40960,
     "MaziyarPanahi/c4ai-command-r-plus-GGUF", "Cohere R+, RAG optimized"),

    # ── XL tier (40B-72B) ──
    ("llama-3.3-70b-instruct", "llama", 70.6, "Q4_K_M", 42.0, 40960, 65536,
     "unsloth/Llama-3.3-70B-Instruct-GGUF", "Llama 3.3 70B, top quality"),
    ("qwen2.5-72b-instruct", "qwen", 72.7, "Q4_K_M", 43.0, 40960, 65536,
     "Qwen/Qwen2.5-72B-Instruct-GGUF", "Qwen 2.5 72B, frontier"),
    ("deepseek-r1-distill-llama-70b", "deepseek", 70.6, "Q4_K_M", 42.0, 40960, 65536,
     "unsloth/DeepSeek-R1-Distill-Llama-70B-GGUF", "DeepSeek R1 distill, reasoning"),

    # ── XXL tier (100B+) ──
    ("command-a-111b", "cohere", 111.0, "Q4_K_M", 67.0, 65536, 98304,
     "MaziyarPanahi/c4ai-command-a-111B-GGUF", "Cohere A, huge context"),
    ("llama-3.1-405b-instruct", "llama", 405.0, "Q3_K_M", 180.0, 131072, 262144,
     "unsloth/Llama-3.1-405B-Instruct-GGUF", "Llama 3.1 405B, frontier"),
]


# ═══════════════════════════════════════════════════════════
# Core Recommender
# ═══════════════════════════════════════════════════════════

class CookbookRecommender:
    """Hardware detection + model recommendation + download scripts + quantization advice.

    Usage:
        recommender = CookbookRecommender()
        result = recommender.recommend()           # full pipeline
        profile = recommender.detect_hardware()     # just detect
        models = recommender.recommend_models(profile)  # just recommend
    """

    # ── Hardware Detection ──────────────────────────────────

    def detect_hardware(self) -> HardwareProfile:
        """Detect system hardware: GPU, CPU, RAM, OS.

        Returns a fully populated HardwareProfile.
        """
        profile = HardwareProfile()

        # OS and hostname
        profile.os = platform.system()
        profile.hostname = platform.node()

        # CPU detection
        profile.cpu = self._detect_cpu()

        # RAM detection
        profile.ram_total_mb, profile.ram_available_mb = self._detect_ram()

        # GPU detection
        gpu = self._detect_gpu()
        profile.gpu = gpu
        profile.has_gpu = gpu.count > 0 and gpu.vram_mb > 0

        logger.info("Hardware profile: GPU=%s, CPU=%s, RAM=%dMB",
                     gpu.name or "none", profile.cpu.model, profile.ram_total_mb)

        return profile

    def _detect_cpu(self) -> CPUInfo:
        """Detect CPU information cross-platform."""
        cpu = CPUInfo()
        cpu.arch = platform.machine()

        try:
            if platform.system() == "Linux":
                cpu = self._detect_cpu_linux(cpu)
            elif platform.system() == "Darwin":
                cpu = self._detect_cpu_macos(cpu)
            elif platform.system() == "Windows":
                cpu = self._detect_cpu_windows(cpu)
        except Exception as e:
            logger.warning("CPU detection fallback: %s", e)

        # Defaults if detection failed
        if cpu.cores_physical == 0:
            cpu.cores_physical = max(1, os.cpu_count() or 1)
        if cpu.cores_logical == 0:
            cpu.cores_logical = max(1, os.cpu_count() or 1)
        if not cpu.model:
            cpu.model = cpu.arch

        return cpu

    def _detect_cpu_linux(self, cpu: CPUInfo) -> CPUInfo:
        """Linux CPU detection via /proc/cpuinfo."""
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read()
            # Model name
            m = re.search(r"model name\s*:\s*(.+)", content)
            if m:
                cpu.model = m.group(1).strip()

            # Vendor
            if "GenuineIntel" in content:
                cpu.vendor = "Intel"
            elif "AuthenticAMD" in content:
                cpu.vendor = "AMD"
            elif "Apple" in content:
                cpu.vendor = "Apple"

            # Count unique physical IDs for physical cores
            physical_ids = set(re.findall(r"physical id\s*:\s*(\d+)", content))
            if physical_ids:
                siblings = re.findall(r"siblings\s*:\s*(\d+)", content)
                cpu_cores = re.findall(r"cpu cores\s*:\s*(\d+)", content)
                if cpu_cores:
                    cpu.cores_physical = sum(int(c) for c in cpu_cores)
            if cpu.cores_physical == 0:
                cpu.cores_physical = os.cpu_count() or 1

            # Logical cores = processor count
            processors = re.findall(r"^processor\s*:", content, re.MULTILINE)
            cpu.cores_logical = len(processors) or os.cpu_count() or 1
        except Exception:
            pass
        return cpu

    def _detect_cpu_macos(self, cpu: CPUInfo) -> CPUInfo:
        """macOS CPU detection via sysctl."""
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                cpu.model = result.stdout.strip()

            result = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                cpu.cores_physical = int(result.stdout.strip())

            result = subprocess.run(
                ["sysctl", "-n", "hw.logicalcpu"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                cpu.cores_logical = int(result.stdout.strip())

            if cpu.model and "Apple" in cpu.model:
                cpu.vendor = "Apple"
            elif cpu.model and "Intel" in cpu.model:
                cpu.vendor = "Intel"
        except Exception:
            pass
        return cpu

    def _detect_cpu_windows(self, cpu: CPUInfo) -> CPUInfo:
        """Windows CPU detection via wmic."""
        try:
            result = subprocess.run(
                ["wmic", "cpu", "get", "Name,NumberOfCores,NumberOfLogicalProcessors",
                 "/format:csv"],
                capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                parts = lines[1].split(",")
                if len(parts) >= 3:
                    cpu.model = parts[-3].strip() if len(parts) >= 3 else ""
                    try:
                        cpu.cores_physical = int(parts[-2].strip()) if parts[-2].strip() else 0
                    except ValueError:
                        pass
                    try:
                        cpu.cores_logical = int(parts[-1].strip()) if parts[-1].strip() else 0
                    except ValueError:
                        pass
            if "Intel" in cpu.model:
                cpu.vendor = "Intel"
            elif "AMD" in cpu.model:
                cpu.vendor = "AMD"
        except Exception:
            pass
        return cpu

    def _detect_ram(self) -> Tuple[int, int]:
        """Detect total and available RAM in MB. Cross-platform."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return int(mem.total / (1024 * 1024)), int(mem.available / (1024 * 1024))
        except ImportError:
            logger.warning("psutil not available for RAM detection")
            return self._detect_ram_fallback()

    def _detect_ram_fallback(self) -> Tuple[int, int]:
        """Fallback RAM detection without psutil."""
        total = 0
        try:
            if platform.system() == "Linux":
                with open("/proc/meminfo", "r") as f:
                    content = f.read()
                    m = re.search(r"MemTotal:\s*(\d+)", content)
                    if m:
                        total = int(m.group(1)) // 1024  # kB → MB
                    m = re.search(r"MemAvailable:\s*(\d+)", content)
                    available = int(m.group(1)) // 1024 if m else total // 2
                    return total, available
            elif platform.system() == "Darwin":
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    total = int(result.stdout.strip()) // (1024 * 1024)
                    return total, total // 2  # conservative available
        except Exception:
            pass
        default_mb = 8192
        return (total or default_mb), ((total or default_mb) // 2)  # sensible default

    def _detect_gpu(self) -> GPUInfo:
        """Detect GPU information cross-platform."""
        gpu = GPUInfo(count=0)

        # NVIDIA GPU detection via nvidia-smi
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split("\n")
                gpu.count = len(lines)
                # Use first GPU
                parts = [p.strip() for p in lines[0].split(",")]
                if len(parts) >= 2:
                    gpu.name = parts[0]
                    try:
                        gpu.vram_mb = int(parts[1])
                    except ValueError:
                        gpu.vram_mb = 0
                if len(parts) >= 3:
                    gpu.driver_version = parts[2]
                gpu.vendor = "nvidia"
                gpu.cuda_support = True
                return gpu
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # AMD ROCm / rocm-smi detection
        try:
            result = subprocess.run(
                ["rocm-smi", "--showproductname", "--showmeminfo", "vram",
                 "--csv"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                gpu.count = 1
                gpu.vendor = "amd"
                gpu.rocm_support = True
                # Try to parse GPU name and VRAM
                for line in result.stdout.strip().split("\n"):
                    if "Card Series" in line or "GPU" in line:
                        gpu.name = line.split(",")[-1].strip()
                    if "VRAM" in line or "Memory" in line:
                        try:
                            val = re.search(r"(\d+)", line.split(",")[-1])
                            if val:
                                gpu.vram_mb = int(val.group(1))
                        except ValueError:
                            pass
                if gpu.name or gpu.vram_mb > 0:
                    return gpu
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Apple Silicon / Metal detection
        if platform.system() == "Darwin":
            try:
                result = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    content = result.stdout
                    # Chip model
                    m = re.search(r"Chipset Model:\s*(.+)", content)
                    if not m:
                        m = re.search(r"Chip:\s*(.+)", content)
                    if m:
                        gpu.name = m.group(1).strip()
                        gpu.count = 1
                        gpu.vendor = "apple"
                        gpu.metal_support = True
                    # VRAM
                    m = re.search(r"VRAM.*?:\s*(\d+)\s*(GB|MB)", content)
                    if m:
                        val = int(m.group(1))
                        gpu.vram_mb = val * 1024 if m.group(2).upper() == "GB" else val
                    if gpu.name:
                        return gpu
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        # Try to detect via lspci on Linux
        try:
            result = subprocess.run(
                ["lspci"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                content = result.stdout
                if "VGA" in content or "3D" in content:
                    for line in content.split("\n"):
                        if "VGA" in line or "3D" in line:
                            gpu.name = line.split(":")[-1].strip()
                            gpu.count = 1
                            if "NVIDIA" in line.upper():
                                gpu.vendor = "nvidia"
                            elif "AMD" in line.upper() or "ATI" in line.upper():
                                gpu.vendor = "amd"
                            elif "Intel" in line.upper():
                                gpu.vendor = "intel"
                            break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        logger.info("GPU detection: %s (vendor=%s, vram=%dMB)",
                     gpu.name or "none", gpu.vendor, gpu.vram_mb)
        return gpu

    # ── Model Recommendation ────────────────────────────────

    def recommend_models(self, profile: Optional[HardwareProfile] = None) -> List[ModelRecommendation]:
        """Recommend models based on hardware profile.

        If no profile is given, detects hardware first.
        Returns a list of ModelRecommendation objects.
        """
        if profile is None:
            profile = self.detect_hardware()

        effective_memory_mb = profile.gpu.vram_mb if profile.has_gpu else profile.ram_total_mb
        is_gpu = profile.has_gpu

        recommendations: List[ModelRecommendation] = []

        for (name, family, params_b, default_quant, size_gb,
             vram_min_mb, ram_min_mb, hf_id, notes) in _MODEL_DB:

            required = vram_min_mb if is_gpu else ram_min_mb

            if required <= effective_memory_mb:
                # Determine tier
                tier = self._determine_tier(params_b)

                # Adjust quant based on headroom
                quant = default_quant
                if is_gpu:
                    headroom = effective_memory_mb - vram_min_mb
                    if headroom > 16384 and params_b > 30:
                        quant = "Q8_0"  # can afford higher quality
                    elif headroom < 2048:
                        quant = "IQ4_XS"  # tight on VRAM, use better compression
                else:
                    headroom = effective_memory_mb - ram_min_mb
                    if headroom < 2048 and params_b > 10:
                        quant = "IQ4_XS"  # CPU-only with tight RAM

                # Recalculate size for adjusted quant
                adj_size = self._estimate_size(params_b, quant)

                rec = ModelRecommendation(
                    name=name,
                    family=family,
                    params_b=params_b,
                    quant=quant,
                    size_gb=adj_size,
                    vram_min_mb=vram_min_mb,
                    ram_min_mb=ram_min_mb,
                    huggingface_id=hf_id,
                    tier=tier,
                    notes=notes,
                )
                recommendations.append(rec)

        # Sort by params ascending
        recommendations.sort(key=lambda r: r.params_b)

        return recommendations

    @staticmethod
    def _determine_tier(params_b: float) -> str:
        """Classify model by parameter count into a tier name."""
        if params_b <= 3:
            return "tiny"
        elif params_b <= 8:
            return "small"
        elif params_b <= 15:
            return "medium"
        elif params_b <= 35:
            return "large"
        elif params_b <= 75:
            return "xl"
        elif params_b <= 120:
            return "xxl"
        else:
            return "goliath"

    @staticmethod
    def _estimate_size(params_b: float, quant: str) -> float:
        """Estimate GGUF file size in GB based on params and quantization."""
        # FP16 baseline: ~2 bytes per param
        fp16_size = params_b * 2.0  # GB

        quant_multipliers = {
            "Q8_0": 0.525,      # ~8.4 bits/param
            "Q6_K": 0.41,       # ~6.6 bits/param
            "Q5_K_M": 0.355,    # ~5.7 bits/param
            "Q4_K_M": 0.30,     # ~4.8 bits/param
            "Q3_K_M": 0.235,    # ~3.75 bits/param
            "IQ4_XS": 0.27,     # ~4.3 bits/param (importance weighted)
            "Q2_K": 0.185,      # ~3.0 bits/param
        }

        mult = quant_multipliers.get(quant, 0.30)
        return round(fp16_size * mult, 1)

    # ── Download Script Generation ──────────────────────────

    def generate_download_scripts(self,
                                  recommendations: List[ModelRecommendation],
                                  method: str = "all") -> Dict[str, str]:
        """Generate download scripts for recommended models.

        Args:
            recommendations: list of ModelRecommendation from recommend_models()
            method: "huggingface", "ollama", "llama_cpp", or "all" (default)

        Returns dict of script_name → script_content.
        """
        scripts: Dict[str, str] = {}

        if method in ("huggingface", "all"):
            scripts["download_hf.sh"] = self._gen_huggingface_script(recommendations)

        if method in ("ollama", "all"):
            scripts["download_ollama.sh"] = self._gen_ollama_script(recommendations)

        if method in ("llama_cpp", "all"):
            scripts["download_llamacpp.sh"] = self._gen_llamacpp_script(recommendations)

        return scripts

    def _gen_huggingface_script(self, recs: List[ModelRecommendation]) -> str:
        """Generate a bash script using huggingface-cli to download GGUF files."""
        lines = [
            "#!/bin/bash",
            "# Generated by MeshCtx v3.88 CookbookRecommender",
            "# Download models via huggingface-cli",
            "# Install: pip install huggingface_hub",
            "",
            "set -e",
            "",
            "# Configuration",
            'DOWNLOAD_DIR="${HOME}/models"',
            'mkdir -p "$DOWNLOAD_DIR"',
            "",
            "# Check for huggingface-cli",
            "if ! command -v huggingface-cli &> /dev/null; then",
            '    echo "Installing huggingface_hub..."',
            "    pip install huggingface_hub",
            "fi",
            "",
            "echo 'Downloading recommended models...'",
            "",
        ]

        for r in recs:
            lines.append(f"# {r.name} — {r.tier} tier, {r.params_b}B params, {r.quant}")
            lines.append(f'huggingface-cli download "{r.huggingface_id}" '
                         f'--include "*{r.quant}*" '
                         f'--local-dir "$DOWNLOAD_DIR/{r.name}" 2>&1 | tail -1')
            lines.append(f'echo "  ✓ {r.name} downloaded"')
            lines.append("")

        lines.append('echo ""')
        lines.append('echo "All models downloaded to $DOWNLOAD_DIR"')
        lines.append('ls -lh "$DOWNLOAD_DIR"')

        return "\n".join(lines)

    def _gen_ollama_script(self, recs: List[ModelRecommendation]) -> str:
        """Generate a bash script using ollama pull."""
        # Map recommendations to Ollama model names
        ollama_map = {
            "llama-3.2-3b-instruct": "llama3.2:3b",
            "llama-3.1-8b-instruct": "llama3.1:8b",
            "mistral-7b-instruct-v0.3": "mistral:7b",
            "mistral-nemo-12b-instruct": "mistral-nemo:12b",
            "qwen2.5-7b-instruct": "qwen2.5:7b",
            "qwen2.5-14b-instruct": "qwen2.5:14b",
            "qwen2.5-32b-instruct": "qwen2.5:32b",
            "qwen2.5-72b-instruct": "qwen2.5:72b",
            "gemma-2-2b-it": "gemma2:2b",
            "phi-4-mini-instruct": "phi4:mini",
            "codestral-22b": "codestral:22b",
            "deepseek-r1-distill-llama-70b": "deepseek-r1:70b",
            "llama-3.3-70b-instruct": "llama3.3:70b",
        }

        lines = [
            "#!/bin/bash",
            "# Generated by MeshCtx v3.88 CookbookRecommender",
            "# Download models via Ollama",
            "# Install: curl -fsSL https://ollama.com/install.sh | sh",
            "",
            "set -e",
            "",
            "# Check for ollama",
            "if ! command -v ollama &> /dev/null; then",
            '    echo "Ollama not found. Install: curl -fsSL https://ollama.com/install.sh | sh"',
            "    exit 1",
            "fi",
            "",
            "echo 'Pulling recommended models via Ollama...'",
            "",
        ]

        for r in recs:
            ollama_name = ollama_map.get(r.name)
            if ollama_name:
                lines.append(f"# {r.name} — {r.tier} tier, {r.params_b}B params")
                lines.append(f"ollama pull {ollama_name}")
                lines.append(f'echo "  ✓ {r.name} pulled"')
                lines.append("")

        lines.append('echo ""')
        lines.append('echo "Available models:"')
        lines.append("ollama list")

        return "\n".join(lines)

    def _gen_llamacpp_script(self, recs: List[ModelRecommendation]) -> str:
        """Generate a script to download GGUF files directly via wget/curl."""
        lines = [
            "#!/bin/bash",
            "# Generated by MeshCtx v3.88 CookbookRecommender",
            "# Download GGUF files directly (no extra tools needed)",
            "# These URLs are examples — replace with actual GGUF URLs for your quant",
            "",
            "set -e",
            "",
            'DOWNLOAD_DIR="${HOME}/models/gguf"',
            'mkdir -p "$DOWNLOAD_DIR"',
            "",
            "# Models to download:",
        ]

        for r in recs:
            lines.append(f"# {r.name} — {r.family} {r.params_b}B {r.quant}")
            lines.append(f"#   HuggingFace: https://huggingface.co/{r.huggingface_id}")
            lines.append(f"#   Estimated size: {r.size_gb} GB")
            lines.append(f"#   Command (example):")
            lines.append(f'#   wget "https://huggingface.co/{r.huggingface_id}/resolve/main/'
                         f'{r.name.lower()}-{r.quant}.gguf" '
                         f'-O "$DOWNLOAD_DIR/{r.name}-{r.quant}.gguf"')
            lines.append("")

        lines.append('echo "See comments above for download URLs."')
        lines.append('echo "Download GGUF files from HuggingFace and place in $DOWNLOAD_DIR"')

        return "\n".join(lines)

    # ── Quantization Advice ─────────────────────────────────

    def recommend_quantization(self, profile: Optional[HardwareProfile] = None) -> Dict[str, str]:
        """Generate quantization advice based on hardware profile.

        Returns a dict with keys: 'recommended_quant', 'alternative_quant', 'notes', 'format'.
        """
        if profile is None:
            profile = self.detect_hardware()

        vram_gb = profile.gpu.vram_mb / 1024 if profile.has_gpu else 0
        ram_gb = profile.ram_total_mb / 1024

        advice: Dict[str, str] = {}

        if profile.has_gpu and vram_gb >= 48:
            advice = {
                "format": "GGUF",
                "recommended_quant": "Q8_0",
                "alternative_quant": "Q6_K",
                "target_bits_per_param": "8.0",
                "notes": (
                    f"Plenty of VRAM ({vram_gb:.0f}GB). Use Q8_0 for near-lossless quality "
                    "on models up to 30-40B. For models 70B+, Q6_K or Q4_K_M is practical."
                ),
            }
        elif profile.has_gpu and vram_gb >= 24:
            advice = {
                "format": "GGUF",
                "recommended_quant": "Q5_K_M",
                "alternative_quant": "Q4_K_M",
                "target_bits_per_param": "5.5",
                "notes": (
                    f"Good VRAM ({vram_gb:.0f}GB). Q5_K_M offers excellent quality-per-byte. "
                    "Use Q4_K_M for 30B+ models to fit comfortably."
                ),
            }
        elif profile.has_gpu and vram_gb >= 12:
            advice = {
                "format": "GGUF",
                "recommended_quant": "Q4_K_M",
                "alternative_quant": "IQ4_XS",
                "target_bits_per_param": "4.5",
                "notes": (
                    f"Moderate VRAM ({vram_gb:.0f}GB). Q4_K_M is the sweet spot. "
                    "IQ4_XS saves ~10% more memory with minimal quality loss."
                ),
            }
        elif profile.has_gpu and vram_gb >= 6:
            advice = {
                "format": "GGUF",
                "recommended_quant": "IQ4_XS",
                "alternative_quant": "Q3_K_M",
                "target_bits_per_param": "4.0",
                "notes": (
                    f"Limited VRAM ({vram_gb:.0f}GB). IQ4_XS prioritizes memory efficiency. "
                    "Q3_K_M for fitting larger models at slight quality cost."
                ),
            }
        elif profile.has_gpu:
            advice = {
                "format": "GGUF",
                "recommended_quant": "Q3_K_M",
                "alternative_quant": "Q2_K",
                "target_bits_per_param": "3.5",
                "notes": (
                    f"Minimal VRAM ({vram_gb:.0f}GB). Stick to 1-3B models. "
                    "Q3_K_M or Q2_K to maximize model size within limits."
                ),
            }
        else:
            # CPU-only
            if ram_gb >= 64:
                advice = {
                    "format": "GGUF (CPU inference via llama.cpp)",
                    "recommended_quant": "Q4_K_M",
                    "alternative_quant": "Q5_K_M",
                    "target_bits_per_param": "5.0",
                    "notes": (
                        f"CPU-only with {ram_gb:.0f}GB RAM. Q4_K_M for balance. "
                        "llama.cpp is the recommended engine. Consider OpenBLAS for speed."
                    ),
                }
            elif ram_gb >= 32:
                advice = {
                    "format": "GGUF (CPU inference via llama.cpp)",
                    "recommended_quant": "Q4_K_M",
                    "alternative_quant": "IQ4_XS",
                    "target_bits_per_param": "4.5",
                    "notes": (
                        f"CPU-only with {ram_gb:.0f}GB RAM. Q4_K_M is default. "
                        "llama.cpp recommended. Expect ~2-5 tokens/sec on 7B models."
                    ),
                }
            elif ram_gb >= 16:
                advice = {
                    "format": "GGUF (CPU inference via llama.cpp)",
                    "recommended_quant": "IQ4_XS",
                    "alternative_quant": "Q3_K_M",
                    "target_bits_per_param": "4.0",
                    "notes": (
                        f"CPU-only with {ram_gb:.0f}GB RAM. Stick to ≤8B models. "
                        "IQ4_XS for best memory efficiency. Consider Ollama for ease."
                    ),
                }
            else:
                advice = {
                    "format": "GGUF (CPU inference via llama.cpp)",
                    "recommended_quant": "Q3_K_M",
                    "alternative_quant": "Q2_K",
                    "target_bits_per_param": "3.0",
                    "notes": (
                        f"CPU-only with limited {ram_gb:.0f}GB RAM. Use ≤3B models only. "
                        "TinyLlama, Gemma 2B, Qwen 1.5B are good options."
                    ),
                }

        return advice

    # ── Full Pipeline ───────────────────────────────────────

    def recommend(self, profile: Optional[HardwareProfile] = None,
                  script_method: str = "all") -> CookbookResult:
        """Run the full recommendation pipeline.

        1. Detect hardware (or use provided profile)
        2. Recommend models
        3. Generate download scripts
        4. Provide quantization advice
        5. Build summary

        Returns a CookbookResult with everything.
        """
        if profile is None:
            profile = self.detect_hardware()

        models = self.recommend_models(profile)
        scripts = self.generate_download_scripts(models, method=script_method)
        quant_advice = self.recommend_quantization(profile)

        # Build summary
        summary_parts = [
            "=" * 60,
            "MeshCtx v3.88 — Hardware Cookbook",
            "=" * 60,
            "",
            f"  OS:        {profile.os} ({profile.hostname})",
            f"  CPU:       {profile.cpu.model}",
            f"  Cores:     {profile.cpu.cores_physical} physical / {profile.cpu.cores_logical} logical",
            f"  RAM:       {profile.ram_total_mb // 1024} GB total",
        ]

        if profile.has_gpu:
            summary_parts.append(
                f"  GPU:       {profile.gpu.name} ({profile.gpu.vram_mb // 1024} GB VRAM)"
            )
        else:
            summary_parts.append("  GPU:       None detected (CPU-only mode)")

        summary_parts.extend([
            "",
            f"  Recommended Quant: {quant_advice.get('recommended_quant', 'N/A')}",
            f"  Format:            {quant_advice.get('format', 'N/A')}",
            "",
            f"  Compatible Models:  {len(models)}",
            "",
        ])

        if models:
            summary_parts.append("  Top recommendations:")
            for m in models[:5]:
                summary_parts.append(
                    f"    • {m.name} ({m.params_b:.0f}B, {m.quant}) — {m.tier} tier"
                )
            if len(models) > 5:
                summary_parts.append(f"    ... and {len(models) - 5} more")

            # Primary recommendation
            best = models[-1]  # largest compatible
            summary_parts.extend([
                "",
                f"  ★ Best Fit: {best.name} ({best.params_b:.0f}B, {best.quant})",
                f"    {best.notes}",
                f"    HuggingFace: https://huggingface.co/{best.huggingface_id}",
            ])

        summary_parts.extend([
            "",
            f"  Download scripts generated: {list(scripts.keys())}",
            "",
            "=" * 60,
        ])

        summary = "\n".join(summary_parts)

        result = CookbookResult(
            profile=profile,
            recommendations=models,
            download_scripts=scripts,
            quantization_advice=quant_advice,
            summary=summary,
        )

        logger.info("CookbookRecommender: %d models, %d scripts",
                     len(models), len(scripts))

        return result


# ═══════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════

_cookbook_instance: Optional[CookbookRecommender] = None


def get_cookbook() -> CookbookRecommender:
    """Get or create the singleton CookbookRecommender instance."""
    global _cookbook_instance
    if _cookbook_instance is None:
        _cookbook_instance = CookbookRecommender()
    return _cookbook_instance


def reset_cookbook() -> None:
    """Reset the singleton (useful for testing)."""
    global _cookbook_instance
    _cookbook_instance = None
