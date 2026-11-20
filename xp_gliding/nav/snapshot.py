"""The state snapshot the Flight Computer's page draws: one JSON string, built a few times a second.

The adapter (`adapter/computer.py`) reads the simulator and the HUD's instruments, fills a dict
with the keys of FIELDS, and `snapshot_json` turns it into the string the page receives from
`xplane.xpg_state()`. The page only formats and draws: every number here is in SI units and
degrees true, whatever units the pilot chose (`units` names them, for the page).

A number that is not finite (a vario not settled yet, a division by a zero speed) goes out as
null, never as NaN, which is not JSON; so does a key the adapter left out. The page shows "--".

X-Plane's local axes, used by `track` and `wind_from`: x east, y up, z south.

Pure Python: no `xp`, nothing of the engine.
"""

import json
import math

# key -> decimals kept. Positions to about 0.1 m; the rest to what the page could ever show.
FIELDS = {
    "t": 2,  # sim running time (s)
    "local_s": 0,  # the simulator's local time of day (s since midnight), for the clock
    "lat": 6, "lon": 6,  # degrees
    "msl_m": 1, "agl_m": 1,
    "track_deg": 1, "heading_deg": 1,  # true
    "gs_ms": 2, "ias_ms": 2, "tas_ms": 2,
    "te_ms": 2,  # total energy vario
    "netto_ms": 2,  # the air's own movement; null where the aircraft has no polar
    "avg_ms": 2,  # 30 s average
    "thm_ms": 2,  # since circling began in this thermal
    "wind_from_deg": 1, "wind_ms": 2,  # X-Plane's wind at the glider
    "top_m": 1,  # up from the glider to the clouds, as the HUD's TOP; null with thermals off
    "aid_core_az_deg": 1, "aid_amp_ms": 2,  # the centring aid: where the stronger side is
    "thm_gain_m": 1,  # height gained in this thermal, null until it has an average
    "thm4_ms": 2,  # the climb of the last four thermals left, null before the first
    "ld": 1,  # E, the glide ratio achieved (nav/glide.py), null while it means nothing
    "vmg_ms": 2,  # the ground speed made good towards the target's route, null without a task
}
FLAGS = ("valid", "thm_valid", "thm_active", "circling", "aid_valid")
TEXTS = ("units", "view", "layout", "screen")  # layout: which computer; screen: the Glide Computer's
INTS = ("poll_hz", "track_n", "track_epoch",  # track_*: the track's points and epoch (nav/track.py)
        "task_rev", "tasks_rev")  # change when the task loaded, or the list of tasks, is new
OBJECTS = ("nav",)  # nav: the point flown to and what is left (nav/task.py, Progress.nav), or null
LISTS = ("keys",)  # keys: the page's last commands, [number, name], done once each by the page


def _number(value, decimals):
    if value is None:
        return None
    value = float(value)
    return round(value, decimals) if math.isfinite(value) else None


def snapshot_json(values):
    """The JSON string for the page, from a dict of the adapter's values (see FIELDS, FLAGS, TEXTS,
    INTS). Keys outside those are ignored; missing ones go out as null."""
    out = {key: _number(values.get(key), decimals) for key, decimals in FIELDS.items()}
    for key in FLAGS:
        out[key] = bool(values.get(key, False))
    for key in TEXTS:
        value = values.get(key)
        out[key] = value if isinstance(value, str) else None
    for key in INTS:
        value = values.get(key)
        out[key] = int(value) if isinstance(value, (int, float)) and math.isfinite(value) else None
    for key in OBJECTS:
        value = values.get(key)
        out[key] = _clean(value) if isinstance(value, dict) else None
    for key in LISTS:
        value = values.get(key)
        out[key] = _clean(value) if isinstance(value, list) else []
    return json.dumps(out, separators=(",", ":"), allow_nan=False)


def _clean(value):
    """A value inside one of OBJECTS or LISTS, at any depth: a number that is not finite becomes null."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def track(vx_ms, vz_ms):
    """(track in degrees true, ground speed in m/s) from the velocity on X-Plane's local axes.
    The track is None below 0.5 m/s, where it means nothing."""
    speed = math.hypot(vx_ms, vz_ms)
    if speed < 0.5:
        return None, speed
    return math.degrees(math.atan2(vx_ms, -vz_ms)) % 360.0, speed


def wind_from(wind_x_ms, wind_z_ms):
    """(direction the wind blows from, degrees true, speed m/s) from X-Plane's wind at the aircraft
    (`sim/weather/aircraft/wind_now_x_msc` and `_z_msc`: where the air goes). The direction is None
    below 0.5 m/s: calm, as the HUD shows it."""
    speed = math.hypot(wind_x_ms, wind_z_ms)
    if speed < 0.5:
        return None, speed
    going = math.degrees(math.atan2(wind_x_ms, -wind_z_ms))
    return (going + 180.0) % 360.0, speed
