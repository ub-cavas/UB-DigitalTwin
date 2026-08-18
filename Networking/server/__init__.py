"""server: the world master. One process, one authority for background traffic.

Depends on dtnet/. Never imports station/ or harness/.
Runs headless (-RenderOffScreen or -nullrhi per the W1 spike finding).
"""
