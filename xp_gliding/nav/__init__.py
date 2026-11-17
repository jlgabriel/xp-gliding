"""The Flight Computer's own arithmetic: pure Python, deterministic, tested outside X-Plane.

What `engine/` is to the thermals, `nav/` is to the Flight Computer. It never imports `xp`, and it
reads nothing of the engine: the Flight Computer shows what the glider can observe, never where
XP-Gliding knows its thermals are (tests/test_architecture.py checks both).
"""
