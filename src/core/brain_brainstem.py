"""
Brainstem — 脑干
=================
核心功能:
  AutonomicRegulator — 自主神经调节 (心率/呼吸/体温)
  ReticularActivation — 网状激活系统 (觉醒/睡眠)
  HomeostaticDrive  — 内稳态驱力 (饥饿/口渴/疲劳)

参考:
  Moruzzi G, Magoun HW. "Brain stem reticular formation and activation of the EEG." EEG Clin Neurophysiol, 1949
  Saper CB. "The central autonomic nervous system." Annu Rev Neurosci, 2002
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from collections import deque


@dataclass
class VitalSigns:
    heart_rate: float       # bpm
    respiration_rate: float # breaths/min
    body_temp: float        # °C
    blood_pressure: float   # mmHg systolic
    timestamp: float = 0.0


@dataclass
class ArousalState:
    level: float             # 0 (coma) → 1 (hyper-aroused)
    eeg_band: str            # delta/theta/alpha/beta/gamma
    sleep_pressure: float    # homeostatic sleep drive
    circadian_phase: float   # 0-24h


class AutonomicRegulator:
    """Medulla + Pons — cardiovascular, respiratory, thermoregulation."""

    def __init__(self):
        # Setpoints
        self.hr_setpoint = 72.0
        self.rr_setpoint = 14.0
        self.temp_setpoint = 37.0
        self.bp_setpoint = 120.0

        # Current state
        self.vitals = VitalSigns(
            heart_rate=72.0, respiration_rate=14.0,
            body_temp=37.0, blood_pressure=120.0
        )

        # Regulation gains (sympathetic/parasympathetic balance)
        self.sympathetic_tone = 0.5
        self.parasympathetic_tone = 0.5

        self.history: deque = deque(maxlen=200)

    def update(self, exertion: float = 0.0, stress: float = 0.0,
               ambient_temp: float = 22.0, dt: float = 0.1):
        """One time step of autonomic regulation."""
        # Heart rate: setpoint + exertion + stress
        target_hr = self.hr_setpoint + exertion * 30 + stress * 15
        hr_error = target_hr - self.vitals.heart_rate
        self.vitals.heart_rate += hr_error * dt * 2.0  # fast correction

        # Respiration
        target_rr = self.rr_setpoint + exertion * 8 + stress * 4
        rr_error = target_rr - self.vitals.respiration_rate
        self.vitals.respiration_rate += rr_error * dt * 1.5

        # Thermoregulation
        temp_error = self.temp_setpoint - self.vitals.body_temp
        # + ambient influence + exertion heat
        ambient_effect = (ambient_temp - self.vitals.body_temp) * 0.1
        exertion_heat = exertion * 0.5
        self.vitals.body_temp += (temp_error * 0.3 + ambient_effect + exertion_heat) * dt

        # Blood pressure (baroreflex)
        bp_target = self.bp_setpoint + stress * 20 + exertion * 10
        bp_error = bp_target - self.vitals.blood_pressure
        self.vitals.blood_pressure += bp_error * dt * 1.0

        # Clamp to physiological ranges
        self.vitals.heart_rate = np.clip(self.vitals.heart_rate, 40, 200)
        self.vitals.respiration_rate = np.clip(self.vitals.respiration_rate, 6, 40)
        self.vitals.body_temp = np.clip(self.vitals.body_temp, 34, 42)
        self.vitals.blood_pressure = np.clip(self.vitals.blood_pressure, 60, 200)

        self.vitals.timestamp += dt
        self.history.append(VitalSigns(
            self.vitals.heart_rate, self.vitals.respiration_rate,
            self.vitals.body_temp, self.vitals.blood_pressure,
            self.vitals.timestamp
        ))

    def heart_rate_variability(self) -> float:
        """RMSSD of recent heart rate (stress indicator)."""
        if len(self.history) < 10:
            return 3.0
        recent = [v.heart_rate for v in list(self.history)[-20:]]
        diffs = np.diff(recent)
        return float(np.sqrt(np.mean(diffs**2)))

    def is_stable(self) -> bool:
        """Check if all vitals are within normal range."""
        return (60 <= self.vitals.heart_rate <= 100 and
                10 <= self.vitals.respiration_rate <= 20 and
                36.5 <= self.vitals.body_temp <= 37.5 and
                90 <= self.vitals.blood_pressure <= 140)


class ReticularActivation:
    """Reticular Activating System (RAS) — arousal & sleep-wake cycle."""

    def __init__(self):
        self.state = ArousalState(
            level=0.7,          # awake
            eeg_band="beta",
            sleep_pressure=0.2,
            circadian_phase=10.0  # 10 AM
        )

    def update(self, stimulation: float = 0.0, dt: float = 0.1):
        """Update arousal level based on stimulation and homeostatic pressure."""
        # Circadian: sinusoidal over 24h
        self.state.circadian_phase = (self.state.circadian_phase + dt / 3600.0) % 24.0
        circadian_drive = np.sin(np.pi * (self.state.circadian_phase - 6) / 12.0) * 0.5 + 0.5

        # Sleep pressure accumulates with wake, dissipates with sleep
        if self.state.level > 0.3:  # awake
            self.state.sleep_pressure = min(1.0, self.state.sleep_pressure + dt * 0.02)
        else:  # asleep
            self.state.sleep_pressure = max(0.0, self.state.sleep_pressure - dt * 0.1)

        # Arousal = circadian + stimulation - sleep pressure
        target = circadian_drive * 0.6 + stimulation * 0.4 - self.state.sleep_pressure * 0.3
        self.state.level = float(np.clip(
            0.9 * self.state.level + 0.1 * target, 0.05, 1.0
        ))

        # EEG band
        if self.state.level > 0.8:
            self.state.eeg_band = "gamma"
        elif self.state.level > 0.6:
            self.state.eeg_band = "beta"
        elif self.state.level > 0.4:
            self.state.eeg_band = "alpha"
        elif self.state.level > 0.2:
            self.state.eeg_band = "theta"
        else:
            self.state.eeg_band = "delta"

    def is_awake(self) -> bool:
        return self.state.level > 0.3


class HomeostaticDrive:
    """Hypothalamus → brainstem: hunger, thirst, fatigue drives."""

    def __init__(self):
        self.hunger = 0.0       # 0=full, 1=starving
        self.thirst = 0.0       # 0=hydrated, 1=dehydrated
        self.fatigue = 0.0      # 0=rested, 1=exhausted
        self._time_awake = 0.0

    def update(self, activity_level: float = 0.5, dt: float = 0.1):
        """Accumulate homeostatic drives over time."""
        self._time_awake += dt
        self.hunger = min(1.0, self.hunger + dt * 0.015 * activity_level)
        self.thirst = min(1.0, self.thirst + dt * 0.02 * activity_level)
        self.fatigue = min(1.0, self.fatigue + dt * 0.01 * activity_level)

    def consume(self, food: float = 0.0, water: float = 0.0, rest: float = 0.0):
        """Consume resources to reduce drives."""
        self.hunger = max(0.0, self.hunger - food * 0.8)
        self.thirst = max(0.0, self.thirst - water * 0.8)
        self.fatigue = max(0.0, self.fatigue - rest * 0.9)

    def dominant_drive(self) -> Tuple[str, float]:
        """Return the strongest homeostatic drive."""
        drives = [("hunger", self.hunger), ("thirst", self.thirst), ("fatigue", self.fatigue)]
        drives.sort(key=lambda x: -x[1])
        return drives[0]

    def all_drives(self) -> Dict:
        return {
            'hunger': round(self.hunger, 4),
            'thirst': round(self.thirst, 4),
            'fatigue': round(self.fatigue, 4)
        }
