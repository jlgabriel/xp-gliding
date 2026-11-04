"""Plugin settings: defaults, and an optional JSON file that overrides them.

The file is `Output/xp-gliding/config.json` under X-Plane's folder; it is
created with the defaults the first time the plugin starts, so the user can
see and edit them. Changes made in flight (through the `xp_gliding/...`
datarefs or the menu) are not written back: the file is the starting point of
every session.

Day parameters. Until phase 2 reads them from XP12's atmosphere, the
convective velocity scale w* and the mixed-layer depth zi (m above ground)
are fixed numbers. Allen's thermals stop about 10% below zi.

Pure Python: no `xp`.
"""

import json

DEFAULTS = {
    "enabled": True,  # plugin effect on at start
    "thermals_enabled": True,  # our thermals (issue #30: off keeps the plugin loaded)
    "roll_enabled": True,  # gust roll moment from the spanwise lift gradient
    "helix_enabled": True,  # cancel the climbing-turn overbanking of the energy force
    "markers_enabled": False,  # training mode: draw a ring and a column over nearby thermals
    "gliders_only": True,  # only act on aircraft without engines
    "wstar_ms": 3.0,  # convective velocity scale w* (m/s)
    "zi_m": 2000.0,  # convective layer depth zi (m AGL)
    "seed": 1,  # field seed; with the date and place it fixes the sky
    "range_m": 10000.0,  # thermals are loaded this far around the aircraft
    "recentre_m": 20000.0,  # move the local origin when this far from it
}


class Settings:
    """Current settings; attributes named as in DEFAULTS."""

    __slots__ = tuple(DEFAULTS)

    def __init__(self, values=None):
        for key, default in DEFAULTS.items():
            setattr(self, key, default)
        if values:
            self.update(values)

    def update(self, values):
        """Apply known keys from a dict, coerced to the default's type; ignore the rest."""
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            kind = type(DEFAULTS[key])
            try:
                setattr(self, key, bool(value) if kind is bool else kind(value))
            except (TypeError, ValueError):
                pass

    def as_dict(self):
        return {key: getattr(self, key) for key in DEFAULTS}


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
