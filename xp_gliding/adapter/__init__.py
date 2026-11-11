"""XP12 adapter: the only part of XP-Gliding that talks to the X-Plane SDK.

Modules:
  aircraft  wing geometry of the user's aircraft, read from its .acf (no `xp`)
  config    settings and their JSON file (no `xp`)
  core      state -> forces, native thermal guard (no `xp`)
  markers   training markers: instances over nearby thermals (no `xp`)
  clouds    the cumulus: particle emitters over the thermals that carry one (no `xp`)
  vario     the HUD's instruments: total energy, netto, average, centring aid (no `xp`)
  hud       the soaring HUD's window and drawing (`xp`)
  xpio      dataref lookups, reads and writes, marker objects (`xp`)
  plugin    the XPPython3 plugin: flight loop, menu, commands, own datarefs (`xp`)
"""
