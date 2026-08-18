"""station.wheel — 100 Hz+ input thread, latest-value slot.

One job: read the wheel/pedals and keep a single up-to-date control value
that station.main's sim loop reads and applies via apply_control(). Never
let the input read block or live inside the tick path.

Forked from manual_control_steeringwheel.py — keep the axis mapping and
the logarithmic pedal curve from _parse_vehicle_wheel(), that's the part
worth preserving even though the surrounding module is being rewritten.
"""


class WheelInput:
    def __init__(self, device_index: int = 0):
        raise NotImplementedError

    def start(self) -> None:
        """Start the 100 Hz+ read thread."""
        raise NotImplementedError

    def latest_control(self) -> dict:
        """Non-blocking read of {throttle, brake, steer, gear} — the latest-value slot."""
        raise NotImplementedError
