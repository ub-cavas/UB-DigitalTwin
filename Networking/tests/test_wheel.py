"""Tests for the DT-24 keyboard latest-value input provider."""

from __future__ import annotations

import unittest

from station.wheel import WheelInput


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class FakeEvent:
    def __init__(self, event_type, key=None):
        self.type = event_type
        self.key = key


class FakeEventQueue:
    def __init__(self):
        self.pending = []

    def get(self):
        pending, self.pending = self.pending, []
        return pending


class FakeKeys:
    def __init__(self):
        self.pressed = set()

    def __getitem__(self, key):
        return key in self.pressed


class FakePygame:
    QUIT = 1
    KEYDOWN = 2
    K_ESCAPE = 3
    K_q = 4
    K_w = 5
    K_UP = 6
    K_s = 7
    K_DOWN = 8
    K_a = 9
    K_LEFT = 10
    K_d = 11
    K_RIGHT = 12
    K_SPACE = 13

    def __init__(self):
        self.event = FakeEventQueue()
        self._keys = FakeKeys()
        self.key = type("Key", (), {"get_pressed": lambda key_self: self._keys})()
        self.display = type(
            "Display", (),
            {
                "set_caption": lambda display_self, value: None,
                "set_mode": lambda display_self, value: value,
            },
        )()
        self.initialized = False
        self.quit_called = False

    def init(self):
        self.initialized = True

    def quit(self):
        self.quit_called = True


class WheelInputTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.pygame = FakePygame()
        self.input = WheelInput(
            pygame_module=self.pygame,
            monotonic=self.clock.monotonic,
            poll_hz=100,
        )

    def test_keyboard_sample_publishes_smoothed_control(self):
        self.pygame._keys.pressed.update({self.pygame.K_w, self.pygame.K_d})

        self.input._poll_once()

        control = self.input.latest_control()
        self.assertGreater(control["throttle"], 0.0)
        self.assertGreater(control["steer"], 0.0)
        self.assertEqual(control["brake"], 0.0)
        self.assertEqual(control["gear"], 1)

    def test_brake_reverse_and_quit_events_are_published(self):
        self.pygame.event.pending = [
            FakeEvent(self.pygame.KEYDOWN, self.pygame.K_q),
            FakeEvent(self.pygame.KEYDOWN, self.pygame.K_ESCAPE),
        ]
        self.pygame._keys.pressed.update({self.pygame.K_s, self.pygame.K_SPACE})

        self.input._poll_once()

        control = self.input.latest_control()
        self.assertEqual(control["gear"], -1)
        self.assertEqual(control["throttle"], 0.0)
        self.assertEqual(control["brake"], 1.0)
        self.assertTrue(control["hand_brake"])
        self.assertTrue(self.input.quit_requested)

    def test_stale_samples_apply_safe_brake_without_blocking(self):
        self.input._poll_once()
        self.clock.now += 0.251

        self.assertEqual(
            self.input.latest_control(),
            {"throttle": 0.0, "brake": 1.0, "steer": 0.0, "gear": 1, "hand_brake": False},
        )

    def test_rejects_invalid_configuration(self):
        with self.assertRaisesRegex(ValueError, "poll_hz"):
            WheelInput(poll_hz=0, pygame_module=self.pygame)
        with self.assertRaisesRegex(ValueError, "stale_input_s"):
            WheelInput(stale_input_s=False, pygame_module=self.pygame)


if __name__ == "__main__":
    unittest.main()
