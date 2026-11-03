"""XP12 adapter: the only part of xp-gliding that talks to the X-Plane SDK.

Modules:
  aircraft  wing geometry of the user's aircraft, read from its .acf (no `xp`)
  config    settings and their JSON file (no `xp`)
  core      state -> forces, native thermal guard (no `xp`)
  xpio      dataref lookups, reads and writes (`xp`)
  plugin    the XPPython3 plugin: flight loop, menu, commands, own datarefs (`xp`)
"""
