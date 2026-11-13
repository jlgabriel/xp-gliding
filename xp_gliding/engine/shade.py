"""Less lift under X-Plane's clouds, and none in rain.

The thermals are as strong as the sun heats the ground: w* = (g / theta * H * zi)^(1/3), the cube
root of the surface heat flux H times the depth zi (`daycycle.py`). X-Plane's own cloud layers
stand between the sun and the ground, so they take a share of H, and the w* in use is times the
cube root of what is left. X-Plane gives its layers at the aircraft (type and coverage, three
layers), not where each of its clouds is, so this is the same for every thermal around the
glider and changes as the weather changes from place to place: an area, not one cloud's shadow.
The plugin's own cumulus are not X-Plane's layers and do not count.

- Each layer shades by its coverage times a weight for its type (`TYPE_WEIGHT`, interpolated,
  since X-Plane blends types): cirrus is thin and lets most of the sun through, stratus and
  cumulonimbus very little. The layers combine as independent screens: the sky's cover is
  C = 1 - prod(1 - weight * coverage).
- The heat that reaches the ground is 1 - `MAX_LOSS` * C^2, so a few clouds cost little and a
  closed sky almost all of it: w* at about 92% of the clear sky's at C = 0.5, 79% at 0.75 and 46%
  under a closed overcast. Marked on purpose (Juan Luis, 2026-11-12): under a closed stratus deck
  thermals all but die. Kasten and Czeplak's formula for the light alone (1 - 0.75 C^3.4) would
  give 63% there, and real sensible heat falls further than the light does.
- In rain there are no thermals (`RAIN_OFF`, X-Plane's `region/rain_percent`): the ground is wet
  and cooled, and the air under a shower sinks.
- The ground does not heat or cool at once: the share follows its target with a time constant
  of `TAU_S` in sky time, so a change of weather takes a few minutes to be felt, and no sky
  starts over for it. A new flight or a jump starts it at its target.

All numbers are first guesses, to judge by flying. Pure Python: no `xp`.
"""

import math

TYPE_WEIGHT = (0.3, 1.0, 0.8, 1.0)  # cirrus, stratus, cumulus, cumulonimbus (X-Plane's 0-3)
MAX_LOSS = 0.9  # of the heat, under a sky closed by opaque cloud
RAIN_OFF = 0.05  # rain_percent above this: no thermals
TAU_S = 150.0  # the ground's response to a change of sky (s)


def type_weight(kind):
    """How much of the sun a layer of this type (X-Plane's blended 0-3) stops where it covers."""
    k = min(max(kind, 0.0), float(len(TYPE_WEIGHT) - 1))
    i = min(int(k), len(TYPE_WEIGHT) - 2)
    a = k - i
    return (1.0 - a) * TYPE_WEIGHT[i] + a * TYPE_WEIGHT[i + 1]


def sky_cover(kinds, coverages):
    """The share of the sun the layers stop, 0-1: each by its coverage and type, as screens."""
    clear = 1.0
    for kind, coverage in zip(kinds, coverages):
        c = min(max(coverage, 0.0), 1.0)
        if c > 0.0:
            clear *= 1.0 - type_weight(kind) * c
    return 1.0 - clear


def strength_share(kinds, coverages, rain):
    """w* under this sky over w* under a clear one, 0-1."""
    if rain > RAIN_OFF:
        return 0.0
    cover = sky_cover(kinds, coverages)
    return (1.0 - MAX_LOSS * cover * cover) ** (1.0 / 3.0)


class Shade:
    """The share of the moment, following its target over `TAU_S` of sky time."""

    __slots__ = ("share", "target", "_t")

    def __init__(self):
        self.share = 1.0
        self.target = 1.0
        self._t = None

    def reset(self):
        """Start again at the next target, as a new flight or a jump does."""
        self._t = None

    def step(self, target, t):
        """Move towards target (from `strength_share`) at sky time t (s). Returns the share."""
        self.target = target
        if self._t is None or t < self._t:
            self.share = target
        else:
            self.share += (target - self.share) * (1.0 - math.exp(-(t - self._t) / TAU_S))
        self._t = t
        return self.share
