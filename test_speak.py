#!/usr/bin/env python3
"""
test_speak.py — Unit tests for mew.speak (speed adjustment)

Run with:
    python3 -m pytest test_speak.py -v
    python3 -m pytest test_speak.py::TestAdjustSpeed -v
"""

import unittest

import numpy as np

from mew.speak import adjust_speed


def _sine(freq: float = 440.0, duration: float = 1.0, sr: int = 24_000) -> np.ndarray:
    """Generate a sine wave test signal."""
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    return np.sin(2 * np.pi * freq * t)


def _rms(signal: np.ndarray) -> float:
    return float(np.sqrt(np.mean(signal ** 2)))


class TestAdjustSpeed(unittest.TestCase):

    def test_speed_1_is_noop(self):
        """speed=1.0 should return the input array unchanged."""
        signal = _sine()
        result = adjust_speed(signal, 1.0)
        np.testing.assert_array_equal(result, signal)

    def test_speed_2_halves_length(self):
        signal = _sine(duration=1.0)
        result = np.asarray(adjust_speed(signal, 2.0), dtype=np.float32)
        expected_len = len(signal) // 2
        self.assertAlmostEqual(len(result), expected_len, delta=expected_len * 0.05)

    def test_speed_0_5_doubles_length(self):
        signal = _sine(duration=1.0)
        result = np.asarray(adjust_speed(signal, 0.5), dtype=np.float32)
        expected_len = len(signal) * 2
        self.assertAlmostEqual(len(result), expected_len, delta=expected_len * 0.05)

    def test_speed_3_thirds_length(self):
        signal = _sine(duration=1.0)
        result = np.asarray(adjust_speed(signal, 3.0), dtype=np.float32)
        expected_len = len(signal) // 3
        self.assertAlmostEqual(len(result), expected_len, delta=expected_len * 0.05)

    def test_output_not_silent_speedup(self):
        """Regression: speed > 1.0 must not produce silence."""
        signal = _sine(duration=1.0)
        input_rms = _rms(signal)
        for speed in [1.5, 2.0, 3.0]:
            result = np.asarray(adjust_speed(signal, speed), dtype=np.float32)
            output_rms = _rms(result)
            self.assertGreater(
                output_rms, input_rms * 0.5,
                f"speed={speed}: output RMS {output_rms:.4f} is too low "
                f"(input RMS {input_rms:.4f})",
            )

    def test_output_not_silent_slowdown(self):
        """Regression: speed < 1.0 must not produce silence."""
        signal = _sine(duration=1.0)
        input_rms = _rms(signal)
        for speed in [0.5, 0.75]:
            result = np.asarray(adjust_speed(signal, speed), dtype=np.float32)
            output_rms = _rms(result)
            self.assertGreater(
                output_rms, input_rms * 0.5,
                f"speed={speed}: output RMS {output_rms:.4f} is too low "
                f"(input RMS {input_rms:.4f})",
            )

    def test_output_not_silent_speech_like(self):
        """Use a multi-frequency signal that is more speech-like than a pure sine."""
        sr = 24_000
        t = np.linspace(0, 1.0, sr, dtype=np.float32)
        # Simulate a rough vocal spectrum: fundamental + harmonics with decay
        signal = (
            0.5 * np.sin(2 * np.pi * 150 * t)
            + 0.3 * np.sin(2 * np.pi * 300 * t)
            + 0.15 * np.sin(2 * np.pi * 450 * t)
            + 0.05 * np.sin(2 * np.pi * 600 * t)
        ).astype(np.float32)
        input_rms = _rms(signal)
        for speed in [0.5, 1.5, 2.0, 3.0]:
            result = np.asarray(adjust_speed(signal, speed), dtype=np.float32)
            output_rms = _rms(result)
            self.assertGreater(
                output_rms, input_rms * 0.5,
                f"speed={speed}: output RMS {output_rms:.4f} is too low "
                f"(input RMS {input_rms:.4f})",
            )


if __name__ == '__main__':
    unittest.main(verbosity=2)
