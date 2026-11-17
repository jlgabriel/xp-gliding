"""The soaring HUD: a small panel on screen with the instruments of `vario`.

A flight loop of its own samples the aircraft ten times a second, updates the
instruments and formats the text, so nothing of this runs in the frames between.
A window in the flight overlay layer draws the result every frame, the shapes and
strings already made, in one of two ways:

- Panel Graphics (`PanelDrawer`), X-Plane 12.4.4's native 2D drawing, where both X-Plane 12.4.4
  and XPPython3 4.8.0 have it: the static part recorded once and replayed, the rest each frame,
  all text in TrueType. Measured on 2026-11-17 for a scene like this one: 26-33 us a draw.
- OpenGL (`GLDrawer`) everywhere else, and if Panel Graphics fails, to start or while drawing:
  then the HUD says so in the log and draws with OpenGL until X-Plane restarts. Under Vulkan
  X-Plane gives plugins an OpenGL context of their own, and drawing in a window is the supported
  way to use it. The static part is a GL display list; small text uses X-Plane's own font,
  because TrueType through xpgl costs ~18 us per glyph from Python, so only the big TE reading
  pays for it (433 us a draw for that same scene, 2026-11-17).

It never touches the forces, and a failure here only hides the panel: an
exception must not leave a draw callback, because XPPython3 stops calling it.

Units: the menu's *Units on the HUD* (`hud_units`) gives the vario in m/s and TOP in m, or in
knots and feet, as glider varios read where altitudes are in feet (Juan Luis, 2026-11-11). The
wind is in knots either way, as in X-Plane's weather settings. Only the text and the tape change:
everything is worked out in SI, and the datarefs stay in m/s.
AVG is the climb over the last 30 s; THM the climb since the glider began circling in this thermal,
greyed once it has left, until the next (`vario.ThermalAverage`).
TOP is how far the clouds are, up from the glider: to the nearest one drawn, or to the sky's level.
Plugins > XP-Gliding > Soaring HUD toggles it, as does the command `xp_gliding/hud/toggle`.
"""

import math
import time
import traceback

import xp

from ..engine.field import sky_named
from .vario import SAMPLE_PERIOD_S, CentringAid, ThermalAverage, Vario, height_to_top, polar_for

WIDTH, HEIGHT = 170, 300
MARGIN_LEFT, MARGIN_BOTTOM = 20, 300  # clear of the ASK 21's panel in the default view
TAPE_BOTTOM, TAPE_TOP = 12, HEIGHT - 12
TAPE_X = 8
AID_X, AID_Y, AID_RADIUS = 118, 52, 34
WIND_X, WIND_Y, WIND_RADIUS = 118, 122, 18  # the arrow, between the text and the centring aid
WIND_CALM_MS = 0.5  # below this there is no direction to show
KT_PER_MS = 1.0 / 0.514444
# Half-swing of the lift around a circle. On logged orbits of the test pilot it is 0.8-0.9 m/s
# even within 30 m of the core, where the direction means nothing, and 1.8 m/s or more once
# 30 m or more off centre. Below this the arrow stays hidden.
AID_MIN_AMP_MS = 1.2
AID_FULL_AMP_MS = 3.0
SOLVE_EVERY = 5  # samples between CentringAid solutions
FONT_BIG = "Resources/fonts/Roboto-Bold.ttf"
FONT_SMALL = "Resources/fonts/Roboto-Regular.ttf"  # Panel Graphics only: OpenGL uses X-Plane's own font
BIG_PX = 34.0
SMALL_PX = 12.0  # Roboto at 12 is about as wide as X-Plane's own font: 14 was 18 % wider (2026-11-17)
TEXT_X = 66  # the text's left edge
TE_Y = HEIGHT - 44  # the big number's baseline
TEXT_Y = HEIGHT - 70  # the first small line's
LINE_PX = 20
KT_TO_KMH = 1.852
FT_PER_M = 1.0 / 0.3048


class Units:
    """How the HUD shows a rate and a height: the tape's span and marks, the text's units."""

    __slots__ = ("per_ms", "tape", "major", "per_m", "height_step", "height_label")

    def __init__(self, per_ms, tape, major, per_m, height_step, height_label):
        self.per_ms = per_ms  # a rate shown, per m/s
        self.tape = tape  # the tape goes from -tape to +tape, a mark at each whole unit
        self.major = major  # a longer mark every so many
        self.per_m = per_m  # a height shown, per m
        self.height_step = height_step  # TOP is rounded to this
        self.height_label = height_label

    def height_text(self, height_m):
        step = self.height_step
        return f"{round(height_m * self.per_m / step) * step:+.0f} {self.height_label}"


# Knots: 10 kt is 5.1 m/s, so the tape spans about what it does in m/s. Feet are rounded to 10,
# since the last digit would turn over with every 30 cm of height.
UNITS = {
    "metric": Units(1.0, 5, 5, 1.0, 1, "m"),
    "aviation": Units(KT_PER_MS, 10, 5, FT_PER_M, 10, "ft"),
}

SCRIM = (0.0, 0.0, 0.0, 0.45)
WHITE = (1.0, 1.0, 1.0)
AMBER = (1.0, 0.75, 0.1)
GREEN = (0.3, 1.0, 0.45)
CYAN = (0.3, 0.85, 1.0)
# X-Plane draws text colours about squared (gamma 2.2: 0.65 showed as 0.38, so
# GREEN's 0.3 shows as 0.08): 0.82 shows as a mid grey, about 0.65.
GREY = (0.82, 0.82, 0.82)  # the last thermal's average, once the glider has left it


def tape_y(value, tape):
    """Height on a tape that spans -tape to +tape of a value in its own units, clamped to its ends."""
    v = max(-tape, min(tape, value))
    return TAPE_BOTTOM + (v + tape) / (2.0 * tape) * (TAPE_TOP - TAPE_BOTTOM)


def aid_arrow(core_az_deg, psi_deg, amp_ms):
    """The arrow's tip relative to the dial's centre: up is the nose, longer is more off centre."""
    angle = math.radians(core_az_deg - psi_deg)
    length = AID_RADIUS * (0.4 + 0.6 * min(amp_ms / AID_FULL_AMP_MS, 1.0))
    return length * math.sin(angle), length * math.cos(angle)


def wind_arrow(wind_x_ms, wind_z_ms, psi_deg):
    """The tip of the wind's arrow from its centre: up is the nose, and it points where the wind
    goes, so it turns as the glider circles. None when calm. X-Plane's local axes: x east, z south."""
    if math.hypot(wind_x_ms, wind_z_ms) < WIND_CALM_MS:
        return None
    angle = math.atan2(wind_x_ms, -wind_z_ms) - math.radians(psi_deg)
    return WIND_RADIUS * math.sin(angle), WIND_RADIUS * math.cos(angle)


class Hud:
    def __init__(self, settings, log):
        self.settings = settings
        self.log = log
        self.vario = Vario()
        self.aid = CentringAid(lag_s=self.vario.tau_s)
        self.thermal = ThermalAverage()
        self.eligible = False
        self.sample_us = 0.0
        self.draw_us = 0.0
        self.failed = False
        self.window = None
        self.drawer = None  # PanelDrawer or GLDrawer, made with the window
        self.prefer_panel = True  # False once Panel Graphics failed, or when asked for OpenGL
        self._rebuild = False  # a new window and drawer, asked anywhere, made by the next tick
        self.units = UNITS["metric"]
        self._samples = 0
        self._te_y = self._netto_y = self._average_y = tape_y(0.0, 1.0)
        self._arrow = None
        self._wind_arrow = None
        self._te_text = self._netto_text = self._average_text = self._top_text = ""
        self._wind_text = ""
        self._thermal_text = "THM --"
        self._thermal_color = WHITE
        self.top_msl_m = None  # where the clouds are, from the plugin's slow path
        self.zi_m = settings.zi_m  # the zi in use, from the plugin's slow path: maybe the weather's
        ref = xp.findDataRef
        self._time = ref("sim/time/total_running_time_sec")
        self._paused = ref("sim/time/paused")
        self._replay = ref("sim/time/is_in_replay")
        self._elevation = ref("sim/flightmodel/position/elevation")
        self._agl = ref("sim/flightmodel/position/y_agl")
        self._tas = ref("sim/flightmodel/position/true_airspeed")
        self._ias = ref("sim/flightmodel/position/indicated_airspeed")
        self._phi = ref("sim/flightmodel/position/phi")
        self._psi = ref("sim/flightmodel/position/psi")
        self._mass = ref("sim/flightmodel/weight/m_total")
        self._wind_x = ref("sim/weather/aircraft/wind_now_x_msc")
        self._wind_z = ref("sim/weather/aircraft/wind_now_z_msc")
        self.loop = xp.createFlightLoop(self.on_loop, xp.FlightLoop_Phase_AfterFlightModel, None)

    # --- life cycle ------------------------------------------------------------

    def enable(self):
        xp.scheduleFlightLoop(self.loop, SAMPLE_PERIOD_S, 1)

    def disable(self):
        xp.scheduleFlightLoop(self.loop, 0, 1)
        self._show(False)

    def stop(self):
        xp.destroyFlightLoop(self.loop)
        self._drop_drawing()

    def set_top(self, nearest_base_m, level_m):
        """The nearest drawn cloud's base (m MSL, -1: none), and the sky's level (None: no sky yet)."""
        self.top_msl_m = nearest_base_m if nearest_base_m >= 0.0 else level_m

    def set_aircraft(self, path, eligible):
        self.eligible = eligible
        self.vario.polar = polar_for(path)
        self.vario.has_netto = self.vario.polar is not None
        self.reset_instruments()
        self.top_msl_m = None

    def reset_instruments(self):
        """The glider jumped (a new flight, the map, the clock): what it did before says nothing
        about now. Seen 2026-11-07: a placement on the map left AVG at an impossible -7.7 m/s."""
        self.vario.reset()
        self.aid.reset()
        self.thermal.reset()

    def _load_drawing(self):
        """The window and what draws in it: Panel Graphics where X-Plane and XPPython3 have it,
        else OpenGL. A window's content type is fixed when it is made, so each drawer has its own."""
        drawer = None
        if self.prefer_panel and panel_graphics_available():
            try:
                drawer = PanelDrawer()
            except Exception:
                self.prefer_panel = False
                self.log("HUD: Panel Graphics failed to start, drawing with OpenGL:\n"
                         + traceback.format_exc())
        if drawer is None:
            drawer = GLDrawer()
        left, _, _, bottom = xp.getScreenBoundsGlobal()
        x, y = left + MARGIN_LEFT, bottom + MARGIN_BOTTOM
        # Named only for Panel Graphics: XPPython3 before 4.8.0 knows no contentType.
        extra = {"contentType": xp.WindowContentTypePanelGraphics} if drawer.panel else {}
        self.window = xp.createWindowEx(x, y + HEIGHT, x + WIDTH, y, 1, self.on_draw,
                                        decoration=xp.WindowDecorationNone,
                                        layer=xp.WindowLayerFlightOverlay, **extra)
        self.drawer = drawer
        self.log(f"HUD drawn with {drawer.name}")

    def _drop_drawing(self):
        if self.window is not None:
            xp.destroyWindow(self.window)
            self.window = None
        if self.drawer is not None:
            drawer, self.drawer = self.drawer, None
            try:
                drawer.release()
            except Exception:  # a drawer that failed may not free cleanly; the HUD goes on
                self.log(f"HUD: freeing its {drawer.name} drawing failed:\n" + traceback.format_exc())

    @property
    def panel_graphics(self):
        """1 while the HUD draws with Panel Graphics. Writing 0 moves it to OpenGL and 1 back, where
        X-Plane has Panel Graphics (dataref `xp_gliding/hud/panel_graphics`, for checks)."""
        return int(self.drawer is not None and self.drawer.panel)

    @panel_graphics.setter
    def panel_graphics(self, value):
        if bool(value) != self.prefer_panel:
            self.prefer_panel = bool(value)
            self._rebuild = True

    def _show(self, visible):
        if self.window is not None:
            xp.setWindowIsVisible(self.window, 1 if visible else 0)

    def _fail(self, where):
        self.failed = True
        self.log(f"HUD stopped, error in {where}:\n" + traceback.format_exc())

    # --- ten times a second -------------------------------------------------------

    def on_loop(self, sinceLast, elapsedTime, counter, refCon):
        try:
            self.tick()
        except Exception:
            self._fail("its sampling loop")
            try:
                self._show(False)
            except Exception:
                pass
            return 0
        return SAMPLE_PERIOD_S

    def tick(self):
        st = self.settings
        # Enabled is the plugin's whole effect, the HUD included (docs/pilot-guide.md).
        wanted = st.enabled and st.hud_enabled and self.eligible and not self.failed
        if self._rebuild:
            self._rebuild = False
            self._drop_drawing()
        if wanted and self.window is None:
            self._load_drawing()
        self._show(wanted)
        if not wanted:
            return
        if xp.getDatai(self._replay):
            self.reset_instruments()
            return
        if xp.getDatai(self._paused):
            return
        t0 = time.perf_counter()
        self.sample()
        self.sample_us += 0.05 * ((time.perf_counter() - t0) * 1e6 - self.sample_us)

    def sample(self):
        getf = xp.getDataf
        units = self.units = UNITS.get(self.settings.hud_units, UNITS["metric"])
        t = getf(self._time)
        bank = getf(self._phi)
        psi = getf(self._psi)
        vario = self.vario
        msl_m = xp.getDatad(self._elevation)
        if not vario.update(t, msl_m, getf(self._tas),
                            getf(self._ias) * KT_TO_KMH, bank, getf(self._mass)):
            if not vario.valid:  # it started over (a jump the vario saw itself): so does the thermal
                self.thermal.reset()
            return
        self.aid.update(t, psi, bank, vario.netto_ms)
        thermal = self.thermal
        thermal.update(t, vario.energy_m, self.aid.turning)
        self._samples += 1
        if self._samples >= SOLVE_EVERY:
            self._samples = 0
            self.aid.solve()
        per_ms, tape = units.per_ms, units.tape
        te, netto, average = vario.te_ms * per_ms, vario.netto_ms * per_ms, vario.average_ms * per_ms
        self._te_y = tape_y(te, tape)
        self._netto_y = tape_y(netto, tape)
        self._average_y = tape_y(average, tape)
        self._arrow = None
        if self.aid.valid and self.aid.amp_ms >= AID_MIN_AMP_MS:
            self._arrow = aid_arrow(self.aid.core_az_deg, psi, self.aid.amp_ms)
        self._te_text = f"{te:+.1f}"
        self._netto_text = f"NET {netto:+.1f}" if vario.has_netto else "NET --"
        self._average_text = f"AVG {average:+.1f}"
        self._thermal_text = f"THM {thermal.average_ms * per_ms:+.1f}" if thermal.valid else "THM --"
        self._thermal_color = WHITE if thermal.active else GREY
        if self.top_msl_m is not None:
            top_m = self.top_msl_m - msl_m
        else:
            top_m = height_to_top(self.zi_m, getf(self._agl), sky_named(self.settings.sky).cloud_base_zzi)
        self._top_text = "TOP " + units.height_text(top_m)
        wind_x, wind_z = getf(self._wind_x), getf(self._wind_z)
        self._wind_arrow = wind_arrow(wind_x, wind_z, psi)
        if self._wind_arrow is None:
            self._wind_text = "WIND calm"
        else:
            self._wind_text = f"WIND {math.hypot(wind_x, wind_z) * KT_PER_MS:.0f} kt"

    # --- every frame ----------------------------------------------------------------

    def on_draw(self, windowID, refCon):
        if self.failed or self._rebuild:
            return
        t0 = time.perf_counter()
        try:
            left, _, _, bottom = xp.getWindowGeometry(windowID)
            self.drawer.draw(self, left, bottom)
        except Exception:
            if self.drawer is not None and self.drawer.panel:
                # Never destroy a window from its own draw callback: the next tick does it.
                self.prefer_panel = False
                self._rebuild = True
                self.log("HUD: Panel Graphics failed while drawing, back to OpenGL:\n"
                         + traceback.format_exc())
            else:
                self._fail("its draw callback")
            return
        self.draw_us += 0.02 * ((time.perf_counter() - t0) * 1e6 - self.draw_us)


def panel_graphics_available():
    """Panel Graphics needs both XPPython3 4.8.0 and X-Plane 12.4.4 (SDK 440).

    makeColor needs no draw phase, so it is a safe probe anywhere: on X-Plane before 12.4.4 it
    raises, and XPPython3 before 4.8.0 has none of it.
    """
    if not hasattr(xp, "WindowContentTypePanelGraphics") or not hasattr(xp, "makeColor"):
        return False
    try:
        xp.makeColor(1.0, 1.0, 1.0, 1.0)
    except Exception:
        return False
    return True


def clockwise(points):
    """The polygon wound clockwise, y up: X-Plane 12.4's Panel Graphics fills only those."""
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        area += x0 * y1 - x1 * y0
    return points if area <= 0.0 else points[::-1]


def tick_marks(units):
    """The tape's marks and its spine, as pairs of points in the panel's own coordinates."""
    points = []
    for v in range(-units.tape, units.tape + 1):
        y = tape_y(v, units.tape)
        points += [(TAPE_X, y), (TAPE_X + (22 if v == 0 else 14 if v % units.major == 0 else 8), y)]
    return points + [(TAPE_X, TAPE_BOTTOM), (TAPE_X, TAPE_TOP)]


def dial_points():
    """The centring aid's circle, 40 points."""
    return [(AID_X + AID_RADIUS * math.sin(2.0 * math.pi * i / 40),
             AID_Y + AID_RADIUS * math.cos(2.0 * math.pi * i / 40)) for i in range(40)]


def mark_triangles(hud):
    """The moving triangles, each (colour, three points), in the panel's own coordinates."""
    y = hud._te_y
    marks = [(AMBER, [(TAPE_X + 24, y), (TAPE_X + 46, y + 8), (TAPE_X + 46, y - 8)])]
    y = hud._netto_y
    marks.append((GREEN, [(TAPE_X + 2, y), (TAPE_X + 14, y + 5), (TAPE_X + 14, y - 5)]))
    y = hud._average_y
    marks.append((WHITE, [(TAPE_X + 46, y), (TAPE_X + 54, y + 4), (TAPE_X + 54, y - 4)]))
    if hud._arrow is not None:
        dx, dy = hud._arrow
        marks.append((CYAN, [(AID_X + dx, AID_Y + dy), (AID_X - dy * 0.25, AID_Y + dx * 0.25),
                             (AID_X + dy * 0.25, AID_Y - dx * 0.25)]))
    if hud._wind_arrow is not None:
        dx, dy = hud._wind_arrow
        marks.append((WHITE, [(WIND_X + dx, WIND_Y + dy),
                              (WIND_X + 0.3 * dx - 0.4 * dy, WIND_Y + 0.3 * dy + 0.4 * dx),
                              (WIND_X + 0.3 * dx + 0.4 * dy, WIND_Y + 0.3 * dy - 0.4 * dx)]))
    return marks


def wind_shaft(hud):
    """The wind arrow's shaft, two points, or None when calm."""
    if hud._wind_arrow is None:
        return None
    dx, dy = hud._wind_arrow
    return [(WIND_X - dx, WIND_Y - dy), (WIND_X + 0.3 * dx, WIND_Y + 0.3 * dy)]


def text_lines(hud):
    """The small lines of text, top down, each LINE_PX under the last: (colour, text)."""
    return ((GREEN, hud._netto_text), (WHITE, hud._average_text),
            (hud._thermal_color, hud._thermal_text), (WHITE, hud._top_text),
            (WHITE, hud._wind_text))  # the wind just above its arrow


class PanelDrawer:
    """X-Plane 12.4.4's Panel Graphics: the static part recorded once and replayed, the rest each frame.

    Measured on 2026-11-17 against the OpenGL way below, for a scene like this one: 26-33 us a
    draw against 433, as sharp. All text goes through Panel Graphics fonts, since XPLMDrawString
    does not draw in a Panel Graphics window.
    """

    panel = True
    name = "Panel Graphics"

    def __init__(self):
        system = xp.getSystemPath()
        self.big = xp.createFont(xp.CharSetASCII)
        xp.fontAddFace(self.big, system + FONT_BIG)
        self.small = xp.createFont(xp.CharSetASCII)
        xp.fontAddFace(self.small, system + FONT_SMALL)
        self.colors = {c: xp.makeColor(*c, 1.0) for c in (WHITE, AMBER, GREEN, CYAN, GREY)}
        self.scrim = xp.makeColor(*SCRIM)
        self.tick = xp.makeColor(1.0, 1.0, 1.0, 0.9)
        self.dial = xp.makeColor(1.0, 1.0, 1.0, 0.6)
        self.static = None  # the retained drawing, made in the first draw for these units
        self.static_units = None

    def release(self):
        # A retained drawing goes before the fonts it may hold.
        if self.static is not None:
            xp.destroyRetainedDrawing(self.static)
            self.static = None
        for font in (self.big, self.small):
            xp.destroyFont(font)

    def draw_static(self, units):
        xp.polygon(self.scrim, clockwise([(0, 0), (WIDTH, 0), (WIDTH, HEIGHT), (0, HEIGHT)]))
        xp.lines(self.tick, tick_marks(units))
        xp.lineLoop(self.dial, dial_points())
        xp.lines(self.dial, [(AID_X, AID_Y + AID_RADIUS), (AID_X, AID_Y + AID_RADIUS + 6)])  # the nose, up

    def draw(self, hud, left, bottom):
        if self.static is not None and self.static_units is not hud.units:
            xp.destroyRetainedDrawing(self.static)  # the units changed: a new tape
            self.static = None
        if self.static is None:
            # Recorded inside a draw phase, where Panel Graphics has its context.
            self.static_units = hud.units
            xp.beginRetainedDrawing()
            try:
                self.draw_static(hud.units)
            finally:
                self.static = xp.endRetainedDrawing()
        colors = self.colors
        xp.transformPush()
        try:
            xp.transformTranslate(left, bottom)
            xp.drawRetained(self.static)
            shaft = wind_shaft(hud)
            if shaft is not None:
                xp.lines(colors[WHITE], shaft)
            for color, points in mark_triangles(hud):
                xp.polygon(colors[color], clockwise(points))
            xp.fontDrawString(self.big, colors[AMBER], BIG_PX, TEXT_X, TE_Y, hud._te_text, xp.JustLeft)
            y = TEXT_Y
            for color, text in text_lines(hud):
                xp.fontDrawString(self.small, colors[color], SMALL_PX, TEXT_X, y, text, xp.JustLeft)
                y -= LINE_PX
        finally:
            xp.transformPop()


class GLDrawer:
    """OpenGL in a window: for X-Plane before 12.4.4 or XPPython3 before 4.8.0, or when Panel
    Graphics fails. The static part is a GL display list, the big number TrueType through xpgl,
    the small text X-Plane's own font."""

    panel = False
    name = "OpenGL"

    def __init__(self):
        # Only in the simulator: tests have no OpenGL, and fonts need X-Plane.
        from OpenGL import GL
        from XPPython3 import xpgl

        self.GL, self.xpgl = GL, xpgl
        self.font_big = xpgl.loadFont(FONT_BIG, int(BIG_PX))
        self.static_list = None
        self.static_units = None  # the units the static list was drawn for

    def release(self):
        if self.static_list is not None:
            self.GL.glDeleteLists(self.static_list, 1)
            self.static_list = None

    def draw(self, hud, left, bottom):
        GL = self.GL
        xp.setGraphicsState(alphaBlending=1)
        # X-Plane leaves its own state here: additive blending, and faces culled so that this
        # module's counterclockwise polygons would not draw at all.
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDisable(GL.GL_CULL_FACE)
        if self.static_list is not None and self.static_units is not hud.units:
            GL.glDeleteLists(self.static_list, 1)  # the units changed: a new tape
            self.static_list = None
        if self.static_list is None:
            self.static_units = hud.units
            self.static_list = GL.glGenLists(1)
            GL.glNewList(self.static_list, GL.GL_COMPILE)
            self.draw_static(hud.units)
            GL.glEndList()
        GL.glPushMatrix()
        GL.glTranslatef(left, bottom, 0.0)
        GL.glCallList(self.static_list)
        self.draw_marks(hud)
        GL.glPopMatrix()
        x = left + TEXT_X
        self.xpgl.drawText(self.font_big, x, bottom + TE_Y, hud._te_text, "L", AMBER)
        y = bottom + TEXT_Y
        for color, text in text_lines(hud):
            xp.drawString(color, x, y, text, None, xp.Font_Proportional)
            y -= LINE_PX

    def draw_static(self, units):
        GL = self.GL
        GL.glColor4f(*SCRIM)
        GL.glBegin(GL.GL_QUADS)
        for x, y in ((0, 0), (WIDTH, 0), (WIDTH, HEIGHT), (0, HEIGHT)):
            GL.glVertex2f(x, y)
        GL.glEnd()
        GL.glColor4f(1.0, 1.0, 1.0, 0.9)
        GL.glBegin(GL.GL_LINES)
        for x, y in tick_marks(units):
            GL.glVertex2f(x, y)
        GL.glEnd()
        GL.glColor4f(1.0, 1.0, 1.0, 0.6)
        GL.glBegin(GL.GL_LINE_LOOP)
        for x, y in dial_points():
            GL.glVertex2f(x, y)
        GL.glEnd()
        GL.glBegin(GL.GL_LINES)  # the nose, up
        GL.glVertex2f(AID_X, AID_Y + AID_RADIUS)
        GL.glVertex2f(AID_X, AID_Y + AID_RADIUS + 6)
        GL.glEnd()

    def draw_marks(self, hud):
        GL = self.GL
        shaft = wind_shaft(hud)
        if shaft is not None:
            GL.glColor3f(*WHITE)
            GL.glBegin(GL.GL_LINES)
            for x, y in shaft:
                GL.glVertex2f(x, y)
            GL.glEnd()
        GL.glBegin(GL.GL_TRIANGLES)
        for color, points in mark_triangles(hud):
            GL.glColor3f(*color)
            for x, y in points:
                GL.glVertex2f(x, y)
        GL.glEnd()
