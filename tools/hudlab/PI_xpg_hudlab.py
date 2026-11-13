"""Drawing lab: the same vario strip drawn each way XPPython3 can, with its cost measured.

Measurement tool, not part of the plugin. Install by copying this single file into
`Resources/plugins/PythonPlugins/`, restart X-Plane, and drive it with `measure_hud.py`.

Writing `xp_gliding/hudlab/mode` picks the method (see MODES). Each one draws the same
scene from synthetic values: a scrim, a tape of 11 ticks, a needle, a marker and three
text lines. Published, over the samples since `xp_gliding/hudlab/reset` was last written:

  draw_us_p50/p99     CPU time in our own draw callback, per draw (with imgui, the whole
                      window callback, its renderer included)
  draws_per_s         how often the scene is really drawn (on-demand drawing is less)
  errors              exceptions caught in a draw

Exceptions must not leave a draw callback: XPPython3 logged the first one and the callback
never drew again (seen 2026-11-03), so a bug in one mode silently ends the others sharing
its window. GPU cost and main-thread CPU are read from outside by the driver.
imgui is imported only when its mode is first used: XPPython3's docs warn that reloading scripts
after using it crashes the simulator, so never reload with this plugin once that mode ran.

License: GPL-3.0-or-later.
"""

import math
import time
import traceback

import xp
from OpenGL import GL
from XPPython3 import xpgl

W, H = 150, 240
LEFT, TOP = 40, 560
ON_DEMAND_PERIOD_S = 0.1
RING = 4096
FONT = "Resources/fonts/Roboto-Regular.ttf"

MODES = {
    0: "off",
    1: "window: XPLM dark box and strings only (no tape)",
    2: "window: xpgl shapes and text",
    3: "window: raw GL immediate mode, XPLM strings",
    4: "window: GL display list for the static part, XPLM strings",
    5: "avionics popup: xpgl, every frame",
    6: "avionics popup: xpgl, on demand at 10 Hz",
    7: "window: imgui",
    8: "window: GL display list for the static part, xpgl TrueType text",
}


class Stats:
    def __init__(self):
        self.values = [0.0] * RING
        self.reset()

    def reset(self):
        self.n = 0

    def add(self, value):
        self.values[self.n % RING] = value
        self.n += 1

    def percentile(self, p):
        count = min(self.n, RING)
        if not count:
            return 0.0
        return sorted(self.values[:count])[min(int(p * count), count - 1)]


def value_now():
    return 3.0 * math.sin(time.monotonic() / 3.0)


class PythonInterface:
    def XPluginStart(self):
        self.mode = 0
        self.draw_stats = Stats()
        self.errors = 0
        self.reset_at = time.monotonic()
        self.draws = 0
        self.list_id = None
        self.window = None
        self.imgui_window = None
        self.imgui = None
        self.device = None
        self.device_demand = None
        self.big = self.small = None
        self.published = {"draw_us_p50": 0.0, "draw_us_p99": 0.0, "draws_per_s": 0.0,
                          "errors": 0.0}
        self.refs = [
            xp.registerDataAccessor("xp_gliding/hudlab/mode", xp.Type_Int, 1,
                                    readInt=lambda _: self.mode,
                                    writeInt=lambda _, v: self.set_mode(int(v))),
            xp.registerDataAccessor("xp_gliding/hudlab/reset", xp.Type_Int, 1,
                                    readInt=lambda _: 0, writeInt=lambda _, v: self.reset_stats()),
        ]
        for name in self.published:
            self.refs.append(xp.registerDataAccessor(
                "xp_gliding/hudlab/" + name, xp.Type_Float, 0,
                readFloat=self.read_published, readRefCon=name))
        self.loop = xp.createFlightLoop(self.slow_loop, xp.FlightLoop_Phase_AfterFlightModel, None)
        return "xp-gliding HUD lab", "jlgabriel.xp_gliding.hudlab", "Drawing cost measurements."

    def XPluginEnable(self):
        self.big = xpgl.loadFont(FONT, 34)
        self.small = xpgl.loadFont(FONT, 14)
        xp.scheduleFlightLoop(self.loop, ON_DEMAND_PERIOD_S, 1)
        return 1

    def XPluginDisable(self):
        self.set_mode(0)
        xp.scheduleFlightLoop(self.loop, 0, 1)

    def XPluginStop(self):
        xp.destroyFlightLoop(self.loop)
        for ref in self.refs:
            xp.unregisterDataAccessor(ref)

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        pass

    # --- measurements -------------------------------------------------------

    def read_published(self, name):
        return self.published[name]

    def reset_stats(self):
        self.draw_stats.reset()
        self.draws = 0
        self.reset_at = time.monotonic()

    def slow_loop(self, sinceLast, elapsedTime, counter, refCon):
        if self.mode == 6 and self.device_demand is not None:
            xp.avionicsNeedsDrawing(self.device_demand)
        now = time.monotonic()
        if now - self.reset_at > 1.0:
            p = self.published
            p["draw_us_p50"] = self.draw_stats.percentile(0.50)
            p["draw_us_p99"] = self.draw_stats.percentile(0.99)
            p["draws_per_s"] = self.draws / (now - self.reset_at)
            p["errors"] = float(self.errors)
        return ON_DEMAND_PERIOD_S

    def timed(self, scene, *args):
        t0 = time.perf_counter()
        try:
            scene(*args)
        except Exception:
            self.errors += 1
            if self.errors == 1:
                xp.log("[hudlab] draw failed:\n" + traceback.format_exc())
            return
        self.draw_stats.add((time.perf_counter() - t0) * 1e6)
        self.draws += 1

    # --- switching ------------------------------------------------------------

    def set_mode(self, mode):
        if mode not in MODES or mode == self.mode:
            return
        self.hide_all()
        self.mode = mode
        if mode in (1, 2, 3, 4, 8):
            self.show_window()
        elif mode == 5:
            self.show_device(False)
        elif mode == 6:
            self.show_device(True)
        elif mode == 7:
            self.show_imgui()
        self.reset_stats()
        xp.log(f"[hudlab] mode {mode}: {MODES[mode]}")

    def hide_all(self):
        if self.window is not None:
            xp.setWindowIsVisible(self.window, 0)
        if self.imgui_window is not None:
            xp.setWindowIsVisible(self.imgui_window.windowID, 0)
        for device in (self.device, self.device_demand):
            if device is not None:
                xp.setAvionicsPopupVisible(device, 0)

    def show_window(self):
        if self.window is None:
            self.window = xp.createWindowEx(
                LEFT, TOP, LEFT + W, TOP - H, 1, self.draw_window,
                decoration=xp.WindowDecorationNone, layer=xp.WindowLayerFlightOverlay)
        xp.setWindowIsVisible(self.window, 1)

    def show_device(self, on_demand):
        device = self.device_demand if on_demand else self.device
        if device is None:
            device = xp.createAvionicsEx(
                screenWidth=W, screenHeight=H, bezelWidth=W, bezelHeight=H,
                screenOffsetX=0, screenOffsetY=0, drawOnDemand=1 if on_demand else 0,
                screenDraw=self.draw_device, brightness=lambda rheo, ambient, bus, refCon: 1.0,
                deviceID="xpg.hudlab.demand" if on_demand else "xpg.hudlab.frame",
                deviceName="xp-gliding HUD lab")
            if on_demand:
                self.device_demand = device
            else:
                self.device = device
        xp.setAvionicsPopupVisible(device, 1)

    def show_imgui(self):
        if self.imgui_window is None:
            import imgui
            from XPPython3 import xp_imgui
            lab = self

            class TimedWindow(xp_imgui.Window):
                def imguiDrawWindow(self, windowID, refCon):
                    lab.timed(super().imguiDrawWindow, windowID, refCon)

            self.imgui = imgui
            self.imgui_window = TimedWindow(
                left=LEFT, top=TOP, right=LEFT + W, bottom=TOP - H, visible=1,
                draw=self.draw_imgui, refCon=None)
        xp.setWindowIsVisible(self.imgui_window.windowID, 1)

    # --- the callbacks ----------------------------------------------------------

    def draw_window(self, windowID, refCon):
        left, top, _, bottom = xp.getWindowGeometry(windowID)
        if self.mode == 1:
            self.timed(self.scene_xplm, left, top, bottom)
        elif self.mode == 2:
            self.timed(self.scene_xpgl, left, bottom)
        elif self.mode == 3:
            self.timed(self.scene_gl, left, bottom)
        elif self.mode == 4:
            self.timed(self.scene_gl_list, left, bottom)
        elif self.mode == 8:
            self.timed(self.scene_gl_ttf, left, bottom)

    def draw_device(self, refCon):
        def scene():
            xpgl.clear()
            self.scene_xpgl(0, 0)
        self.timed(scene)

    def draw_imgui(self, windowID, refCon):
        self.scene_imgui()

    # --- the scene, each way ---------------------------------------------------

    @staticmethod
    def needle_y(bottom):
        return bottom + H / 2 + value_now() / 5.0 * (H / 2 - 12)

    def texts(self):
        v = value_now()
        return f"{v:+.1f}", f"NETTO {v + 1.2:+.1f}", f"AVG {v / 2:+.1f}"

    def scene_xplm(self, left, top, bottom):
        a, b, c = self.texts()
        xp.drawTranslucentDarkBox(left, top, left + W, bottom)
        xp.drawString((1, 1, 1), left + 50, bottom + H // 2, a, None, xp.Font_Proportional)
        xp.drawString((1, 1, 1), left + 50, bottom + 30, b, None, xp.Font_Proportional)
        xp.drawString((1, 1, 1), left + 50, bottom + 12, c, None, xp.Font_Proportional)

    def scene_xpgl(self, left, bottom):
        a, b, c = self.texts()
        y = self.needle_y(bottom)
        xp.setGraphicsState(alphaBlending=1)
        # xpgl's polygons force alpha to 1 on XPPython3 4.7.1, so the scrim is plain GL.
        GL.glColor4f(0.0, 0.0, 0.0, 0.45)
        GL.glBegin(GL.GL_QUADS)
        GL.glVertex2f(left, bottom)
        GL.glVertex2f(left + W, bottom)
        GL.glVertex2f(left + W, bottom + H)
        GL.glVertex2f(left, bottom + H)
        GL.glEnd()
        for i in range(11):
            ty = bottom + 12 + i * (H - 24) / 10
            xpgl.drawLine(left + 6, ty, left + (26 if i % 5 == 0 else 18), ty, 1.0, (1, 1, 1, 0.9))
        xpgl.drawTriangle(left + 28, y, left + 48, y + 7, left + 48, y - 7, (1.0, 0.8, 0.1))
        xpgl.drawRectangle(left + 6, y + 10, 20, 4, (0.3, 1.0, 0.4))
        xpgl.drawText(self.big, left + 56, bottom + H // 2, a)
        xpgl.drawText(self.small, left + 56, bottom + 30, b)
        xpgl.drawText(self.small, left + 56, bottom + 12, c)

    def static_gl(self, left, bottom):
        GL.glColor4f(0.0, 0.0, 0.0, 0.45)
        GL.glBegin(GL.GL_QUADS)
        GL.glVertex2f(left, bottom)
        GL.glVertex2f(left + W, bottom)
        GL.glVertex2f(left + W, bottom + H)
        GL.glVertex2f(left, bottom + H)
        GL.glEnd()
        GL.glColor4f(1.0, 1.0, 1.0, 0.9)
        GL.glBegin(GL.GL_LINES)
        for i in range(11):
            ty = bottom + 12 + i * (H - 24) / 10
            GL.glVertex2f(left + 6, ty)
            GL.glVertex2f(left + (26 if i % 5 == 0 else 18), ty)
        GL.glEnd()

    def needle_gl(self, left, bottom):
        y = self.needle_y(bottom)
        GL.glColor4f(1.0, 0.8, 0.1, 1.0)
        GL.glBegin(GL.GL_TRIANGLES)
        GL.glVertex2f(left + 28, y)
        GL.glVertex2f(left + 48, y + 7)
        GL.glVertex2f(left + 48, y - 7)
        GL.glEnd()

    def moving_gl(self, left, bottom):
        a, b, c = self.texts()
        self.needle_gl(left, bottom)
        xp.drawString((1, 1, 1), left + 56, bottom + H // 2, a, None, xp.Font_Proportional)
        xp.drawString((1, 1, 1), left + 56, bottom + 30, b, None, xp.Font_Proportional)
        xp.drawString((1, 1, 1), left + 56, bottom + 12, c, None, xp.Font_Proportional)

    def scene_gl(self, left, bottom):
        xp.setGraphicsState(alphaBlending=1)
        self.static_gl(left, bottom)
        self.moving_gl(left, bottom)

    def static_list(self, left, bottom):
        xp.setGraphicsState(alphaBlending=1)
        if self.list_id is None:
            self.list_id = GL.glGenLists(1)
            GL.glNewList(self.list_id, GL.GL_COMPILE)
            self.static_gl(0, 0)
            GL.glEndList()
        GL.glPushMatrix()
        GL.glTranslatef(left, bottom, 0.0)
        GL.glCallList(self.list_id)
        GL.glPopMatrix()

    def scene_gl_list(self, left, bottom):
        self.static_list(left, bottom)
        self.moving_gl(left, bottom)

    def scene_gl_ttf(self, left, bottom):
        a, b, c = self.texts()
        self.static_list(left, bottom)
        self.needle_gl(left, bottom)
        xpgl.drawText(self.big, left + 56, bottom + H // 2, a)
        xpgl.drawText(self.small, left + 56, bottom + 30, b)
        xpgl.drawText(self.small, left + 56, bottom + 12, c)

    def scene_imgui(self):
        imgui = self.imgui
        a, b, c = self.texts()
        pos = imgui.get_window_position()
        lst = imgui.get_window_draw_list()
        y = pos.y + H / 2 - value_now() / 5.0 * (H / 2 - 12)
        for i in range(11):
            ty = pos.y + 12 + i * (H - 24) / 10
            lst.add_line(pos.x + 6, ty, pos.x + (26 if i % 5 == 0 else 18), ty, 0xE6FFFFFF)
        lst.add_triangle_filled(pos.x + 28, y, pos.x + 48, y + 7, pos.x + 48, y - 7, 0xFF1ACCFF)
        imgui.set_cursor_pos((56, H // 2))
        imgui.text(a)
        imgui.set_cursor_pos((56, H - 50))
        imgui.text(b)
        imgui.set_cursor_pos((56, H - 30))
        imgui.text(c)
