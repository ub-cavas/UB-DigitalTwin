"""Unit tests for the keyboard-only DT-19 synthetic station feed."""

from __future__ import annotations

import unittest

from harness.publisher import constant_velocity_trajectory
from station.synthetic_feed import (
    HARSH_PROFILE,
    METRO_PROFILE,
    NO_IMPAIRMENT,
    SyntheticPuppetFeed,
    place_trajectory,
)


class FakeEvent:
    def __init__(self, event_type, key):
        self.type = event_type
        self.key = key


class FakePygame:
    KEYDOWN = 1
    K_0 = 10
    K_m = 11
    K_h = 12


class SyntheticPuppetFeedTests(unittest.TestCase):
    def test_placed_trajectory_rotates_and_translates_pose_and_velocity(self):
        trajectory = place_trajectory(
            constant_velocity_trajectory,
            origin_x=10.0,
            origin_y=20.0,
            origin_z=1.0,
            heading_yaw_deg=90.0,
        )

        state = trajectory(2.0)

        self.assertAlmostEqual(state["pos_x"], 10.0)
        self.assertAlmostEqual(state["pos_y"], 50.0)
        self.assertAlmostEqual(state["pos_z"], 1.0)
        self.assertAlmostEqual(state["vel_x"], 0.0, places=5)
        self.assertAlmostEqual(state["vel_y"], 15.0)
        self.assertAlmostEqual(state["rot_y"], 90.0)

    def test_delivered_packet_sets_master_render_time_and_drains_once(self):
        feed = SyntheticPuppetFeed(constant_velocity_trajectory, profile=NO_IMPAIRMENT)
        try:
            packet = feed._trajectory(0.0)
            packet["master_frame_seq"] = 0
            from dtnet import wire

            feed._receive((wire.pack(packet), NO_IMPAIRMENT))

            self.assertEqual(len(feed.drain_packets()), 1)
            self.assertEqual(feed.drain_packets(), [])
            self.assertIsNotNone(feed.render_time())
        finally:
            feed.close()

    def test_keyboard_profile_shortcuts_select_live_profiles(self):
        feed = SyntheticPuppetFeed(constant_velocity_trajectory, profile=NO_IMPAIRMENT)
        pygame = FakePygame()
        try:
            feed.handle_pygame_input([FakeEvent(pygame.KEYDOWN, pygame.K_m)], pygame)
            self.assertEqual(feed.profile, METRO_PROFILE)
            feed.handle_pygame_input([FakeEvent(pygame.KEYDOWN, pygame.K_h)], pygame)
            self.assertEqual(feed.profile, HARSH_PROFILE)
            feed.handle_pygame_input([FakeEvent(pygame.KEYDOWN, pygame.K_0)], pygame)
            self.assertEqual(feed.profile, NO_IMPAIRMENT)
        finally:
            feed.close()


if __name__ == "__main__":
    unittest.main()
