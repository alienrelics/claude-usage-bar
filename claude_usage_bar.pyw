"""
Claude Usage Bar — desktop widget for Windows
Shows session (5h) and weekly (7d) Claude Code usage percentages
as a small always-on-top dark pill, pinned bottom-right above the clock.

Drag to move  ·  right-click to refresh or quit  ·  auto-refreshes every 2 min

Requirements: pip install pillow
Run with:     pythonw claude_usage_bar.pyw
"""

import json
import os
import ssl
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk

REFRESH = 120   # seconds between API polls
CRED  = Path.home() / ".claude" / ".credentials.json"
CACHE = Path(os.environ.get("TEMP", "/tmp")) / "claude-usage-bar-cache.json"
ICON  = Path(__file__).parent / "claude-usage.ico"

# ── Palette ────────────────────────────────────────────────────────────
BG      = "#0e0e14"
BORDER  = "#2a2a38"
DOT_OK  = "#5fd38d"
DOT_ERR = "#f87171"
LBL_C   = "#6a6a80"
RST_C   = "#45455a"
OK_C    = "#f4f1ec"
WARN_C  = "#ffb066"
CRIT_C  = "#f87171"
OFF_C   = "#5a5a6e"

STATE = {"s": 0, "w": 0, "s_iso": None, "w_iso": None, "status": "starting"}


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
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Content-Type": "application/json",
        },
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
            d = json.loads(r.read().decode())
            with open(CACHE, "w") as f:
                json.dump({"ts": time.time(), "d": d}, f)
            return d
    except Exception:
        pass
    # Fall back to cache (up to 10 min old)
    try:
        with open(CACHE) as f:
            c = json.load(f)
        if time.time() - c["ts"] < 600:
            return c["d"]
    except Exception:
        pass
    return None


def countdown(iso):
    """Return compact time-until string like '55m', '2h30m', '4d3h'."""
    if not iso:
        return ""
    try:
        s = int(
            (
                datetime.fromisoformat(iso.replace("Z", "+00:00"))
                - datetime.now(timezone.utc)
            ).total_seconds()
        )
        if s <= 0:
            return "now"
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        m = s // 60
        if d:
            return f"{d}d{h}h"
        if h:
            return f"{h}h{m}m"
        return f"{m}m"
    except Exception:
        return ""


def pct_color(p):
    if p is None:
        return OFF_C
    if p >= 90:
        return CRIT_C
    if p >= 75:
        return WARN_C
    return OK_C


# ── Widget ─────────────────────────────────────────────────────────────
class UsageWidget:
    W = 282
    H = 44

    def __init__(self):
        # Hidden root keeps the window out of the taskbar / Alt+Tab
        self._root = tk.Tk()
        self._root.withdraw()

        self.win = tk.Toplevel(self._root)
        self.win.title("Claude Usage")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.93)
        self.win.configure(bg=BG)
        self.win.resizable(False, False)

        if ICON.exists():
            try:
                self._root.iconbitmap(str(ICON))
                self.win.iconbitmap(str(ICON))
            except Exception:
                pass

        # Position: bottom-right above taskbar
        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self.win.geometry(f"{self.W}x{self.H}+{sw - self.W - 6}+{sh - self.H - 48}")

        # Layout
        outer = tk.Frame(self.win, bg=BORDER, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=BG, padx=10, pady=0)
        inner.pack(fill="both", expand=True)
        inner.grid_rowconfigure(0, weight=1)

        self.dot = tk.Label(inner, text="●", fg=DOT_OK, bg=BG, font=("Consolas", 8))
        self.dot.grid(row=0, column=0, padx=(0, 6))

        tk.Label(inner, text="S", fg=LBL_C, bg=BG,
                 font=("Consolas", 9, "bold")).grid(row=0, column=1, padx=(0, 3))
        self.s_val = tk.Label(inner, text="--", fg=OK_C, bg=BG,
                              font=("Consolas", 13, "bold"))
        self.s_val.grid(row=0, column=2, padx=(0, 3))
        self.s_rst = tk.Label(inner, text="", fg=RST_C, bg=BG, font=("Consolas", 8))
        self.s_rst.grid(row=0, column=3, padx=(0, 12))

        tk.Label(inner, text="W", fg=LBL_C, bg=BG,
                 font=("Consolas", 9, "bold")).grid(row=0, column=4, padx=(0, 3))
        self.w_val = tk.Label(inner, text="--", fg=OK_C, bg=BG,
                              font=("Consolas", 13, "bold"))
        self.w_val.grid(row=0, column=5, padx=(0, 3))
        self.w_rst = tk.Label(inner, text="", fg=RST_C, bg=BG, font=("Consolas", 8))
        self.w_rst.grid(row=0, column=6)

        self._drag_x = self._drag_y = 0
        for w in self._all_widgets(self.win):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-3>", self._show_menu)

        self._menu = tk.Menu(
            self._root, tearoff=0,
            bg="#16161f", fg="#c8c8dc",
            activebackground="#2a2a40", activeforeground="#ffffff",
            font=("Consolas", 10),
        )
        self._menu.add_command(label="Refresh", command=self._refresh_now)
        self._menu.add_separator()
        self._menu.add_command(label="Quit", command=self._quit)

        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ── helpers ────────────────────────────────────────────────────────
    def _all_widgets(self, parent):
        yield parent
        for child in parent.winfo_children():
            yield from self._all_widgets(child)

    def _drag_start(self, e):
        self._drag_x = e.x_root - self.win.winfo_x()
        self._drag_y = e.y_root - self.win.winfo_y()

    def _drag_move(self, e):
        self.win.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    def _show_menu(self, e):
        try:
            self._menu.tk_popup(e.x_root, e.y_root)
        finally:
            self._menu.grab_release()

    def _quit(self):
        self._root.quit()

    # ── data ───────────────────────────────────────────────────────────
    def _apply_state(self):
        ok = STATE["status"] == "ok"
        self.dot.configure(fg=DOT_OK if ok else DOT_ERR)
        s = STATE["s"] if ok else None
        w = STATE["w"] if ok else None
        self.s_val.configure(text=f"{s}%" if s is not None else "--", fg=pct_color(s))
        self.w_val.configure(text=f"{w}%" if w is not None else "--", fg=pct_color(w))
        self.s_rst.configure(text=countdown(STATE["s_iso"]) if ok else "")
        self.w_rst.configure(text=countdown(STATE["w_iso"]) if ok else "")

    def _fetch_once(self):
        try:
            tok = get_token()
            d = api_fetch(tok) if tok else None
            if d:
                fh = d.get("five_hour") or {}
                sd = d.get("seven_day") or {}
                STATE["s"] = round(fh.get("utilization", 0))
                STATE["w"] = round(sd.get("utilization", 0))
                STATE["s_iso"] = fh.get("resets_at")
                STATE["w_iso"] = sd.get("resets_at")
                STATE["status"] = "ok"
            else:
                STATE["status"] = "offline"
        except Exception:
            STATE["status"] = "offline"
        self._root.after(0, self._apply_state)

    def _poll_loop(self):
        while True:
            self._fetch_once()
            time.sleep(REFRESH)

    def _refresh_now(self):
        threading.Thread(target=self._fetch_once, daemon=True).start()

    def _tick_countdown(self):
        if STATE["status"] == "ok":
            self.s_rst.configure(text=countdown(STATE["s_iso"]))
            self.w_rst.configure(text=countdown(STATE["w_iso"]))
        self._root.after(30000, self._tick_countdown)

    def run(self):
        self._tick_countdown()
        self._root.mainloop()


if __name__ == "__main__":
    UsageWidget().run()
