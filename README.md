# Claude Usage Bar

A tiny always-on-top Windows desktop widget that shows your **Claude Code session and weekly usage** at a glance.

![Widget](preview.png)

```
● S 9%  1h53m    W 98%  53m
```

| Label | Meaning |
|-------|---------|
| **S** | 5-hour session usage % |
| **W** | 7-day weekly usage % |
| countdown | time until the window resets |

Color thresholds: cream < 75% — amber 75–89% — red ≥ 90%

---

## Requirements

- Windows 10 or 11
- Python 3.10+
- [Pillow](https://pypi.org/project/pillow/) (`pip install pillow`)

---

## Quick start

```bash
pip install pillow
python make_icon.py          # generates claude-usage.ico (run once)
pythonw claude_usage_bar.pyw # launch the widget (no console window)
```

The widget appears bottom-right above your clock. Drag it anywhere.

---

## Auto-start on boot

1. Press `Win + R` and run: `shell:startup`
2. Create a shortcut to `claude_usage_bar.pyw` in that folder.
3. Set the shortcut's icon to `claude-usage.ico` for the proper logo.

---

## Usage

| Action | Effect |
|--------|--------|
| Drag | Move widget anywhere on screen |
| Right-click | Refresh now / Quit |
| Auto | Refreshes every 2 minutes |

---

## How it works

Reads usage data from the Claude API using the same OAuth token that Claude Code stores locally at `~/.claude/.credentials.json`. No extra setup needed — if Claude Code is authenticated, this widget works automatically.

---

## License

MIT
