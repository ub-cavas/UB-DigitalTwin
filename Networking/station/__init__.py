"""station: the wheel station. Permanently a desktop app — display, pygame,
and local GPU are all expected here. (Unlike server/, no headless
constraint applies to this package.)

Depends on dtnet/. Never imports server/ directly — talks to it only over
the wire, so it can be pointed at harness.publisher or server.relay
interchangeably.
"""
