"""Atmospheric engine: pure Python, deterministic, never imports `xp`.

Modules:
  geo          local east-north-up frame and lat/lon conversion
  rng          portable deterministic random numbers (splitmix64)
  updraft      Allen (2006) updraft model for a single thermal
  field        deterministic thermal field with life cycle and spatial grid
  injection    energy-based lift force, sample geometry and gust roll moment
  wind         the sky carried by the wind, and thermals leaning with it
  sun          the sun's elevation: no sun, no thermals
  day          the cloud base from the atmosphere's layers
  clouds       which thermals carry a cumulus, and how it looks over its life
  cloud_order  the order the clouds are drawn in, near over far
  markers      training markers: which thermals, where and how bright
"""
