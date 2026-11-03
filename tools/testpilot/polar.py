"""Still-air polar of the Laminar ASK 21 measured in test A (docs/baseline.md).

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import math

# Sea-level sink (m/s) against IAS (km/h) at 541 kg, wings level.
POLAR_SL = ((77.0, 0.86), (80.0, 0.86), (90.0, 0.86), (100.0, 0.90), (120.0, 1.11),
            (140.0, 1.50))


def polar_sink(ias_kmh, tas_ms, bank_deg=0.0):
    """Still-air sink (m/s, positive down) at this IAS, TAS and bank: the
    sea-level sink scaled by TAS/IAS, and by n^1.5 = cos(bank)^-1.5 in a turn."""
    pts = POLAR_SL
    if ias_kmh <= pts[0][0]:
        sl = pts[0][1]
    elif ias_kmh >= pts[-1][0]:
        sl = pts[-1][1]
    else:
        for (v0, s0), (v1, s1) in zip(pts, pts[1:]):
            if v0 <= ias_kmh <= v1:
                sl = s0 + (s1 - s0) * (ias_kmh - v0) / (v1 - v0)
                break
    return sl * tas_ms / (ias_kmh / 3.6) * math.cos(math.radians(bank_deg)) ** -1.5
