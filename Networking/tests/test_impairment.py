"""Tests for the live-adjustable, asynchronous impairment injector."""

from __future__ import annotations

import threading
import time
import unittest

from harness.impairment import ImpairmentInjector


class FixedRandom:
    """A deterministic random source for exercising jitter and loss."""

    def __init__(self, random_value: float = 0.5, jitter_value: float = 0.0):
        self.random_value = random_value
        self.jitter_value = jitter_value

    def random(self) -> float:
        return self.random_value

    def uniform(self, lower: float, upper: float) -> float:
        return self.jitter_value


class ImpairmentInjectorTests(unittest.TestCase):
    def test_disabled_profile_delivers_synchronously(self) -> None:
        delivered = []
        with ImpairmentInjector(0, 0, 0) as injector:
            send = injector.wrap(delivered.append)
            send(b"packet")
        self.assertEqual(delivered, [b"packet"])

    def test_loss_drops_packets(self) -> None:
        delivered = []
        with ImpairmentInjector(0, 0, 100) as injector:
            injector.wrap(delivered.append)(b"packet")
        self.assertEqual(delivered, [])

    def test_delay_is_asynchronous_and_eventually_delivers(self) -> None:
        delivered = []
        delivered_event = threading.Event()

        def receive(packet):
            delivered.append(packet)
            delivered_event.set()

        with ImpairmentInjector(30, 0, 0) as injector:
            send = injector.wrap(receive)
            started = time.monotonic()
            send(b"packet")
            self.assertEqual(delivered, [])
            self.assertTrue(delivered_event.wait(0.5))
            self.assertGreaterEqual(time.monotonic() - started, 0.02)
        self.assertEqual(delivered, [b"packet"])

    def test_profile_changes_apply_to_future_packets(self) -> None:
        delivered = []
        with ImpairmentInjector(0, 0, 0) as injector:
            send = injector.wrap(delivered.append)
            send(b"before")
            injector.set_profile(0, 0, 100)
            send(b"after")
        self.assertEqual(delivered, [b"before"])

    def test_rejects_invalid_profiles_and_callbacks(self) -> None:
        invalid_profiles = [
            (-1, 0, 0),
            (0, -1, 0),
            (0, 0, -1),
            (0, 0, 101),
            (float("inf"), 0, 0),
        ]
        for profile in invalid_profiles:
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    ImpairmentInjector(*profile)

        with ImpairmentInjector() as injector:
            with self.assertRaises(TypeError):
                injector.wrap(None)


if __name__ == "__main__":
    unittest.main()
