"""CPU time of X-Plane's threads and a capture of its window, from outside (Windows only).

The frame rate cap hides a small drawing cost in the frame time, so the cost of a method
whose code we cannot time from Python is read as CPU time of the thread that draws.
X-Plane's own screenshot command leaves plugins' 2D windows out, hence the capture.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import ctypes
import subprocess
from ctypes import wintypes

TH32CS_SNAPTHREAD = 0x00000004
THREAD_QUERY_LIMITED_INFORMATION = 0x0800
kernel32 = ctypes.windll.kernel32


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD), ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG), ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD)]


def xplane_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq X-Plane.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return int(out.splitlines()[0].split(",")[1].strip('"'))


def thread_ids(pid):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(THREADENTRY32)
    ids = []
    more = kernel32.Thread32First(snap, ctypes.byref(entry))
    while more:
        if entry.th32OwnerProcessID == pid:
            ids.append(entry.th32ThreadID)
        more = kernel32.Thread32Next(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return ids


def thread_times(tid):
    """(creation, cpu seconds), or None if the thread is gone."""
    handle = kernel32.OpenThread(THREAD_QUERY_LIMITED_INFORMATION, False, tid)
    if not handle:
        return None
    times = [wintypes.FILETIME() for _ in range(4)]
    ok = kernel32.GetThreadTimes(handle, *[ctypes.byref(t) for t in times])
    kernel32.CloseHandle(handle)
    if not ok:
        return None
    value = [(t.dwHighDateTime << 32 | t.dwLowDateTime) for t in times]
    return value[0], (value[2] + value[3]) * 1e-7


def main_thread(pid):
    """The process's oldest thread, the one the SDK and plugins' draw callbacks run on."""
    best = None
    for tid in thread_ids(pid):
        t = thread_times(tid)
        if t is not None and (best is None or t[0] < best[1]):
            best = (tid, t[0])
    return best[0]


def main_window_rect(pid):
    """(left, top, right, bottom) on screen of the largest visible window of the process."""
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append((rect.left, rect.top, rect.right, rect.bottom))
        return True

    ctypes.windll.user32.EnumWindows(proc(visit), 0)
    return max(found, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))


def capture_window(pid, path):
    """Save what is on screen where X-Plane's window is. Needs Pillow, and an unlocked screen."""
    from PIL import ImageGrab

    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # or the rectangle is scaled, the grab not
    ImageGrab.grab(bbox=main_window_rect(pid), all_screens=True).save(path)
