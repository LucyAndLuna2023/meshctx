"""v3.95 Auto-Tuner tests"""
import pytest
from src.core.auto_tuner import AutoTuner, PIDController, PIDParams, ABTest, get_auto_tuner


class TestPIDParams:
    def test_default(self):
        p = PIDParams()
        assert p.kp == 1.0

    def test_custom(self):
        p = PIDParams(kp=2.0, ki=0.5, kd=0.1)
        assert p.kp == 2.0


class TestPIDController:
    def test_compute(self):
        pid = PIDController(PIDParams(setpoint=100))
        output = pid.compute(50)
        assert output > 0

    def test_convergence(self):
        pid = PIDController(PIDParams(setpoint=50, kp=2.0, ki=0.5, kd=0.1))
        outputs = []
        for _ in range(20):
            outputs.append(pid.compute(30))
        assert outputs[-1] < outputs[0] * 0.8


class TestAutoTuner:
    def test_record_metric(self):
        tuner = AutoTuner()
        adj = tuner.record_metric("cpu", 80, 50)
        assert isinstance(adj, float)

    def test_auto_tune(self):
        tuner = AutoTuner()
        adj, params = tuner.auto_tune("memory", 90, 75)
        assert isinstance(params, PIDParams)

    def test_trend_insufficient(self):
        tuner = AutoTuner()
        assert tuner.get_trend() == "insufficient_data"

    def test_trend_improving(self):
        tuner = AutoTuner()
        for v in [100, 90, 80, 70, 60, 50]:
            tuner.record_metric("test", v, 0)
        assert tuner.get_trend() == "improving"

    def test_ab_test(self):
        tuner = AutoTuner()
        tuner.create_ab_test("test1", {"x": 1}, {"x": 2})
        for i in range(10):
            tuner.record_ab_result("test1", "a", float(10 - i))
            tuner.record_ab_result("test1", "b", float(5 - i))
        winner = tuner.get_ab_winner("test1")
        assert winner.winner == "a"

    def test_config_switch(self):
        tuner = AutoTuner()
        tuner.save_config("default")
        assert tuner.switch_config("default")
        assert not tuner.switch_config("nonexistent")


def test_singleton():
    a = get_auto_tuner()
    b = get_auto_tuner()
    assert a is b
