"""Wing geometry of the user's aircraft, read from its .acf file.

The gust roll moment needs the span, wing area and taper, and the tail sample
needs the tail arm (SPEC "Sampling geometry"). The SDK exposes the wing parts
as `sim/aircraft/parts/acf_*[56]` arrays but not their positions, so the
geometry is read from the aircraft's own .acf file instead, which Plane Maker
writes as text lines `P <key> <value>` with lengths in feet.

Plane Maker's wing parts are `_wing/0` to `_wing/7` (wings 1-4, left and
right), `_wing/8`/`_wing/9` the horizontal stabilizer and `_wing/10`/`_wing/11`
the vertical fins. Every part has a root position (`_part_x` lateral,
`_part_z` longitudinal, positive aft), a semi-length and root and tip chords.

- span: twice the farthest wing-tip from the centre line (dihedral ignored);
- area: the planform of wings 1-4 plus the strip through the fuselage between
  the innermost roots, which is how published wing areas are quoted;
- taper: tip chord over root chord of the innermost wing;
- tail arm: from the innermost wing root to the horizontal stabilizer root.

Pure Python: no `xp`. If the file cannot be read (missing, encrypted, no wing),
`read_acf_geometry` returns None and the adapter uses DEFAULT_GEOMETRY.
"""

FT = 0.3048
MAIN_WINGS = range(0, 8)
HSTAB = (8, 9)
KEYS = ("_part_x", "_part_z", "_semilen_SEG", "_Croot", "_Ctip")


class WingGeometry:
    __slots__ = ("span_m", "area_m2", "taper", "tail_arm_m", "source")

    def __init__(self, span_m, area_m2, taper, tail_arm_m, source):
        self.span_m = span_m
        self.area_m2 = area_m2
        self.taper = taper
        self.tail_arm_m = tail_arm_m
        self.source = source

    @property
    def aspect_ratio(self):
        return self.span_m * self.span_m / self.area_m2

    def __repr__(self):
        return (f"WingGeometry(span {self.span_m:.2f} m, area {self.area_m2:.2f} m2, "
                f"AR {self.aspect_ratio:.1f}, taper {self.taper:.2f}, "
                f"tail arm {self.tail_arm_m:.2f} m, from {self.source})")


# Schleicher ASK 21 (published span and area; taper and tail arm from Laminar's model).
DEFAULT_GEOMETRY = WingGeometry(17.0, 17.95, 0.37, 4.6, "ASK 21 defaults")


def parse_wing_parts(lines):
    """{part index: {key: value}} for the `P _wing/N/<key> value` lines."""
    parts = {}
    for line in lines:
        if not line.startswith("P _wing/"):
            continue
        fields = line.split()
        if len(fields) != 3:
            continue
        path = fields[1].split("/")
        if len(path) != 3 or path[2] not in KEYS:
            continue
        try:
            index, value = int(path[1]), float(fields[2])
        except ValueError:
            continue
        parts.setdefault(index, {})[path[2]] = value
    return parts


def geometry_from_parts(parts, source=""):
    wings = [p for i, p in parts.items()
             if i in MAIN_WINGS and p.get("_semilen_SEG", 0.0) > 0.0]
    if not wings:
        return None
    span_ft = 2.0 * max(abs(p.get("_part_x", 0.0)) + p["_semilen_SEG"] for p in wings)
    area_ft2 = sum(p["_semilen_SEG"] * 0.5 * (p.get("_Croot", 0.0) + p.get("_Ctip", 0.0))
                   for p in wings)
    inner = min(wings, key=lambda p: abs(p.get("_part_x", 0.0)))
    root_chord = inner.get("_Croot", 0.0)
    # The two innermost roots are mirror images; the fuselage strip is counted once.
    area_ft2 += 2.0 * abs(inner.get("_part_x", 0.0)) * root_chord
    if span_ft <= 0.0 or area_ft2 <= 0.0 or root_chord <= 0.0:
        return None
    taper = inner.get("_Ctip", 0.0) / root_chord
    stabs = [parts[i] for i in HSTAB if parts.get(i, {}).get("_semilen_SEG", 0.0) > 0.0]
    if stabs:
        tail_arm_ft = stabs[0].get("_part_z", 0.0) - inner.get("_part_z", 0.0)
    else:
        tail_arm_ft = DEFAULT_GEOMETRY.tail_arm_m / FT
    return WingGeometry(span_ft * FT, area_ft2 * FT * FT, taper, max(tail_arm_ft * FT, 1.0),
                        source)


def read_acf_geometry(path):
    """WingGeometry of the .acf at `path`, or None if it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return geometry_from_parts(parse_wing_parts(f), path)
    except OSError:
        return None
