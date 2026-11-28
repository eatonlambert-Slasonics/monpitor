"""Colours for log lines, shared by the HDMI console and the web page.

``spans(line)`` splits one display line into ``(text, kind)`` pieces. The
console turns kinds into ANSI colours, the web page into CSS classes.

Line shapes come from overnight-runs:
    progress.py  "[14:05:25]   project/run | Bash: git push ..."
    run.sh       "[Thu Nov 26 02:05:40 PM PST 2026] project/run finished, exit 0"
    reports      Markdown, plus MonPitor's own "──── file.md ────" separators
"""

import re
import unicodedata

PROGRESS_RE = re.compile(r"^(\[\d\d:\d\d:\d\d\])(\s+)(\S+)( \| )(.*)$")
RUNNER_RE = re.compile(r"^(\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [^\]]*\])( )(.*)$")
TOOL_RE = re.compile(r"^([A-Za-z_][\w.-]*)(: )(.*)$")
EXIT_RE = re.compile(r"exit (\d+)\s*$")

# kind -> ANSI SGR codes. Kept to the 8 base colours plus bold/dim, which the
# Linux text console draws reliably.
ANSI = {
    "time": "2",
    "name": "36",
    "sep": "2",
    "tool": "33",
    "says": "1;37",
    "error": "1;31",
    "warn": "33",
    "ok": "1;32",
    "runner": "35",
    "start": "1;35",
    "heading": "1;36",
    "rule": "35",
    "dim": "2",
}


def _message(msg):
    """Spans for the part of a progress line after "name | "."""
    if msg.startswith("says: "):
        return [("says: ", "dim"), (msg[6:], "says")]
    if msg.startswith(("tool error:", "DENIED:")):
        return [(msg, "error")]
    if msg.startswith("API retry"):
        return [(msg, "warn")]
    if msg.startswith("done: "):
        return [(msg, "ok" if msg.startswith("done: success") else "error")]
    if msg.startswith("session started"):
        return [(msg, "dim")]
    m = TOOL_RE.match(msg)
    if m:
        return [(m.group(1), "tool"), (m.group(2), "sep"), (m.group(3), "")]
    return [(msg, "")]


def _runner(msg):
    """Kind for a run.sh line's message."""
    low = msg.lower()
    if low.startswith(("warning", "unknown host")) or "not found" in low:
        return "warn"
    if low.startswith("stopping the chain") or "blocked" in low:
        return "error"
    m = EXIT_RE.search(msg)
    if m:
        return "ok" if m.group(1) == "0" else "error"
    if low.startswith("queue finished"):
        return "ok"
    if low.startswith(("starting ", "trigger found")):
        return "start"
    return "runner"


def spans(line):
    """Split one display line into (text, kind) pieces; kind "" is plain."""
    m = PROGRESS_RE.match(line)
    if m:
        return [(m.group(1), "time"), (m.group(2), ""), (m.group(3), "name"),
                (m.group(4), "sep")] + _message(m.group(5))
    m = RUNNER_RE.match(line)
    if m:
        return [(m.group(1), "time"), (m.group(2), ""), (m.group(3), _runner(m.group(3)))]
    s = line.lstrip()
    if s.startswith("────"):
        return [(line, "rule")]
    if s.startswith("#"):
        return [(line, "heading")]
    if s.startswith("> ") or line.startswith("  > "):  # stream-json tool calls
        return [(line, "tool")]
    if s.startswith("== result: success"):
        return [(line, "ok")]
    if s.startswith(("== result:", "BLOCKED")):
        return [(line, "error")]
    if s.startswith("```"):
        return [(line, "dim")]
    return [(line, "")]


def char_width(ch):
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


def ansi(pieces, width):
    """Render spans with ANSI colours, cut to ``width`` screen columns."""
    out, used = [], 0
    for text, kind in pieces:
        keep = []
        for ch in text.replace("\t", "    "):
            w = char_width(ch)
            if used + w > width:
                break
            keep.append(ch)
            used += w
        text = "".join(keep)
        code = ANSI.get(kind)
        out.append(f"\x1b[{code}m{text}\x1b[0m" if code and text else text)
        if used >= width:
            break
    return "".join(out)


def stamped(line):
    """Spans for a buffer ``Line`` with its time column in front.

    Every log line gets ``HH:MM:SS`` (``~HH:MM:SS`` when the time is a guess,
    ``--:--:--`` when unknown). progress.py lines already start with
    ``[HH:MM:SS]``, so that copy is dropped instead of showing the time twice.
    Report text and MonPitor's separators have no time column.
    """
    pieces = spans(line.text)
    if line.clock is None and not line.approx:
        return pieces
    if PROGRESS_RE.match(line.text):
        pieces = pieces[1:]
    mark = "~" if line.approx else " "
    return [(f"{mark}{line.clock or '--:--:--'} ", "time")] + pieces


def age_text(seconds):
    """How long ago, short: "8s", "4m", "2h 05m", "3d 4h"."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60:02d}m"
    return f"{s // 86400}d {s % 86400 // 3600}h"


# A live log that has said nothing for this long is shown in warning colour.
QUIET_SECONDS = 10 * 60
