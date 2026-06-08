"""
Claude Usage Bar — frosted pill HUD for Windows

A ~34px translucent pill pinned above the Windows clock showing Claude Code
session (5h) and weekly (7d) usage percentages with a breathing live dot.

Rendered with PIL into a per-pixel-alpha layered window (UpdateLayeredWindow),
so the frosted pill reads on any background — white, black, or a photo.

Requirements: pip install pillow
Run with:     pythonw claude_usage_bar.pyw
Right-click the pill to refresh or quit.
"""

import ctypes
import json
import os
import ssl
import sys
import threading
import time
import urllib.request
from ctypes import POINTER, byref, c_int, c_void_p, sizeof, wintypes
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Palette ────────────────────────────────────────────────────────────
PILL_BG   = (16, 16, 20, 143)      # rgba(16,16,20,0.56)
PILL_EDGE = (255, 255, 255, 36)    # rgba(255,255,255,0.14)
TRACK     = (255, 255, 255, 51)    # rgba(255,255,255,0.20)
LBL       = (242, 239, 234, 214)
SHADOW    = (0, 0, 0, 150)
OK        = (244, 241, 236, 255)   # <75% cream
WARN      = (255, 176, 102, 255)   # 75-89% amber
CRIT      = (248, 113, 113, 255)   # >=90% red
OFF       = (207, 207, 214, 255)
LIVE      = (95, 211, 141, 255)
ERRDOT    = (248, 113, 113, 255)
RST       = (150, 150, 158, 235)

REFRESH = 120   # seconds between API polls
TICK    = 1     # seconds between reposition / topmost re-assert
ANIM_MS = 80    # ms between pulse frames (~12 fps)
PULSE_S = 1.8   # seconds per full live-dot pulse cycle
CRED    = Path.home() / ".claude" / ".credentials.json"
CACHE   = Path(os.environ.get("TEMP", "/tmp")) / "claude-usage-bar-cache.json"
FONT_B  = "C:/Windows/Fonts/consolab.ttf"

STATE = {"status": "starting", "s": 0, "w": 0, "s_iso": None, "w_iso": None}
_dirty = threading.Event()
_dirty.set()

# ── Win32 plumbing ─────────────────────────────────────────────────────
user32  = ctypes.windll.user32
gdi32   = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
LRESULT = ctypes.c_ssize_t

WS_POPUP        = 0x80000000
WS_EX_LAYERED   = 0x00080000
WS_EX_TOPMOST   = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SW_SHOWNA       = 8
HWND_TOPMOST    = -1
SWP_NOMOVE      = 0x0002
SWP_NOSIZE      = 0x0001
SWP_NOACTIVATE  = 0x0010
ULW_ALPHA       = 0x02
WM_RBUTTONUP    = 0x0205
WM_TIMER        = 0x0113
WM_DESTROY      = 0x0002
TPM_RETURNCMD   = 0x0100
TPM_RIGHTBUTTON = 0x0002
MF_SEPARATOR    = 0x0800


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", c_int), ("cbWndExtra", c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", wintypes.BYTE), ("BlendFlags", wintypes.BYTE),
                ("SourceConstantAlpha", wintypes.BYTE), ("AlphaFormat", wintypes.BYTE)]


WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

HWND, HDC, HANDLE = wintypes.HWND, wintypes.HDC, wintypes.HANDLE
DWORD, UINT, BOOL = wintypes.DWORD, wintypes.UINT, wintypes.BOOL
LPCWSTR = wintypes.LPCWSTR

# Every Win32 call returning/taking a HANDLE must have restype+argtypes set —
# 64-bit handles overflow ctypes' default c_int otherwise.
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [LPCWSTR]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [HWND, UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassW.restype = wintypes.ATOM
user32.RegisterClassW.argtypes = [POINTER(WNDCLASS)]
user32.CreateWindowExW.restype = HWND
user32.CreateWindowExW.argtypes = [DWORD, LPCWSTR, LPCWSTR, DWORD, c_int, c_int,
                                   c_int, c_int, HWND, HANDLE, HANDLE, c_void_p]
user32.LoadCursorW.restype = HANDLE
user32.LoadCursorW.argtypes = [HANDLE, c_void_p]
user32.ShowWindow.argtypes = [HWND, c_int]
user32.SetTimer.argtypes = [HWND, c_void_p, UINT, c_void_p]
user32.SetWindowPos.argtypes = [HWND, c_void_p, c_int, c_int, c_int, c_int, UINT]
user32.DestroyWindow.argtypes = [HWND]
user32.FindWindowW.restype = HWND
user32.FindWindowW.argtypes = [LPCWSTR, LPCWSTR]
user32.GetWindowRect.argtypes = [HWND, POINTER(wintypes.RECT)]
user32.GetDC.restype = HDC
user32.GetDC.argtypes = [HWND]
user32.ReleaseDC.argtypes = [HWND, HDC]
user32.UpdateLayeredWindow.restype = BOOL
user32.UpdateLayeredWindow.argtypes = [HWND, HDC, POINTER(wintypes.POINT),
                                       POINTER(wintypes.SIZE), HDC,
                                       POINTER(wintypes.POINT), wintypes.COLORREF,
                                       POINTER(BLENDFUNCTION), DWORD]
user32.CreatePopupMenu.restype = HANDLE
user32.AppendMenuW.argtypes = [HANDLE, UINT, ctypes.c_size_t, LPCWSTR]
user32.TrackPopupMenu.restype = c_int
user32.TrackPopupMenu.argtypes = [HANDLE, UINT, c_int, c_int, c_int, HWND, c_void_p]
user32.DestroyMenu.argtypes = [HANDLE]
user32.SetForegroundWindow.argtypes = [HWND]
gdi32.CreateCompatibleDC.restype = HDC
gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.SelectObject.restype = HANDLE
gdi32.SelectObject.argtypes = [HDC, HANDLE]
gdi32.DeleteObject.argtypes = [HANDLE]
gdi32.DeleteDC.argtypes = [HDC]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateDIBSection.argtypes = [HDC, POINTER(BITMAPINFO), UINT,
                                   POINTER(c_void_p), HANDLE, DWORD]


# ── Data ───────────────────────────────────────────────────────────────
def get_token():
    t = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if t:
        return t
    try:
        with open(CRED, "r", encoding="utf-8") as f:
            return json.load(f).get("claudeAiOauth", {}).get("accessToken")
    except Exception:
        return None


def api_fetch(token):
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={"Authorization": f"Bearer {token}",
                 "anthropic-beta": "oauth-2025-04-20",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(),
                                    timeout=15) as r:
            d = json.loads(r.read().decode())
            with open(CACHE, "w") as f:
                json.dump({"ts": time.time(), "d": d}, f)
            return d
    except Exception:
        try:
            with open(CACHE) as f:
                c = json.load(f)
            if time.time() - c["ts"] < 600:
                return c["d"]
        except Exception:
            pass
    return None


def countdown(iso):
    if not iso:
        return "--"
    try:
        s = int((datetime.fromisoformat(iso.replace("Z", "+00:00"))
                 - datetime.now(timezone.utc)).total_seconds())
        if s <= 0:
            return "now"
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        m = s // 60
        if d:
            return f"{d}d {h}h"
        if h:
            return f"{h}h {m}m"
        return f"{m}m"
    except Exception:
        return "--"


def _apply(d):
    fh = d.get("five_hour") or {}
    sd = d.get("seven_day") or {}
    STATE["s"] = round(fh.get("utilization", 0))
    STATE["w"] = round(sd.get("utilization", 0))
    STATE["s_iso"] = fh.get("resets_at")
    STATE["w_iso"] = sd.get("resets_at")
    STATE["status"] = "ok"


def poll_loop():
    while True:
        tok = get_token()
        d = api_fetch(tok) if tok else None
        if d:
            _apply(d)
        else:
            STATE["status"] = "offline"
        _dirty.set()
        time.sleep(REFRESH)


def level_color(p):
    if p >= 90:
        return CRIT
    if p >= 75:
        return WARN
    return OK


# ── Rendering (PIL → RGBA pill) ────────────────────────────────────────
SS = 3  # supersample for crisp small text
_f_lbl = ImageFont.truetype(FONT_B, 10 * SS)
_f_val = ImageFont.truetype(FONT_B, 13 * SS)
_f_rst = ImageFont.truetype(FONT_B, 10 * SS)
_scratch = ImageDraw.Draw(Image.new("RGBA", (4, 4)))


def _tw(t, f):
    return _scratch.textlength(t, font=f)


def render():
    ok = STATE["status"] == "ok"
    metrics = [("S", STATE["s"] if ok else None, countdown(STATE["s_iso"]) if ok else ""),
               ("W", STATE["w"] if ok else None, countdown(STATE["w_iso"]) if ok else "")]

    pad, gap, dot_d, ig, rg = (12 * SS, 9 * SS, round(8 * SS * 0.7), 6 * SS, 5 * SS)
    H = 34 * SS

    def vtext(m):
        return f"{m}%" if m is not None else "—"

    x = pad + dot_d + gap
    for i, (lab, m, rst) in enumerate(metrics):
        x += _tw(lab, _f_lbl) + ig + _tw(vtext(m), _f_val)
        if rst:
            x += rg + _tw(rst, _f_rst)
        if i < len(metrics) - 1:
            x += gap
    W = int(x + pad)

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2,
                        fill=PILL_BG, outline=PILL_EDGE, width=SS)

    cx = pad
    cy = H // 2

    dot = LIVE if ok else ERRDOT
    cxc = cx + dot_d / 2
    rb = dot_d / 2
    if ok:
        for k in range(2):
            p = ((time.time() / PULSE_S) + k * 0.5) % 1.0
            R = rb + p * (6 * SS)
            a = int(130 * (1 - p) ** 1.5)
            if a > 0:
                d.ellipse([cxc - R, cy - R, cxc + R, cy + R],
                          outline=dot[:3] + (a,), width=SS)
    else:
        d.ellipse([cx - SS, cy - dot_d // 2 - SS, cx + dot_d + SS, cy + dot_d // 2 + SS],
                  fill=dot[:3] + (70,))
    d.ellipse([cx, cy - dot_d // 2, cx + dot_d, cy + dot_d // 2], fill=dot)
    cx += dot_d + gap

    for i, (lab, m, rst) in enumerate(metrics):
        col = level_color(m) if m is not None else OFF
        d.text((cx, cy), lab, font=_f_lbl, fill=LBL, anchor="lm")
        cx += int(_tw(lab, _f_lbl)) + ig
        vt = vtext(m)
        d.text((cx + SS, cy + SS), vt, font=_f_val, fill=SHADOW, anchor="lm")
        d.text((cx, cy), vt, font=_f_val, fill=col, anchor="lm")
        cx += int(_tw(vt, _f_val))
        if rst:
            cx += rg
            d.text((cx, cy), rst, font=_f_rst, fill=RST, anchor="lm")
            cx += int(_tw(rst, _f_rst))
        if i < len(metrics) - 1:
            cx += gap

    return img.resize((W // SS, H // SS), Image.LANCZOS)


def _premultiplied_bgra(img):
    b = bytearray(img.tobytes("raw", "BGRA"))
    for i in range(0, len(b), 4):
        a = b[i + 3]
        if a != 255:
            b[i] = b[i] * a // 255
            b[i + 1] = b[i + 1] * a // 255
            b[i + 2] = b[i + 2] * a // 255
    return bytes(b)


def push(hwnd, img, x, y):
    w, h = img.size
    raw = _premultiplied_bgra(img)
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    ppv = c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_mem, byref(bmi), 0, byref(ppv), None, 0)
    ctypes.memmove(ppv, raw, len(raw))
    old = gdi32.SelectObject(hdc_mem, hbmp)
    size = wintypes.SIZE(w, h)
    psrc = wintypes.POINT(0, 0)
    pdst = wintypes.POINT(x, y)
    blend = BLENDFUNCTION(0, 0, 255, 1)
    user32.UpdateLayeredWindow(hwnd, hdc_screen, byref(pdst), byref(size),
                               hdc_mem, byref(psrc), 0, byref(blend), ULW_ALPHA)
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)


def clock_pos(w, h):
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    if tray:
        tr = wintypes.RECT()
        user32.GetWindowRect(tray, byref(tr))
        return tr.right - w - 2, tr.top - h - 2
    return 100, 100


# ── Window + message loop ──────────────────────────────────────────────
_HWND = None
_last_img = None


def show_menu(hwnd):
    menu = user32.CreatePopupMenu()
    user32.AppendMenuW(menu, 0, 1, "Refresh now")
    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
    user32.AppendMenuW(menu, 0, 2, "Quit")
    pt = wintypes.POINT()
    user32.GetCursorPos(byref(pt))
    user32.SetForegroundWindow(hwnd)
    cmd = user32.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                pt.x, pt.y, 0, hwnd, None)
    user32.DestroyMenu(menu)
    if cmd == 1:
        _dirty.set()
        threading.Thread(target=_one_shot_fetch, daemon=True).start()
    elif cmd == 2:
        user32.DestroyWindow(hwnd)


def _one_shot_fetch():
    tok = get_token()
    d = api_fetch(tok) if tok else None
    if d:
        _apply(d)
    else:
        STATE["status"] = "offline"
    _dirty.set()


def _animate():
    global _last_img
    _last_img = render()
    x, y = clock_pos(*_last_img.size)
    push(_HWND, _last_img, x, y)


def _refresh():
    _animate()
    _dirty.clear()
    user32.SetWindowPos(_HWND, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def wndproc(hwnd, msg, wp, lp):
    if msg == WM_RBUTTONUP:
        show_menu(hwnd)
        return 0
    if msg == WM_TIMER:
        if wp == 2:
            _animate()
        else:
            _refresh()
        return 0
    if msg == WM_DESTROY:
        global _QUIT_REQUESTED
        _QUIT_REQUESTED = True
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wp, lp)


_WNDPROC = WNDPROCTYPE(wndproc)
_QUIT_REQUESTED = False


def main():
    global _HWND
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASS()
    wc.lpfnWndProc = ctypes.cast(_WNDPROC, ctypes.c_void_p)
    wc.hInstance = hinst
    wc.hCursor = user32.LoadCursorW(0, 32512)
    wc.lpszClassName = "ClaudeUsageHUD"
    result = user32.RegisterClassW(byref(wc))
    if not result:
        err = kernel32.GetLastError()
        if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS — ok on self-restart
            raise ctypes.WinError(err)

    _HWND = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
        "ClaudeUsageHUD", "Claude usage", WS_POPUP,
        100, 100, 10, 10, None, None, hinst, None)

    threading.Thread(target=poll_loop, daemon=True).start()
    _refresh()
    user32.ShowWindow(_HWND, SW_SHOWNA)
    user32.SetTimer(_HWND, 1, TICK * 1000, None)
    user32.SetTimer(_HWND, 2, ANIM_MS, None)

    msg = wintypes.MSG()
    while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(byref(msg))
        user32.DispatchMessageW(byref(msg))


if __name__ == "__main__":
    _mutex = kernel32.CreateMutexW(None, False, "claude-usage-bar-singleton")
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    _delay = 5
    while True:
        _QUIT_REQUESTED = False
        try:
            main()
        except Exception:
            pass
        if _QUIT_REQUESTED:
            break
        time.sleep(_delay)
        _delay = min(_delay * 2, 60)
