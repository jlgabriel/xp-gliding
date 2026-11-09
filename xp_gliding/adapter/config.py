"""Plugin settings: defaults, and an optional JSON file that overrides them.

The file is `Output/xp-gliding/config.json` under X-Plane's folder; it is
created with the defaults the first time the plugin starts. What the pilot chooses
in the menu is written back, so the next session starts from it. Changes made through
the `xp_gliding/...` datarefs, as the test pilot does, are not written by themselves.

Day parameters. The convective velocity scale w* and the mixed-layer depth zi (m above
ground) are fixed numbers. Allen's thermals stop about 10% below zi. With `weather_base_enabled`
(off by default, not flown yet) zi comes from the cloud base in X-Plane's weather instead, and
the setting is kept for when it is turned off (`core.Injector.zi_m`).

Pure Python: no `xp`.
"""

import json
import os

DEFAULTS = {
    "enabled": True,  # plugin effect on at start
    "thermals_enabled": True,  # our thermals (issue #30: off keeps the plugin loaded)
    "wind_enabled": True,  # XP12's wind carries the thermals, clouds and markers
    "lean_enabled": False,  # thermals lean with the wind's layers (a first guess, not flown)
    "wind_at_clouds": False,  # the sky moves with the wind at the clouds, not at the glider
    "sun_enabled": True,  # no sun, no thermals: none is born with the sun low (engine/sun.py)
    "roll_enabled": True,  # gust roll moment from the spanwise lift gradient
    "helix_enabled": True,  # cancel the climbing-turn overbanking of the energy force
    "markers_enabled": False,  # training mode: draw a ring and a column over nearby thermals
    "clouds_enabled": True,  # cumulus over the thermals that carry one
    "hud_enabled": True,  # soaring HUD: vario, netto, average, height to the top, centring aid
    "gliders_only": True,  # only act on gliders: filed as one, with no engines, or in also_gliders
    # Aircraft files (.acf names, any case) the pilot treats as gliders from the menu: motor
    # gliders, which their authors file as something else (filed as gliders, X-Plane tows them).
    "also_gliders": [],
    "wstar_ms": 3.0,  # convective velocity scale w* (m/s)
    "zi_m": 2000.0,  # convective layer depth zi (m AGL)
    "weather_base_enabled": False,  # zi from the cloud base in X-Plane's weather (notes/phase5.md)
    "seed": 1,  # field seed; with the date and place it fixes the sky
    "sky": "wide_carriers",  # a name in engine.field.SKIES; an unknown name is the narrow "default" sky
    "range_m": 10000.0,  # thermals are loaded this far around the aircraft
    "recentre_m": 20000.0,  # move the local origin when this far from it
}

# The menu's submenus: (title, setting, ((label, value), ...)). The values of the sky are
# names in engine.field.SKIES, and all of them are first guesses to judge by flying.
MENU_CHOICES = (
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
        """Apply known keys from a dict, coerced to the default's type; ignore the rest."""
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            kind = type(DEFAULTS[key])
            if kind is list:
                if isinstance(value, list) and all(isinstance(v, str) for v in value):
                    setattr(self, key, list(value))
                continue
            try:
                setattr(self, key, bool(value) if kind is bool else kind(value))
            except (TypeError, ValueError):
                pass

    def as_dict(self):
        return {key: getattr(self, key) for key in DEFAULTS}

    def treated_as_glider(self, acf):
        """True if the pilot chose to treat the aircraft file `acf` (its name) as a glider."""
        return acf.lower() in (name.lower() for name in self.also_gliders)

    def treat_as_glider(self, acf, wanted):
        """Add or remove the aircraft file `acf` (its name) in the list of aircraft treated as gliders."""
        others = [name for name in self.also_gliders if name.lower() != acf.lower()]
        self.also_gliders = others + [acf] if wanted else others


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
    return Settings(values), f"read from {path}"
