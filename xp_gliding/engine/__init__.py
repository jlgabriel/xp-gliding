"""Atmospheric engine: pure Python, deterministic, never imports `xp`.

Modules:
  geo        local east-north-up frame and lat/lon conversion
  rng        portable deterministic random numbers (splitmix64)
  updraft    Allen (2006) updraft model for a single thermal
  field      deterministic thermal field with life cycle and spatial grid
  injection  energy-based lift force, sample geometry and gust roll moment
"""
