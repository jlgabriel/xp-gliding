"""Plugin settings: defaults, and an optional JSON file that overrides them.

The file is `Output/xp-gliding/config.json` under X-Plane's folder; it is
created with the defaults the first time the plugin starts. What the pilot chooses
in the menu is written back, so the next session starts from it. Changes made through
the `xp_gliding/...` datarefs, as the test pilot does, are not written by themselves.

Day parameters. The convective velocity scale w* and the mixed-layer depth zi (m above
ground) are fixed numbers. Allen's thermals stop about 10% below zi. With `weather_base_enabled`
(off by default, flown by hand 2026-11-09) zi comes from the cloud base in X-Plane's weather
instead, and the setting is kept for when it is turned off (`core.Injector.zi_m`).

The file is edited by hand too, so what it holds is checked (`Settings.update`): a value that is
not of its setting's kind, or not a finite number, is left out, and a number outside its LIMITS
is taken to the nearest end. Either way the log says so. A NaN in w* would reach the forces.

Pure Python: no `xp`.
"""

import json
import math
import os

from ..engine.field import SKIES

DEFAULTS = {
    "enabled": True,  # plugin effect on at start
    "thermals_enabled": True,  # our thermals (issue #30: off keeps the plugin loaded)
    "edge_enabled": True,  # sharper thermal edges: a kick on entry and exit, a sink ring, more sink
    "wind_enabled": True,  # XP12's wind carries the thermals, clouds and markers
    "lean_enabled": False,  # thermals lean with the wind's layers (a first guess, not flown)
    "wind_at_clouds": False,  # the sky moves with the wind at the clouds, not at the glider
    "sun_enabled": True,  # the daily cycle: none born with the sun low, w* follows the day (engine/daycycle.py)
    "areas_enabled": True,  # good and bad areas: the thermals' number and strength vary over tens of km
    "roll_enabled": True,  # gust roll moment from the spanwise lift gradient
    "helix_enabled": True,  # cancel the climbing-turn overbanking of the energy force
    "markers_enabled": False,  # training mode: draw a ring and a column over nearby thermals
    "clouds_enabled": True,  # cumulus over the thermals that carry one
    "blue_day": False,  # a blue day: the thermals that would carry a cloud climb as usual, with none
    "hud_enabled": True,  # soaring HUD: vario, netto, average, height to the top, centring aid
    "hud_units": "metric",  # a name in UNIT_NAMES: the HUD's vario in m/s and TOP in m, or knots and feet
    "gliders_only": True,  # only act on gliders: filed as one, with no engines, or in also_gliders
    # Aircraft files (.acf names, any case) the pilot treats as gliders from the menu: motor
    # gliders, which their authors file as something else (filed as gliders, X-Plane tows them).
    "also_gliders": [],
    "wstar_ms": 3.0,  # convective velocity scale w* (m/s)
    "zi_m": 2000.0,  # convective layer depth zi (m AGL)
    "weather_base_enabled": False,  # zi from the cloud base in X-Plane's weather (notes/phase5.md)
    "seed": 1,  # field seed; with the date and place it fixes the sky
    "sky": "wide_carriers",  # a name in engine.field.SKIES; another name is left out
    "range_m": 10000.0,  # thermals are loaded this far around the aircraft
    "recentre_m": 20000.0,  # move the local origin when this far from it
}

# The lowest and highest value config.json may give a number. w*: the menu goes to 5 m/s, and at 8
# the strongest core of the narrow sky reached 30 m/s offline. zi: below 1000 m the thermals are too
# narrow to climb in and too many to load; the top reaches past the weather's deepest (4667 m).
LIMITS = {
    "wstar_ms": (0.0, 6.0),
    "zi_m": (1000.0, 5000.0),
    "range_m": (2000.0, 30000.0),
    "recentre_m": (5000.0, 50000.0),
    "seed": (-2**31, 2**31 - 1),  # an int dataref
}

# The settings that take one of a few names. Another name is left out.
UNIT_NAMES = ("metric", "aviation")
NAMES = {"sky": tuple(SKIES), "hud_units": UNIT_NAMES}

# Named days: each sets the sky, the strength and depth of the day, and whether it is blue, which
# the submenus after it set one by one. First guesses, to judge by flying. With the weather's cloud
# base on, the depth set here waits until it is off.
DAYS = (
    ("Easy: wide, strong thermals", {"sky": "wide_carriers", "wstar_ms": 3.5, "zi_m": 2000.0, "blue_day": False}),
    ("Typical", {"sky": "wide_carriers", "wstar_ms": 3.0, "zi_m": 2000.0, "blue_day": False}),
    ("Demanding: narrower, stronger, higher", {"sky": "medium_carriers", "wstar_ms": 4.0, "zi_m": 2500.0,
                                               "blue_day": False}),
    ("Weak and low", {"sky": "wide_carriers", "wstar_ms": 2.0, "zi_m": 1500.0, "blue_day": False}),
    ("Blue: no clouds to read", {"sky": "wide_carriers", "wstar_ms": 3.0, "zi_m": 2000.0, "blue_day": True}),
)


def day_index(settings):
    """The place in DAYS of the day the settings make, or None if they make none of them."""
    return next((k for k, (_, values) in enumerate(DAYS)
                 if all(getattr(settings, key) == value for key, value in values.items())), None)


# The menu's submenus: (title, setting, ((label, value), ...)). "day" is not a setting: its values
# are places in DAYS. The values of the sky are names in engine.field.SKIES, and all of them are
# first guesses to judge by flying.
MENU_CHOICES = (
    ("Day", "day", tuple((label, k) for k, (label, _) in enumerate(DAYS))),
    ("Sky", "sky", (
        ("Wide thermals under the clouds (x2)", "wide_carriers"),
        ("Medium thermals under the clouds (x1.5)", "medium_carriers"),
        ("Narrow thermals, as the paper", "default"),
    )),
    ("Strength of the day (w*)", "wstar_ms", (
        ("2 m/s", 2.0), ("2.5 m/s", 2.5), ("3 m/s", 3.0), ("3.5 m/s", 3.5), ("4 m/s", 4.0), ("5 m/s", 5.0),
    )),
    ("Depth of the thermal layer (zi)", "zi_m", (
        ("1000 m", 1000.0), ("1500 m", 1500.0), ("2000 m", 2000.0), ("2500 m", 2500.0), ("3000 m", 3000.0),
    )),
    ("Seed of the sky", "seed", tuple((str(k), k) for k in range(1, 6))),
    ("Units on the HUD", "hud_units", (
        ("Metric: m/s and m", "metric"),
        ("Aviation: knots and feet", "aviation"),
    )),
)


class Settings:
    """Current settings; attributes named as in DEFAULTS."""

    __slots__ = tuple(DEFAULTS)

    def __init__(self, values=None):
        for key, default in DEFAULTS.items():
            setattr(self, key, list(default) if isinstance(default, list) else default)
        if values:
            self.update(values)

    def update(self, values):
        """Apply known keys from a dict, coerced to the default's kind and kept within LIMITS.

        Unknown keys are ignored. Returns what was left out or changed, one note per setting,
        for the log.
        """
        notes = []
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            checked = _checked(key, value)
            if checked is None:
                notes.append(f"{key} {value!r} left out")
                continue
            kept, moved = checked
            if moved:
                notes.append(f"{key} {value!r} taken to {kept!r}")
            setattr(self, key, kept)
        return notes

    def as_dict(self):
        return {key: getattr(self, key) for key in DEFAULTS}

    def treated_as_glider(self, acf):
        """True if the pilot chose to treat the aircraft file `acf` (its name) as a glider."""
        return acf.lower() in (name.lower() for name in self.also_gliders)

    def treat_as_glider(self, acf, wanted):
        """Add or remove the aircraft file `acf` (its name) in the list of aircraft treated as gliders."""
        others = [name for name in self.also_gliders if name.lower() != acf.lower()]
        self.also_gliders = others + [acf] if wanted else others


def _checked(key, value):
    """(value, moved) for a setting, moved if it had to be taken within LIMITS; None if the value
    cannot be one. Switches take true and false, or 1 and 0."""
    default = DEFAULTS[key]
    if isinstance(default, list):
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            return list(value), False
        return None
    if isinstance(default, bool):
        if isinstance(value, (bool, int)) and value in (0, 1):
            return bool(value), False
        return None
    if key in NAMES:
        return (value, False) if isinstance(value, str) and value in NAMES[key] else None
    try:
        number = type(default)(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    low, high = LIMITS.get(key, (number, number))
    kept = min(max(number, low), high)
    return kept, kept != number


def save_settings(settings, path):
    """Write the settings to the JSON file at path, whole or not at all. None, or what failed."""
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(settings.as_dict(), f, indent=2)
            f.write("\n")
        os.replace(temp, path)
    except OSError as exc:
        return f"could not write {path}: {exc}"
    return None


def load_settings(path):
    """Settings from the JSON file at path; write the defaults there if it is missing.

    Returns (settings, message) where message says what happened, for the log.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            values = json.load(f)
    except FileNotFoundError:
        settings = Settings()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(settings.as_dict(), f, indent=2)
                f.write("\n")
        except OSError as exc:
            return settings, f"defaults (could not write {path}: {exc})"
        return settings, f"defaults, written to {path}"
    except (OSError, ValueError) as exc:
        return Settings(), f"defaults ({path} unreadable: {exc})"
    if not isinstance(values, dict):
        return Settings(), f"defaults ({path} is not a JSON object)"
    settings = Settings()
    notes = settings.update(values)
    return settings, f"read from {path}" + "".join(f"; {note}" for note in notes)
