"""
Visual Cortex (V1/V2) — 视觉皮层
=================================
核心功能:
  GaborFilterBank  — 朝向选择性滤波器 (Hubel & Wiesel 1962)
  FeatureExtractor — 简单特征提取 (边缘/纹理/亮度)
  VisualBuffer     — 视觉工作缓冲区

参考:
  Hubel DH, Wiesel TN. "Receptive fields of single neurones in cat's striate cortex." J Physiol, 1959
  Marr D. "Vision." 1982
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional


@dataclass
class VisualFeature:
    name: str
    value: float
    location: Tuple[int, int]  # (x, y) in receptive field
    confidence: float


@dataclass
class EdgeDetected:
    orientation: float       # radians
    strength: float
    position: Tuple[int, int]
    scale: float


class GaborFilterBank:
    """V1 simple cells — orientation-selective Gabor filters."""

    def __init__(self, n_orientations: int = 8, n_scales: int = 3, kernel_size: int = 15):
        self.n_orientations = n_orientations
        self.n_scales = n_scales
        self.kernel_size = kernel_size
        self.kernels = self._build_kernels()

    def _gabor(self, x: np.ndarray, y: np.ndarray, theta: float, sigma: float,
               wavelength: float, phase: float = 0.0) -> np.ndarray:
        x_theta = x * np.cos(theta) + y * np.sin(theta)
        y_theta = -x * np.sin(theta) + y * np.cos(theta)
        gaussian = np.exp(-(x_theta**2 + y_theta**2) / (2 * sigma**2))
        sinusoidal = np.cos(2 * np.pi * x_theta / wavelength + phase)
        return gaussian * sinusoidal

    def _build_kernels(self) -> List[Dict]:
        kernels = []
        xs = np.linspace(-self.kernel_size//2, self.kernel_size//2, self.kernel_size)
        x, y = np.meshgrid(xs, xs)

        for scale_idx in range(self.n_scales):
            sigma = 2.0 + scale_idx * 1.5
            wavelength = sigma * 2.5
            for o in range(self.n_orientations):
                theta = o * np.pi / self.n_orientations
                even = self._gabor(x, y, theta, sigma, wavelength, 0.0)
                odd = self._gabor(x, y, theta, sigma, wavelength, np.pi/2)
                energy = np.sqrt(even**2 + odd**2)
                kernels.append({
                    'orientation': theta,
                    'scale': sigma,
                    'even': even,
                    'odd': odd,
                    'energy': energy
                })
        return kernels

    def apply(self, image: np.ndarray) -> List[EdgeDetected]:
        """Apply all Gabor filters to an image. Returns detected edges."""
        if len(image.shape) == 3:
            image = np.mean(image, axis=2)  # grayscale

        h, w = image.shape
        results = []

        for kernel in self.kernels:
            kh, kw = kernel['energy'].shape
            for y in range(0, h - kh, 4):
                for x in range(0, w - kw, 4):
                    patch = image[y:y+kh, x:x+kw]
                    if patch.shape != kernel['energy'].shape:
                        continue
                    response = np.sum(patch * kernel['energy'])
                    norm_factor = np.sqrt(np.sum(patch**2) * np.sum(kernel['energy']**2)) + 1e-8
                    normalized = response / norm_factor

                    if abs(normalized) > 0.15:
                        results.append(EdgeDetected(
                            orientation=kernel['orientation'],
                            strength=abs(float(normalized)),
                            position=(x + kw//2, y + kh//2),
                            scale=kernel['scale']
                        ))

        return results


class FeatureExtractor:
    """V2/V4 — mid-level visual features: color, texture, brightness."""

    def extract(self, image: np.ndarray) -> List[VisualFeature]:
        features = []

        if len(image.shape) == 3:
            r, g, b = np.mean(image[:,:,0]), np.mean(image[:,:,1]), np.mean(image[:,:,2])
            features.append(VisualFeature("red_channel", float(r), (0,0), 0.9))
            features.append(VisualFeature("green_channel", float(g), (0,0), 0.9))
            features.append(VisualFeature("blue_channel", float(b), (0,0), 0.9))

            # Color opponency (red-green, blue-yellow)
            rg = float(r - g) / 255.0
            by = float(b - (r+g)/2) / 255.0
            features.append(VisualFeature("rg_opponent", rg, (0,0), 0.7))
            features.append(VisualFeature("by_opponent", by, (0,0), 0.7))

        # Brightness
        gray = image if len(image.shape) == 2 else np.mean(image, axis=2)
        features.append(VisualFeature("brightness_mean", float(np.mean(gray)), (0,0), 0.9))
        features.append(VisualFeature("brightness_std", float(np.std(gray)), (0,0), 0.8))
        features.append(VisualFeature("contrast", float(np.std(gray) / (np.mean(gray) + 1e-8)), (0,0), 0.7))

        return features

    def extract_from_features(self, feature_vector: np.ndarray) -> List[VisualFeature]:
        """Extract from pre-computed feature vector (for benchmark)."""
        features = []
        names = ["brightness", "contrast", "edge_density", "motion_energy",
                 "color_red", "color_green", "color_blue", "texture_coarseness"]

        for i, name in enumerate(names):
            if i < len(feature_vector):
                features.append(VisualFeature(
                    name=name,
                    value=float(feature_vector[i]),
                    location=(0, 0),
                    confidence=0.8
                ))
        return features


class VisualBuffer:
    """Iconic memory / visual working buffer (~300ms persistence)."""

    def __init__(self, capacity: int = 3):
        self.capacity = capacity
        self.buffer: List[Tuple[np.ndarray, float]] = []  # (image, decay)

    def push(self, image: np.ndarray):
        self.buffer.append((image.copy(), 1.0))
        if len(self.buffer) > self.capacity:
            self.buffer.pop(0)

    def decay(self, dt: float = 0.1):
        self.buffer = [(img, max(0, d - dt)) for img, d in self.buffer]
        self.buffer = [(img, d) for img, d in self.buffer if d > 0.01]

    def get_latest(self) -> Optional[np.ndarray]:
        if self.buffer:
            return self.buffer[-1][0]
        return None
