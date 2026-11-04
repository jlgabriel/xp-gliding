"""The soaring HUD: a small panel on screen with the instruments of `vario`.

A flight loop of its own samples the aircraft ten times a second, updates the
instruments and formats the text, so nothing of this runs in the frames between.
A window in the flight overlay layer draws the result every frame: the static
part from a GL display list, the rest as a few GL primitives and strings already
made. Under Vulkan X-Plane gives plugins an OpenGL context of their own, and
drawing in a window is the supported way to use it (docs/hud.md has the
measurements behind this choice, and what to move to on X-Plane 12.4.4). Small
text uses X-Plane's own font, because TrueType through xpgl costs ~18 us per
glyph from Python; only the big TE reading pays for it.

It never touches the forces, and a failure here only hides the panel: an
exception must not leave a draw callback, because XPPython3 stops calling it.

Metric units for now: m/s and m. Plugins > xp-gliding > Soaring HUD toggles it,
as does the command `xp_gliding/hud/toggle`.
"""

import math
import time
import traceback

import xp

from .vario import SAMPLE_PERIOD_S, CentringAid, Vario, height_to_top, polar_for

WIDTH, HEIGHT = 170, 300
MARGIN_LEFT, MARGIN_BOTTOM = 20, 300  # clear of the ASK 21's panel in the default view
TAPE_MS = 5.0
TAPE_BOTTOM, TAPE_TOP = 12, HEIGHT - 12
TAPE_X = 8
AID_X, AID_Y, AID_RADIUS = 118, 52, 34
# Half-swing of the lift around a circle. On logged orbits of the test pilot it is 0.8-0.9 m/s
# even within 30 m of the core, where the direction means nothing, and 1.8 m/s or more once
# 30 m or more off centre (docs/hud.md). Below this the arrow stays hidden.
AID_MIN_AMP_MS = 1.2
AID_FULL_AMP_MS = 3.0
SOLVE_EVERY = 5  # samples between CentringAid solutions
FONT_BIG = "Resources/fonts/Roboto-Bold.ttf"
KT_TO_KMH = 1.852

SCRIM = (0.0, 0.0, 0.0, 0.45)
WHITE = (1.0, 1.0, 1.0)
AMBER = (1.0, 0.75, 0.1)
GREEN = (0.3, 1.0, 0.45)
CYAN = (0.3, 0.85, 1.0)


def tape_y(value_ms):
    """Height of a value on the tape, clamped to its ends."""
    v = max(-TAPE_MS, min(TAPE_MS, value_ms))
    return TAPE_BOTTOM + (v + TAPE_MS) / (2.0 * TAPE_MS) * (TAPE_TOP - TAPE_BOTTOM)


def aid_arrow(core_az_deg, psi_deg, amp_ms):
    """The arrow's tip relative to the dial's centre: up is the nose, longer is more off centre."""
    angle = math.radians(core_az_deg - psi_deg)
    length = AID_RADIUS * (0.4 + 0.6 * min(amp_ms / AID_FULL_AMP_MS, 1.0))
    return length * math.sin(angle), length * math.cos(angle)


class Hud:
    def __init__(self, settings, log):
        self.settings = settings
        self.log = log
        self.vario = Vario()
        self.aid = CentringAid(lag_s=self.vario.tau_s)
        self.eligible = False
        self.sample_us = 0.0
        self.draw_us = 0.0
        self.failed = False
        self.window = None
        self.static_list = None
        self.GL = self.xpgl = None
        self.font_big = None
        self._samples = 0
        self._te_y = self._netto_y = self._average_y = tape_y(0.0)
        self._arrow = None
        self._te_text = self._netto_text = self._average_text = self._top_text = ""
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
        self.loop = xp.createFlightLoop(self.on_loop, xp.FlightLoop_Phase_AfterFlightModel, None)

    # --- life cycle ------------------------------------------------------------

    def enable(self):
        xp.scheduleFlightLoop(self.loop, SAMPLE_PERIOD_S, 1)

    def disable(self):
        xp.scheduleFlightLoop(self.loop, 0, 1)
        self._show(False)

    def stop(self):
        xp.destroyFlightLoop(self.loop)
        if self.window is not None:
            xp.destroyWindow(self.window)
            self.window = None

    def set_aircraft(self, path, eligible):
        self.eligible = eligible
        self.vario.polar = polar_for(path)
        self.vario.has_netto = self.vario.polar is not None
        self.vario.reset()
        self.aid.reset()

    def _load_drawing(self):
        # Only in the simulator: tests have no OpenGL, and fonts need X-Plane.
        from OpenGL import GL
        from XPPython3 import xpgl

        self.GL, self.xpgl = GL, xpgl
        self.font_big = xpgl.loadFont(FONT_BIG, 34)
        left, _, _, bottom = xp.getScreenBoundsGlobal()
        x, y = left + MARGIN_LEFT, bottom + MARGIN_BOTTOM
        self.window = xp.createWindowEx(x, y + HEIGHT, x + WIDTH, y, 1, self.on_draw,
                                        decoration=xp.WindowDecorationNone,
                                        layer=xp.WindowLayerFlightOverlay)

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
        wanted = self.settings.hud_enabled and self.eligible and not self.failed
        if wanted and self.window is None:
            self._load_drawing()
        self._show(wanted)
        if not wanted:
            return
        if xp.getDatai(self._replay):
            self.vario.reset()
            self.aid.reset()
            return
        if xp.getDatai(self._paused):
            return
        t0 = time.perf_counter()
        self.sample()
        self.sample_us += 0.05 * ((time.perf_counter() - t0) * 1e6 - self.sample_us)

    def sample(self):
        getf = xp.getDataf
        t = getf(self._time)
        bank = getf(self._phi)
        psi = getf(self._psi)
        vario = self.vario
        if not vario.update(t, xp.getDatad(self._elevation), getf(self._tas),
                            getf(self._ias) * KT_TO_KMH, bank, getf(self._mass)):
            return
        self.aid.update(t, psi, bank, vario.netto_ms)
        self._samples += 1
        if self._samples >= SOLVE_EVERY:
            self._samples = 0
            self.aid.solve()
        self._te_y = tape_y(vario.te_ms)
        self._netto_y = tape_y(vario.netto_ms)
        self._average_y = tape_y(vario.average_ms)
        self._arrow = None
        if self.aid.valid and self.aid.amp_ms >= AID_MIN_AMP_MS:
            self._arrow = aid_arrow(self.aid.core_az_deg, psi, self.aid.amp_ms)
        self._te_text = f"{vario.te_ms:+.1f}"
        self._netto_text = f"NET {vario.netto_ms:+.1f}" if vario.has_netto else "NET --"
        self._average_text = f"AVG {vario.average_ms:+.1f}"
        self._top_text = f"TOP {height_to_top(self.settings.zi_m, getf(self._agl)):+.0f} m"

    # --- every frame ----------------------------------------------------------------

    def on_draw(self, windowID, refCon):
        if self.failed:
            return
        t0 = time.perf_counter()
        try:
            left, _, _, bottom = xp.getWindowGeometry(windowID)
            self.draw(left, bottom)
        except Exception:
            self._fail("its draw callback")
            return
        self.draw_us += 0.02 * ((time.perf_counter() - t0) * 1e6 - self.draw_us)

    def draw(self, left, bottom):
        GL = self.GL
        xp.setGraphicsState(alphaBlending=1)
        # X-Plane leaves its own state here: additive blending, and faces culled so that this
        # module's counterclockwise polygons would not draw at all.
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glDisable(GL.GL_CULL_FACE)
        if self.static_list is None:
            self.static_list = GL.glGenLists(1)
            GL.glNewList(self.static_list, GL.GL_COMPILE)
            self.draw_static()
            GL.glEndList()
        GL.glPushMatrix()
        GL.glTranslatef(left, bottom, 0.0)
        GL.glCallList(self.static_list)
        self.draw_marks()
        GL.glPopMatrix()
        x = left + 66
        self.xpgl.drawText(self.font_big, x, bottom + HEIGHT - 44, self._te_text, "L", AMBER)
        y = bottom + HEIGHT
        xp.drawString(GREEN, x, y - 70, self._netto_text, None, xp.Font_Proportional)
        xp.drawString(WHITE, x, y - 90, self._average_text, None, xp.Font_Proportional)
        xp.drawString(WHITE, x, y - 110, self._top_text, None, xp.Font_Proportional)

    def draw_static(self):
        GL = self.GL
        GL.glColor4f(*SCRIM)
        GL.glBegin(GL.GL_QUADS)
        GL.glVertex2f(0, 0)
        GL.glVertex2f(WIDTH, 0)
        GL.glVertex2f(WIDTH, HEIGHT)
        GL.glVertex2f(0, HEIGHT)
        GL.glEnd()
        GL.glColor4f(1.0, 1.0, 1.0, 0.9)
        GL.glBegin(GL.GL_LINES)
        for v in range(-int(TAPE_MS), int(TAPE_MS) + 1):
            y = tape_y(v)
            GL.glVertex2f(TAPE_X, y)
            GL.glVertex2f(TAPE_X + (22 if v == 0 else 14 if v % 5 == 0 else 8), y)
        GL.glVertex2f(TAPE_X, TAPE_BOTTOM)
        GL.glVertex2f(TAPE_X, TAPE_TOP)
        GL.glEnd()
        GL.glColor4f(1.0, 1.0, 1.0, 0.6)
        GL.glBegin(GL.GL_LINE_LOOP)
        for i in range(40):
            angle = 2.0 * math.pi * i / 40
            GL.glVertex2f(AID_X + AID_RADIUS * math.sin(angle), AID_Y + AID_RADIUS * math.cos(angle))
        GL.glEnd()
        GL.glBegin(GL.GL_LINES)  # the nose, up
        GL.glVertex2f(AID_X, AID_Y + AID_RADIUS)
        GL.glVertex2f(AID_X, AID_Y + AID_RADIUS + 6)
        GL.glEnd()

    def draw_marks(self):
        GL = self.GL
        GL.glBegin(GL.GL_TRIANGLES)
        y = self._te_y
        GL.glColor3f(*AMBER)
        GL.glVertex2f(TAPE_X + 24, y)
        GL.glVertex2f(TAPE_X + 46, y + 8)
        GL.glVertex2f(TAPE_X + 46, y - 8)
        y = self._netto_y
        GL.glColor3f(*GREEN)
        GL.glVertex2f(TAPE_X + 2, y)
        GL.glVertex2f(TAPE_X + 14, y + 5)
        GL.glVertex2f(TAPE_X + 14, y - 5)
        y = self._average_y
        GL.glColor3f(*WHITE)
        GL.glVertex2f(TAPE_X + 46, y)
        GL.glVertex2f(TAPE_X + 54, y + 4)
        GL.glVertex2f(TAPE_X + 54, y - 4)
        GL.glEnd()
        arrow = self._arrow
        if arrow is not None:
            dx, dy = arrow
            GL.glColor3f(*CYAN)
            GL.glBegin(GL.GL_TRIANGLES)
            GL.glVertex2f(AID_X + dx, AID_Y + dy)
            GL.glVertex2f(AID_X - dy * 0.25, AID_Y + dx * 0.25)
            GL.glVertex2f(AID_X + dy * 0.25, AID_Y - dx * 0.25)
            GL.glEnd()
