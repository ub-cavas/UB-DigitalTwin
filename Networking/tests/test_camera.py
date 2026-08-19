"""Mocked-CARLA and pygame tests for the DT-11 local ego camera."""

from __future__ import annotations

import unittest

from station.camera import CHASE_VIEW, DRIVER_VIEW, EgoCamera


class FakeLocation:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeRotation:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeTransform:
    def __init__(self, location, rotation=None):
        self.location = location
        self.rotation = rotation or FakeRotation()


class FakeAttachmentType:
    SpringArmGhost = "spring-arm-ghost"
    Rigid = "rigid"


class FakeCarla:
    Location = FakeLocation
    Rotation = FakeRotation
    Transform = FakeTransform
    AttachmentType = FakeAttachmentType


class FakeBlueprint:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, name, value):
        self.attributes[name] = value


class FakeSensor:
    def __init__(self):
        self.callback = None
        self.stopped = False
        self.destroyed = False

    def listen(self, callback):
        self.callback = callback

    def emit(self, image):
        self.callback(image)

    def stop(self):
        self.stopped = True

    def destroy(self):
        self.destroyed = True


class FakeWorld:
    def __init__(self):
        self.blueprint = FakeBlueprint()
        self.spawn_calls = []

    def get_blueprint_library(self):
        return type("Library", (), {"find": lambda library_self, name: self.blueprint})()

    def spawn_actor(self, blueprint, transform, **kwargs):
        sensor = FakeSensor()
        self.spawn_calls.append((blueprint, transform, kwargs, sensor))
        return sensor


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
    def __getitem__(self, key):
        return False


class FakeDisplay:
    def __init__(self):
        self.caption = None
        self.mode = None
        self.fills = []
        self.blits = []
        self.flips = 0

    def set_caption(self, value):
        self.caption = value

    def set_mode(self, value):
        self.mode = value
        return self

    def fill(self, color):
        self.fills.append(color)

    def blit(self, surface, position):
        self.blits.append((surface, position))

    def flip(self):
        self.flips += 1


class FakeFont:
    def __init__(self):
        self.rendered = []

    def render(self, text, antialias, color):
        self.rendered.append((text, antialias, color))
        return ("text", text)


class FakePygame:
    QUIT = 1
    KEYDOWN = 2
    K_ESCAPE = 3
    K_f = 4

    def __init__(self):
        self.event = FakeEventQueue()
        self._keys = FakeKeys()
        self.key = type("Key", (), {"get_pressed": lambda key_self: self._keys})()
        self.display = FakeDisplay()
        self.font_instance = FakeFont()
        self.font = type("FontModule", (), {"Font": lambda font_self, name, size: self.font_instance})()
        self.image_calls = []
        self.image = type(
            "Image",
            (), {"frombuffer": lambda image_self, raw, size, fmt: self._frombuffer(raw, size, fmt)},
        )()
        self.initialized = False
        self.quit_called = False

    def _frombuffer(self, raw, size, fmt):
        self.image_calls.append((raw, size, fmt))
        return ("image", size, fmt)

    def init(self):
        self.initialized = True

    def quit(self):
        self.quit_called = True


class FakeImage:
    def __init__(self, width=1920, height=1080, raw_data=b"frame"):
        self.width = width
        self.height = height
        self.raw_data = raw_data


class EgoCameraTests(unittest.TestCase):
    def setUp(self):
        self.world = FakeWorld()
        self.ego = object()
        self.pygame = FakePygame()
        self.camera = EgoCamera(
            self.world,
            self.ego,
            carla_module=FakeCarla,
            pygame_module=self.pygame,
        )

    def test_start_configures_1080p_chase_sensor_and_renders_latest_frame(self):
        self.camera.start()

        blueprint, transform, kwargs, sensor = self.world.spawn_calls[0]
        self.assertEqual(self.pygame.display.mode, (1920, 1080))
        self.assertEqual(blueprint.attributes, {
            "image_size_x": "1920",
            "image_size_y": "1080",
            "fov": "90.0",
            "sensor_tick": "0.0",
        })
        self.assertEqual(self.camera.view, CHASE_VIEW)
        self.assertEqual(transform.location.x, -10.0)
        self.assertEqual(transform.location.z, 5.0)
        self.assertEqual(transform.rotation.pitch, -0.0)
        self.assertIs(kwargs["attach_to"], self.ego)
        self.assertEqual(kwargs["attachment_type"], FakeAttachmentType.SpringArmGhost)

        sensor.emit(FakeImage(raw_data=b"newest"))
        self.camera.render()

        self.assertEqual(self.pygame.image_calls, [(b"newest", (1920, 1080), "BGRA")])
        self.assertEqual(self.pygame.display.flips, 1)

    def test_waiting_state_toggle_and_close_destroy_only_camera_sensors(self):
        self.camera.start()
        first_sensor = self.world.spawn_calls[0][3]
        self.camera.render()
        self.assertIn("Waiting for camera frame…", self.pygame.font_instance.rendered[0][0])

        self.pygame.event.pending = [FakeEvent(self.pygame.KEYDOWN, self.pygame.K_f)]
        self.camera.pump_events()

        _, transform, kwargs, second_sensor = self.world.spawn_calls[1]
        self.assertEqual(self.camera.view, DRIVER_VIEW)
        self.assertTrue(first_sensor.stopped)
        self.assertTrue(first_sensor.destroyed)
        self.assertEqual(transform.location.x, 1.5)
        self.assertEqual(transform.location.z, 1.6)
        self.assertEqual(kwargs["attachment_type"], FakeAttachmentType.Rigid)

        self.camera.close()
        self.assertTrue(second_sensor.stopped)
        self.assertTrue(second_sensor.destroyed)
        self.assertTrue(self.pygame.quit_called)

    def test_telemetry_overlay_formats_unknown_and_live_values(self):
        camera = EgoCamera(
            self.world,
            self.ego,
            carla_module=FakeCarla,
            pygame_module=self.pygame,
            telemetry_provider=lambda: {
                "rtt_ms": 42.25,
                "jitter_ms": 3.5,
                "loss_pct": 1.25,
                "loss_total_pct": 0.5,
                "buffer_depth": 2,
            },
        )
        camera.start()
        camera.render()

        rendered = [text for text, _, _ in self.pygame.font_instance.rendered]
        self.assertIn("RTT 42.2 ms   Jitter 3.5 ms", rendered)
        self.assertIn("Loss 1.2% (5s) / 0.5% total", rendered)
        self.assertIn("Buffer 2 samples", rendered)

        unknown_camera = EgoCamera(
            self.world,
            self.ego,
            carla_module=FakeCarla,
            pygame_module=FakePygame(),
        )
        unknown_camera.start()
        unknown_camera.render()
        unknown_rendered = [
            text for text, _, _ in unknown_camera.pygame.font_instance.rendered
        ]
        self.assertIn("RTT —   Jitter —", unknown_rendered)
        self.assertIn("Loss — (5s) / — total", unknown_rendered)
        self.assertIn("Buffer —", unknown_rendered)
        camera.close()
        unknown_camera.close()

    def test_escape_and_window_close_request_shutdown(self):
        self.camera.start()
        self.pygame.event.pending = [FakeEvent(self.pygame.KEYDOWN, self.pygame.K_ESCAPE)]
        self.camera.pump_events()
        self.assertTrue(self.camera.quit_requested)

        other = EgoCamera(self.world, self.ego, carla_module=FakeCarla, pygame_module=FakePygame())
        other.start()
        other.pygame.event.pending = [FakeEvent(other.pygame.QUIT)]
        other.pump_events()
        self.assertTrue(other.quit_requested)
        other.close()


if __name__ == "__main__":
    unittest.main()
