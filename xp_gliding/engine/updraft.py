"""Allen (2006) updraft model for one thermal.

Source: M. J. Allen, "Updraft Model for Development of Autonomous Soaring
Uninhabited Air Vehicles", AIAA 2006-1510, 44th AIAA Aerospace Sciences
Meeting, Reno, 2006 (NASA NTRS 20060004052). Equation numbers below are the
paper's. The equations were transcribed from the paper and its Appendix B
MATLAB code; where the two disagree the code is used, because the paper's
check case (its Fig. 12) was produced with it:

- Table 3 prints a "k4" column (0.0008, 0.0005, ...) that the code does not
  use. The code's k4 is a different column (-0.1950, -0.1265, ...), which makes
  the bell reach zero near r = r2. Small rounding differences in k2 (4.8354 vs
  4.8356, 42.797 vs 42.7965) also follow the code.

Inputs are the convective scales of the day: w* (convective velocity scale,
m/s) and zi (convective mixing-layer thickness, m AGL), and the height z above
ground. Typical values from the paper (Desert Rock, Nevada, 2002): mean
w* = 2.56 m/s with zi = 1401 m; +2 sigma w* = 5.02 m/s with zi = 3647 m.

What the model says (worth knowing before tuning by feel):
- Mean updraft (Eq. 11) peaks at 0.45 w* near z/zi = 0.25 and is negative
  above z/zi ~ 0.91: thermals stop short of zi.
- The ring of sink around the core exists only for 0.5 < z/zi < 0.9 (Eqs.
  17-18) and is weak (~ -0.1 m/s for the mean case). Below mid height the only
  sink is the uniform environment sink (Eq. 21).

Two deliberate deviations, both to avoid jumps in lift that a pilot would feel
as unphysical bumps (each can be switched off to reproduce the paper exactly):
- `blend_shapes`: the code picks the nearest row of the shape table, so the
  profile jumps when r2 (which grows with height) crosses a row boundary. By
  default the two neighbouring shapes are blended linearly in r1/r2.
- `stretch_everywhere`: the code stretches the profile toward the environment
  sink (Eq. 23) only outside the core radius r1, which leaves a small step at
  r1. Applying the stretch at every radius keeps the centre value unchanged
  (the stretch is exactly wc at r = 0) and removes the step.
"""

import math

# Shape table, Appendix B (r1/r2 rows; k1, k2, k3, k4 as used in Eq. 16).
SHAPE_R1R2 = (0.14, 0.25, 0.36, 0.47, 0.58, 0.69, 0.80)
SHAPE_K = (
    (1.5352, 2.5826, -0.0113, -0.1950),
    (1.5265, 3.6054, -0.0176, -0.1265),
    (1.4866, 4.8356, -0.0320, -0.0818),
    (1.2042, 7.7904, 0.0848, -0.0445),
    (0.8816, 13.9720, 0.3404, -0.0216),
    (0.7067, 23.9940, 0.5689, -0.0099),
    (0.6189, 42.7965, 0.7157, -0.0033),
)

MIN_OUTER_RADIUS_M = 10.0  # Appendix B: "limit small updrafts to 20m diameter"
DOWNDRAFT_LIMIT_RR2 = 2.0  # Eq. 17: the ring extends out to 2 r2


def mean_outer_radius(zzi, zi):
    """Eq. 12 without the minimum: mean outer radius r2 (m) at height ratio z/zi."""
    return 0.102 * zzi ** (1.0 / 3.0) * (1.0 - 0.25 * zzi) * zi


def mean_updraft(zzi, wstar):
    """Eq. 11: average updraft velocity (m/s) at height ratio z/zi."""
    return zzi ** (1.0 / 3.0) * (1.0 - 1.1 * zzi) * wstar


def core_ratio(r2):
    """Eq. 13: core-to-outer radius ratio r1/r2."""
    return 0.0011 * r2 + 0.14 if r2 < 600.0 else 0.8


def peak_updraft(wbar, r1, r2):
    """Eq. 15: centre velocity of the revolved trapezoid with mean wbar."""
    return 3.0 * wbar * (r2 ** 3 - r2 ** 2 * r1) / (r2 ** 3 - r1 ** 3)


def _bell_row(rr2, row):
    k1, k2, k3, k4 = SHAPE_K[row]
    ws = 1.0 / (1.0 + (k1 * abs(rr2 + k3)) ** k2) + k4 * rr2
    return ws if ws > 0.0 else 0.0


def bell(rr2, r1r2, blend_shapes=True):
    """Eq. 16 shape (without wD): normalized velocity at r/r2, 1 near the centre."""
    if not blend_shapes:
        # Appendix B: nearest row, boundaries at the midpoints between rows.
        row = len(SHAPE_R1R2) - 1
        for i in range(len(SHAPE_R1R2) - 1):
            if r1r2 < 0.5 * (SHAPE_R1R2[i] + SHAPE_R1R2[i + 1]):
                row = i
                break
        return _bell_row(rr2, row)
    if r1r2 <= SHAPE_R1R2[0]:
        return _bell_row(rr2, 0)
    if r1r2 >= SHAPE_R1R2[-1]:
        return _bell_row(rr2, len(SHAPE_R1R2) - 1)
    i = int((r1r2 - SHAPE_R1R2[0]) / (SHAPE_R1R2[1] - SHAPE_R1R2[0]))
    i = min(i, len(SHAPE_R1R2) - 2)
    a = (r1r2 - SHAPE_R1R2[i]) / (SHAPE_R1R2[i + 1] - SHAPE_R1R2[i])
    return (1.0 - a) * _bell_row(rr2, i) + a * _bell_row(rr2, i + 1)


def downdraft_ratio(zzi):
    """Eq. 18 scale factor swd: 0 below z/zi = 0.5, rising to 1 at 0.9."""
    return 2.5 * (zzi - 0.5) if 0.5 < zzi <= 0.9 else 0.0


def environment_sink(z, zi, wstar, density_per_m2):
    """Eq. 21: uniform sink between thermals from conservation of mass (m/s, <= 0).

    `density_per_m2` is the number of (full-strength, mean-size) updrafts per
    square metre. Allen derives it from Eq. 20 at the current height; a field
    of persistent thermals passes its own density instead.
    """
    if zi <= 0.0 or z <= 0.0 or z >= zi:
        return 0.0
    zzi = z / zi
    rbar = mean_outer_radius(zzi, zi)
    frac = density_per_m2 * math.pi * rbar * rbar
    if frac >= 1.0:
        raise ValueError("updrafts cover the whole area; density too high")
    we = -frac * mean_updraft(zzi, wstar) * (1.0 - downdraft_ratio(zzi)) / (1.0 - frac)
    return we if we < 0.0 else 0.0


def allen_density_per_m2(zi, zzi_ref=0.4):
    """Eq. 20: updrafts per square metre, N / (X Y) = 0.6 / (zi r2).

    Allen evaluates it at the aircraft height; Lenschow's spacing data behind
    Eq. 19 were taken at z/zi = 0.4, which is the default reference here for a
    field whose thermals do not change in number with height.
    """
    return 0.6 / (zi * mean_outer_radius(zzi_ref, zi))


def updraft_velocity(r, z, zi, wstar, wgain=1.0, rgain=1.0, we=0.0,
                     blend_shapes=True, stretch_everywhere=True):
    """Vertical air velocity (m/s, positive up) at distance r (m) from one updraft.

    z is the height above ground (m). wgain and rgain are this updraft's
    multipliers on mean strength and mean radius (Appendix B "perturbation
    gains"). we is the environment sink (Eq. 21, <= 0), or 0 for none.
    Far from the updraft (beyond 2 r2) the result is we.
    """
    if zi <= 0.0 or z <= 0.0 or z >= zi:
        return 0.0
    zzi = z / zi
    r2 = mean_outer_radius(zzi, zi) * rgain
    if r2 < MIN_OUTER_RADIUS_M:
        r2 = MIN_OUTER_RADIUS_M
    r1r2 = core_ratio(r2)
    r1 = r1r2 * r2
    wt = mean_updraft(zzi, wstar) * wgain
    wc = peak_updraft(wt, r1, r2)
    rr2 = r / r2

    ws = bell(rr2, r1r2, blend_shapes)

    # Eqs. 17-18: toroidal downdraft at the edge, only at upper heights.
    wd = 0.0
    swd = downdraft_ratio(zzi)
    if swd > 0.0 and r > r1 and rr2 < DOWNDRAFT_LIMIT_RR2:
        wd = swd * (math.pi / 6.0) * math.sin(math.pi * rr2)
        if wd > 0.0:
            wd = 0.0

    w2 = ws * wc + wd * wt
    # Eq. 23: stretch so the profile blends into the environment sink.
    if wc != 0.0 and (stretch_everywhere or r > r1):
        return w2 * (1.0 - we / wc) + we
    return w2


def influence_radius(z, zi, rgain=1.0):
    """Distance (m) beyond which an updraft only contributes the environment sink."""
    if zi <= 0.0 or z <= 0.0 or z >= zi:
        return 0.0
    r2 = max(MIN_OUTER_RADIUS_M, mean_outer_radius(z / zi, zi) * rgain)
    # The bell is zero by ~1.14 r2 in every row; the downdraft ends at 2 r2.
    return DOWNDRAFT_LIMIT_RR2 * r2
