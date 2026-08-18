"""harness: test-only tools. No CARLA dependency anywhere in this package —
that's what makes W1 buildable before any CARLA integration exists.

Everything here is throwaway-adjacent but not actually thrown away: the
publisher and impairment injector are what week 3 swaps OUT, and the
visualizer is what proves dtnet/ works before station/ depends on it.
"""
