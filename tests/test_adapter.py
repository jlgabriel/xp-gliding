import math

import pytest

from xp_gliding.adapter import aircraft, config
from xp_gliding.adapter.clouds import MAX_BASES, CloudHeights
from xp_gliding.adapter.core import (AircraftState, Injection, Injector, NativeThermalGuard)
from xp_gliding.engine import injection as inj
from xp_gliding.engine.clouds import CloudParams, carries_cloud
from xp_gliding.engine.field import SKY_NAMES, Thermal, sky_named
from xp_gliding.engine.wind import AirDrift

# The wing parts of Laminar's ASK 21 (XP 12.4.3 ASK21.acf), lengths in feet.
ASK21_ACF = """\
P acf/_name Schleicher ASK 21
P _wing/0/_Croot 4.860000134
P _wing/0/_Ctip 1.799999952
P _wing/0/_part_x -1.200000048
P _wing/0/_part_z 9.699999809
P _wing/0/_semilen_SEG 26.700000763
P _wing/1/_Croot 4.860000134
P _wing/1/_Ctip 1.799999952
P _wing/1/_part_x 1.200000048
P _wing/1/_part_z 9.699999809
P _wing/1/_semilen_SEG 26.700000763
P _wing/2/_Croot 1.799999952
P _wing/2/_Ctip 1.340000033
P _wing/2/_part_x -27.778099060
P _wing/2/_part_z 8.768182755
P _wing/2/_semilen_SEG 0.500000000
P _wing/3/_Croot 1.799999952
P _wing/3/_Ctip 1.340000033
P _wing/3/_part_x 27.778099060
P _wing/3/_part_z 8.768182755
P _wing/3/_semilen_SEG 0.500000000
P _wing/8/_Croot 2.500000000
P _wing/8/_Ctip 1.399999976
P _wing/8/_part_x -0.000000000
P _wing/8/_part_z 24.649999619
P _wing/8/_semilen_SEG 5.099999905
P _wing/10/_Croot 4.050000191
P _wing/10/_part_x 0.000000000
P _wing/10/_part_z 24.350000381
P _wing/10/_semilen_SEG 5.099999905
"""

KHOB = (32.6875, -103.2170)


# --- aircraft geometry ----------------------------------------------------------

def test_ask21_geometry_from_its_acf_matches_the_real_glider():
    g = aircraft.geometry_from_parts(aircraft.parse_wing_parts(ASK21_ACF.splitlines()))
    assert g.span_m == pytest.approx(17.24, abs=0.01)  # real ASK 21: 17.0 m
    assert g.area_m2 == pytest.approx(17.75, abs=0.05)  # real: 17.95 m2
    assert g.taper == pytest.approx(0.37, abs=0.01)
    assert g.tail_arm_m == pytest.approx(4.56, abs=0.01)
    assert 16.0 < g.aspect_ratio < 17.5


def test_unreadable_acf_gives_none(tmp_path):
    assert aircraft.read_acf_geometry(str(tmp_path / "missing.acf")) is None
    empty = tmp_path / "empty.acf"
    empty.write_text("I\n1200 Version\nACF\n")
    assert aircraft.read_acf_geometry(str(empty)) is None


# --- settings ----------------------------------------------------------------------

def test_settings_coerce_types_and_ignore_unknown_keys():
    s = config.Settings({"wstar_ms": "2.5", "seed": 7.0, "enabled": 0, "bogus": 1,
                         "zi_m": "not a number"})
    assert s.wstar_ms == 2.5 and s.seed == 7 and s.enabled is False
    assert s.zi_m == config.DEFAULTS["zi_m"]


def test_missing_settings_file_is_created_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    s, how = config.load_settings(str(path))
    assert path.exists() and "written" in how
    assert s.as_dict() == config.DEFAULTS
    path.write_text('{"wstar_ms": 2.0}')
    s, how = config.load_settings(str(path))
    assert s.wstar_ms == 2.0 and s.zi_m == config.DEFAULTS["zi_m"]
    path.write_text("[1, 2")
    s, how = config.load_settings(str(path))
    assert s.as_dict() == config.DEFAULTS and "unreadable" in how


# --- injector ----------------------------------------------------------------------

def state(lat=KHOB[0], lon=KHOB[1], agl=800.0, tas=28.0, alpha=0.0, beta=0.0, psi=90.0,
          phi=0.0, mass=541.0, t=12 * 3600.0, day=305):
    s = AircraftState()
    s.lat, s.lon, s.agl_m, s.tas_ms = lat, lon, agl, tas
    s.alpha_deg, s.beta_deg, s.psi_deg, s.phi_deg = alpha, beta, psi, phi
    s.mass_kg, s.rho, s.sky_t_s, s.day = mass, 1.0, t, day
    return s


def injector(**settings):
    inj_ = Injector(config.Settings(settings), aircraft.DEFAULT_GEOMETRY)
    return inj_


def run(inj_, s):
    inj_.slow_update(s)
    return inj_.step(s, Injection())


def test_the_sky_is_carried_by_the_wind_at_the_clouds_only_when_asked():
    def flown(**settings):
        inj_ = injector(**settings)
        inj_.sky_wind = (9.0, 0.0)  # at the clouds: it must not matter with the setting off
        s = state()
        s.wind_x_ms = 5.0
        for k in range(11):
            s.sky_t_s = 1000.0 + k
            inj_.carry(s)
        return inj_.drift.dlon_deg

    glider, clouds = flown(), flown(wind_at_clouds=True)
    assert clouds / glider == pytest.approx(9.0 / 5.0)


def test_with_no_wind_at_the_clouds_read_yet_the_wind_at_the_glider_carries_the_sky():
    inj_ = injector(wind_at_clouds=True)
    s = state()
    s.wind_x_ms = 5.0
    s.sky_t_s = 1000.0
    inj_.carry(s)
    assert inj_.drift.wind_e_ms == 5.0


def test_the_wind_at_the_clouds_does_not_depend_on_the_glider_when_they_have_a_level():
    def wind(agl, msl):
        inj_ = injector(wind_at_clouds=True)
        s = state(agl=agl)
        inj_.sky_wind_update(s, [1000.0, 3000.0], [10.0, 30.0], [270.0, 270.0], msl, 2000.0)
        return inj_.sky_wind

    low, high = wind(300.0, 1400.0), wind(1400.0, 2500.0)
    assert low == high
    assert low[0] == pytest.approx(20.0 * 0.514444)
    assert low[1] == pytest.approx(0.0, abs=1e-9)


def test_uniform_lift_delivers_the_power_of_rising_air_forward():
    inj_ = injector()
    inj_.uniform_ms = 1.5
    s = state(tas=33.0)
    out = run(inj_, s)
    # Along the path at alpha = beta = 0: all forward, i.e. negative faxil.
    assert out.faxil_n == pytest.approx(-541.0 * inj.G * 1.5 / 33.0)
    assert out.fside_n == pytest.approx(0.0) and out.fnrml_n == pytest.approx(0.0)
    assert out.w_span == 1.5 and out.roll_nm == 0.0


def test_force_follows_the_air_relative_velocity():
    inj_ = injector()
    inj_.uniform_ms = 1.0
    out = run(inj_, state(alpha=6.0))
    # Nose above the velocity: the velocity points below the nose.
    assert out.fnrml_n < 0.0 and out.faxil_n < 0.0
    out = run(inj_, state(beta=4.0))
    # X-Plane's beta > 0: nose right of the path, so the velocity is to the left.
    assert out.fside_n < 0.0
    assert math.hypot(out.faxil_n, out.fside_n, out.fnrml_n) == pytest.approx(out.force_n)


def test_no_force_on_the_ground_or_with_thermals_off():
    inj_ = injector()
    inj_.uniform_ms = 1.0
    out = run(inj_, state(tas=5.0))
    assert out.force_n == 0.0 and out.faxil_n == 0.0
    inj_ = injector(thermals_enabled=False)
    out = run(inj_, state())
    assert out.force_n == 0.0 and out.roll_nm == 0.0


def test_more_lift_under_the_right_wing_rolls_left():
    inj_ = injector()
    inj_.debug_dwdy = 0.02
    out = run(inj_, state())
    assert out.roll_nm < 0.0  # X-Plane's L_plug_acf: positive rolls right
    inj_ = injector(roll_enabled=False)
    inj_.debug_dwdy = 0.02
    assert run(inj_, state()).roll_nm == 0.0


def find_thermal_state(inj_, s):
    """Put the aircraft over the core of the nearest thermal."""
    inj_.slow_update(s)
    near = inj_.nearest
    assert near.distance_m >= 0.0
    b = math.radians(near.bearing_deg)
    e, n = inj_.frame.to_enu(s.lat, s.lon)
    lat, lon = inj_.frame.to_latlon(e + near.distance_m * math.sin(b),
                                    n + near.distance_m * math.cos(b))
    return state(lat=lat, lon=lon, agl=s.agl_m, t=s.sky_t_s, day=s.day)


def test_thermal_field_gives_lift_in_a_core_and_is_deterministic():
    a = injector(seed=3)
    s = find_thermal_state(a, state())
    out_a = run(a, s)
    assert out_a.w_centre == pytest.approx(a.nearest.core_ms, abs=1e-9)
    b = injector(seed=3)
    out_b = run(b, s)
    assert out_b.w_span == out_a.w_span and out_b.faxil_n == out_a.faxil_n
    c = injector(seed=4)
    assert run(c, s).w_span != out_a.w_span


def test_the_sky_comes_from_the_settings_by_name():
    plain = injector()
    plain.slow_update(state())
    assert plain.field.config.sky is sky_named("default")
    wide = injector(sky="wide_carriers")
    wide.slow_update(state())
    assert wide.field.config.sky is sky_named("wide_carriers")
    # Changing it in flight rebuilds the field, as the seed does.
    wide.settings.sky = "default"
    wide.slow_update(state())
    assert wide.field.config.sky is sky_named("default")
    assert wide.sky_index == SKY_NAMES.index("default")
    assert injector(sky="medium_carriers").sky_index == SKY_NAMES.index("medium_carriers")
    # A name it does not know is the default sky, not a failure.
    other = injector(sky="nope")
    other.slow_update(state())
    assert other.field.config.sky is sky_named("default")


def test_lift_does_not_change_when_the_origin_moves():
    inj_ = injector(recentre_m=1000.0)
    s0 = state()
    inj_.slow_update(s0)
    origin = (inj_.frame.lat0, inj_.frame.lon0)
    far = state(lat=KHOB[0] + 0.03)  # ~3.3 km north
    s = find_thermal_state(inj_, far)
    assert (inj_.frame.lat0, inj_.frame.lon0) != origin
    moved = run(inj_, s).w_span
    fresh = injector()
    assert run(fresh, s).w_span == pytest.approx(moved, abs=1e-6)


def test_native_thermals_are_held_at_zero_and_restored():
    store = {"v": 0.62}
    guard = NativeThermalGuard(lambda: store["v"], lambda v: store.update(v=v), period_s=5.0)
    guard.want(True, 0.0)
    assert store["v"] == 0.0 and guard.saved == 0.62
    store["v"] = 1.0  # real weather rewrites it
    guard.want(True, 2.0)
    assert store["v"] == 1.0  # not checked every frame
    guard.want(True, 5.0)
    assert store["v"] == 0.0 and guard.saved == 1.0
    guard.want(False, 6.0)
    assert store["v"] == 1.0 and not guard.engaged


def test_helix_correction_rolls_out_of_a_climbing_turn():
    # Uniform lift in a left turn (yaw rate < 0): the energy force makes the glider
    # climb relative to the air, which would overbank it; the correction rolls right.
    inj_ = injector()
    inj_.uniform_ms = 2.0
    s = state(phi=-35.0)
    s.r_rad = -0.25
    out = run(inj_, s)
    assert out.dw_dy_helix == pytest.approx(2.0 * -0.25 / 28.0)
    assert out.roll_nm > 0.0
    s.r_rad = 0.25  # right turn: rolls left
    assert run(inj_, s).roll_nm < 0.0
    off = injector(helix_enabled=False)
    off.uniform_ms = 2.0
    assert run(off, s).roll_nm == 0.0


# --- how high each cloud is --------------------------------------------------------------------


class Ground:
    """A ground that counts its readings."""

    def __init__(self, height=1000.0):
        self.height = height
        self.reads = 0

    def __call__(self, lat, lon):
        self.reads += 1
        return self.height


def cloud_thermal(lat=-33.4, lon=-70.5, birth=1000.0):
    return Thermal(lat, lon, birth, birth + 1800.0, 2.0, 1.2)


def heights_over(ground, level=2000.0):
    heights = CloudHeights(ground, CloudParams())
    heights.level_m = level
    return heights


def test_a_cloud_stands_at_the_level_or_clear_of_the_ground():
    assert heights_over(Ground(1000.0)).base_m(cloud_thermal(), 1500.0, AirDrift()) == 2000.0
    assert heights_over(Ground(2500.0)).base_m(cloud_thermal(), 1500.0, AirDrift()) == 2800.0


def test_the_field_and_the_catalog_get_the_same_height_for_the_same_thermal():
    ground = Ground(2500.0)
    heights = heights_over(ground)
    first = heights.base_m(cloud_thermal(), 1500.0, AirDrift())
    reads = ground.reads
    assert reads >= 5
    ground.height = 900.0  # had it read again, the answer would change
    assert heights.base_m(cloud_thermal(), 1900.0, AirDrift()) == first
    assert ground.reads == reads
    assert heights.base_m(cloud_thermal(birth=1001.0), 1900.0, AirDrift()) == 2000.0  # another one


def test_a_thermal_with_no_cloud_goes_by_the_level_and_reads_no_ground():
    ground = Ground(2500.0)
    heights = heights_over(ground)
    blue = Thermal(-33.4, -70.5, 1000.0, 1100.0, 0.5, 0.6)  # weak, and short-lived
    assert not carries_cloud(blue, CloudParams())
    assert heights.base_m(blue, 1050.0, AirDrift()) == 2000.0
    assert heights.floor_m(blue, 1050.0, AirDrift(), 0.75, 2000.0) == 500.0
    assert ground.reads == 0


def test_a_floor_puts_the_cloud_at_the_skys_share_of_zi():
    heights = heights_over(Ground(2500.0))
    assert heights.floor_m(cloud_thermal(), 1500.0, AirDrift(), 0.75, 2000.0) == 2800.0 - 1500.0


def test_a_new_sky_forgets_every_height_and_says_so():
    ground = Ground(2500.0)
    heights = heights_over(ground)
    heights.base_m(cloud_thermal(), 1500.0, AirDrift())
    resets = heights.resets
    heights.reset()
    assert heights.level_m is None and heights.resets == resets + 1
    heights.level_m = 3000.0
    ground.height = 900.0
    assert heights.base_m(cloud_thermal(), 1500.0, AirDrift()) == 3000.0


def test_the_heights_do_not_grow_without_end():
    heights = heights_over(Ground(1000.0))
    drift = AirDrift()
    for k in range(MAX_BASES + 10):
        heights.base_m(cloud_thermal(birth=1000.0 + k), 1500.0, drift)
    assert len(heights._bases) <= MAX_BASES


def test_a_ground_not_loaded_is_counted_and_the_cloud_stays_at_the_level():
    heights = heights_over(lambda lat, lon: None)
    assert heights.base_m(cloud_thermal(), 1500.0, AirDrift()) == 2000.0
    assert heights.misses >= 5


def test_with_no_heights_the_injector_gives_no_floors_and_nothing_changes():
    injector = Injector(config.Settings(), aircraft.DEFAULT_GEOMETRY)
    s = AircraftState()
    s.lat, s.lon, s.agl_m, s.msl_m, s.tas_ms, s.mass_kg, s.t_zulu_s, s.t_local_s, s.sky_t_s, s.day = (
        -33.4, -70.5, 1400.0, 5000.0, 28.0, 541.0, 43200.0, 43200.0, 43200.0, 305)
    injector.slow_update(s)
    assert all(th.floor_m is None for th in injector.field.thermals())
    assert injector.nearest.floor_m == -1.0
    assert injector._ground(s) is None
