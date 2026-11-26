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

log = logging.getLogger("monpitor.console")

CLEAR = "\x1b[H\x1b[2J"
HIDE_CURSOR = "\x1b[?25l"
INVERSE = "\x1b[7m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


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
        self.paused = False
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

    def set_view(self, header, note=""):
        self.header, self.note = header, note
        self.touch()

    def set_state(self, state):
        self.state = state
        self.touch()

    def touch(self):
        self.dirty.set()

    def pause(self, paused):
        """Stop drawing while a screen cast owns the display."""
        self.paused = paused
        self.touch()

    def draw(self):
        cols, rows = self.size()
        top = f" MonPitor  {self.header}"
        clock = time.strftime("%H:%M ")
        top = fit(top, cols - len(clock)).ljust(cols - len(clock)) + clock
        lines = [INVERSE + top + RESET]
        info = " ".join(x for x in (self.note, self.state) if x)
        if info:
            lines.append(DIM + fit(" " + info, cols) + RESET)
        room = rows - len(lines)
        body = list(self.buffer.lines)[-room:] if room > 0 else []
        lines += [fit(l, cols) for l in body]
        os.write(self.fd, (CLEAR + HIDE_CURSOR + "\n".join(lines)).encode("utf-8", errors="replace"))

    async def run(self):
        self.open()
        q = self.buffer.subscribe()

        async def pump():
            while True:
                await q.get()
                self.dirty.set()

        async def tick():
            while True:  # keeps the clock current and recovers after a cast
                await asyncio.sleep(30)
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
