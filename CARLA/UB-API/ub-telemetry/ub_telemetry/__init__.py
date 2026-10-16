"""Shared telemetry transport for UB Digital Twin clients and servers.

This package owns the wire protocol described in docs/telemetry-protocol.md:
the message envelope, the message type registry, and the Redis pub/sub
plumbing. Every participant on the shared channel should depend on this
package rather than keeping its own copy.

``Telemetry`` and ``Logger`` import cleanly anywhere. The renderers need the
CARLA Python API, which is installed from a packaged CARLA build rather than
from PyPI, so import them from their submodules only where CARLA is present:

    from ub_telemetry.multi_agent_renderer import MultiAgentRenderer
    from ub_telemetry.multi_traffic_renderer import MultiTrafficRenderer
"""

from .logger import Logger
from .telemetry import Telemetry

MESSAGE_TYPES = Telemetry.MESSAGE_TYPES

__all__ = ["Logger", "Telemetry", "MESSAGE_TYPES"]

__version__ = "0.1.0"
