"""Draws the current view on the Pi's HDMI text console (no desktop needed)."""

import asyncio
import fcntl
import logging
import os
import shutil
import struct
import termios
import time
import unicodedata

from monpitor.style import QUIET_SECONDS, age_text, ansi, stamped

log = logging.getLogger("monpitor.console")

HOME = "\x1b[H"
CLEAR_EOL = "\x1b[K"
CLEAR_BELOW = "\x1b[J"
HIDE_CURSOR = "\x1b[?25l"
INVERSE = "\x1b[7m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
YELLOW = "\x1b[1;33m"


def fit(text, width):
    """Cut a line to the screen width, counting wide characters as two."""
    out, used = [], 0
    for ch in text.replace("\t", "    "):
        w = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out)


class ConsoleRenderer:
    """Redraws the console at most a few times a second."""

    def __init__(self, tty, buffer):
        self.tty_path = tty
        self.buffer = buffer
        self.header = ""
        self.note = ""
        self.state = ""
        self.live = False
        self.paused = False
        self.full_clear = True
        self.dirty = asyncio.Event()
        self.fd = None

    def open(self):
        try:
            self.fd = os.open(self.tty_path, os.O_WRONLY | os.O_NOCTTY)
        except OSError as e:
            log.warning("Console %s not available (%s); writing to stdout", self.tty_path, e)
            self.fd = 1

    def size(self):
        try:
            rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(self.fd, termios.TIOCGWINSZ, b"\0" * 8))
            if rows and cols:
                return cols, rows
        except OSError:
            pass
        return tuple(shutil.get_terminal_size((100, 30)))

    def set_view(self, header, note="", live=False):
        self.header, self.note, self.live = header, note, live
        self.touch()

    def set_state(self, state):
        self.state = state
        self.touch()

    def touch(self):
        self.dirty.set()

    def pause(self, paused):
        """Stop drawing while a screen cast owns the display."""
        self.paused = paused
        self.full_clear = True  # wipe whatever the cast left on screen
        self.touch()

    def freshness(self, now=None):
        """("last line 11:27:05, 3m ago", quiet) for a live log, else ("", False)."""
        when = self.buffer.activity
        if not self.live:
            return "", False
        if when is None:
            return "no log lines yet", False
        now = time.time() if now is None else now
        age = now - when
        text = f"last line {time.strftime('%H:%M:%S', time.localtime(when))}, {age_text(age)} ago"
        return text, age >= QUIET_SECONDS

    def draw(self):
        cols, rows = self.size()
        # One column spare: erasing to end of line on a full-width line would eat its last letter.
        cols = max(10, cols - 1)
        top = f" MonPitor  {self.header}"
        clock = time.strftime("now %H:%M:%S ")
        top = fit(top, cols - len(clock)).ljust(cols - len(clock)) + clock
        lines = [INVERSE + top + RESET]
        fresh, quiet = self.freshness()
        info = " · ".join(x for x in (self.note, self.state) if x)
        if fresh:
            fresh_txt = fit(" " + fresh, cols)
            rest = fit("  " + info, cols - len(fresh_txt)) if info else ""
            lines.append((YELLOW if quiet else "") + fresh_txt + RESET + DIM + rest + RESET)
        elif info:
            lines.append(DIM + fit(" " + info, cols) + RESET)
        room = rows - len(lines)
        # Always the newest lines: the bottom of the buffer fills the bottom of the screen.
        body = list(self.buffer.lines)[-room:] if room > 0 else []
        lines += [ansi(stamped(l), cols) for l in body]
        # Overwrite in place instead of clearing first, so the screen doesn't flicker.
        start = HOME + ("\x1b[2J" if self.full_clear else "")
        self.full_clear = False
        out = start + HIDE_CURSOR + (CLEAR_EOL + "\n").join(lines) + CLEAR_EOL + CLEAR_BELOW
        os.write(self.fd, out.encode("utf-8", errors="replace"))

    async def run(self):
        self.open()
        q = self.buffer.subscribe()

        async def pump():
            while True:
                await q.get()
                self.dirty.set()

        async def tick():
            while True:  # keeps the clock and "Xm ago" current, and recovers after a cast
                await asyncio.sleep(1)
                self.dirty.set()

        asyncio.create_task(pump())
        asyncio.create_task(tick())
        while True:
            await self.dirty.wait()
            self.dirty.clear()
            if not self.paused:
                try:
                    self.draw()
                except OSError as e:
                    log.warning("Console draw failed: %s", e)
            await asyncio.sleep(0.25)
