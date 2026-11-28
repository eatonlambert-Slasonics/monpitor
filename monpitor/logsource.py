"""Produces the lines MonPitor shows: a live ssh tail or a finished report."""

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass

log = logging.getLogger("monpitor.logs")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def format_line(raw):
    """Make one log line readable.

    Plain lines pass through with colour codes removed. Lines that look like
    Claude Code ``--output-format stream-json`` events are reduced to their text
    or tool name, so a streamed run reads like a transcript.

    Returns:
        A list of display lines (may be empty for events worth hiding).
    """
    raw = ANSI_RE.sub("", raw.rstrip("\n"))
    s = raw.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return [raw]
    try:
        ev = json.loads(s)
    except ValueError:
        return [raw]
    if not isinstance(ev, dict) or "type" not in ev:
        return [raw]
    t = ev.get("type")
    if t in ("assistant", "user"):
        out = []
        for part in (ev.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and t == "assistant":
                out.extend(part.get("text", "").splitlines())
            elif part.get("type") == "tool_use":
                inp = part.get("input") or {}
                detail = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("description") or ""
                out.append(f"  > {part.get('name')} {str(detail)[:200]}".rstrip())
        return out
    if t == "result":
        return [f"== result: {ev.get('subtype', '')} {ev.get('result', '')[:300] if isinstance(ev.get('result'), str) else ''}".rstrip()]
    if t == "system":
        return [f"== {ev.get('subtype', 'system')}"]
    return []


# Times a log line already carries: progress.py "[14:05:25] ..." and
# run.sh "[Thu Nov 26 02:05:40 PM PST 2026] ...".
PROGRESS_TIME_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\s")
RUNNER_TIME_RE = re.compile(r"^\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [^\]]*?(\d{1,2}):(\d\d):(\d\d)(?: ?([AP]M))?[^\]]*\]")
MARK = "@@monpitor"


def own_time(text):
    """The HH:MM:SS a log line was written at, if the line says so."""
    m = PROGRESS_TIME_RE.match(text)
    if m:
        return m.group(1)
    m = RUNNER_TIME_RE.match(text)
    if m:
        h, mi, se, ampm = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if ampm == "PM" and h < 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{mi}:{se}"
    return None


@dataclass
class Line:
    """One display line and when it was written.

    Attributes:
        text: The line.
        clock: "HH:MM:SS" it was written, or None (report text, separators).
        approx: True when the time is a guess: a line from before MonPitor
            connected that has no time of its own takes the last time seen above it.
    """

    text: str
    clock: str | None = None
    approx: bool = False


class LineBuffer:
    """Ring buffer of display lines with subscribers.

    ``activity`` is when the log last got a new line, in the Pi's clock (epoch
    seconds), or None when unknown or not a live log.
    """

    def __init__(self, size):
        self.lines = deque(maxlen=size)
        self.subscribers = set()
        self.activity = None
        self._carry = None

    def clear(self):
        self.lines.clear()
        self.activity = None
        self._carry = None
        self._emit({"reset": True})

    def set_activity(self, when):
        """Record when the log was last written (from the file's modification time)."""
        if self.activity is None or when > self.activity:
            self.activity = when
        self._emit({"activity": self.activity})

    def add(self, raw, when=None, backlog=False):
        """Add one raw log line.

        Args:
            raw: The line as read.
            when: Epoch seconds it arrived, for a line that is new right now.
            backlog: True for lines written before MonPitor connected, whose
                arrival time says nothing about when they were written.
        """
        if when is not None and not backlog:
            self.activity = when
        for text in format_line(raw):
            clock = own_time(text)
            approx = False
            if clock:
                self._carry = clock
            elif backlog:
                clock, approx = self._carry, True
            elif when is not None:
                clock = time.strftime("%H:%M:%S", time.localtime(when))
                self._carry = clock
            self.append(Line(text, clock, approx))

    def note(self, text):
        """Add a MonPitor separator line (no time column)."""
        self.append(Line(text))

    def append(self, line):
        self.lines.append(line)
        self._emit({"line": line, "activity": self.activity})

    def _emit(self, msg):
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # a slow web client drops lines rather than stalling the display

    def subscribe(self):
        q = asyncio.Queue(maxsize=5000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)


def tail_command(log_path, offset, backlog=300):
    """Shell script run over ssh to follow the log.

    It prints ``@@monpitor <size> <mtime> <now>`` first, so MonPitor knows how
    long ago the log was written without trusting the two clocks to agree. Then
    the last ``backlog`` lines, ``@@monpitor-live <byte>``, and everything from
    that byte on as it is written. After a dropped connection ``offset`` resumes
    where the last one stopped, so nothing is repeated or skipped (run.log is
    only ever appended to; if it shrank, it starts over).
    """
    f = log_path  # left unquoted so the remote shell expands ~
    return (
        f's=$(stat -c %s {f} 2>/dev/null || echo 0); '
        f'printf "{MARK} %s %s %s\\n" "$s" "$(stat -c %Y {f} 2>/dev/null || echo 0)" "$(date +%s)"; '
        f'if [ {int(offset)} -gt 0 ] && [ "$s" -ge {int(offset)} ]; then '
        f'echo "{MARK}-live {int(offset)}"; exec tail -c +{int(offset) + 1} -F {f}; fi; '
        f'head -c "$s" {f} 2>/dev/null | tail -n {int(backlog)}; '
        f'echo "{MARK}-live $s"; exec tail -c +$((s+1)) -F {f}'
    )


class LiveTail:
    """Follows the log over ssh and reconnects when it drops."""

    def __init__(self, host_cfg, buffer, on_state):
        self.host = host_cfg
        self.buffer = buffer
        self.on_state = on_state
        self.task = None
        self.proc = None
        self.offset = 0  # bytes of the log already shown

    def start(self):
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()

    def feed(self, raw, phase):
        """Handle one line from ssh. Returns the new phase.

        Phases: "start" (waiting for the header), "backlog", "live".
        """
        text = raw.decode("utf-8", errors="replace")
        if phase == "start" and text.startswith(MARK + " "):
            try:
                self.size, mtime, rnow = (int(x) for x in text.split()[1:4])
            except ValueError:
                return "backlog"
            if mtime > 0:
                self.buffer.set_activity(time.time() - max(0, rnow - mtime))
            return "backlog"
        if phase != "live" and text.startswith(MARK + "-live "):
            try:
                pos = int(text.split()[1])
            except (IndexError, ValueError):
                pos = 0
            resumed = self.offset > 0
            self.offset = pos
            now = time.strftime("%H:%M:%S")
            if resumed:
                self.buffer.note(f"──── reconnected {now} · ~ = written while disconnected, time estimated ")
            else:
                self.buffer.note(f"──── live from {now} · ~ = earlier line, time estimated ")
            return "live"
        if phase == "live":
            # Bytes before the size at connect time were written while away.
            catching_up = self.offset < getattr(self, "size", 0)
            self.offset += len(raw)
            self.buffer.add(text, when=None if catching_up else time.time(), backlog=catching_up)
            return "live"
        self.buffer.add(text, backlog=True)
        return phase

    async def _run(self):
        if not self.host.ssh:
            self.on_state(f"No ssh address set for {self.host.name} in monpitor.toml")
            return
        delay = 2
        while True:
            cmd = [
                "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                self.host.ssh, tail_command(self.host.log, self.offset),
            ]
            self.on_state(f"connecting to {self.host.ssh}")
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                phase = "start"
                async for raw in self.proc.stdout:
                    if phase == "start":
                        self.on_state("")
                        delay = 2
                    phase = self.feed(raw, phase)
                err = (await self.proc.stderr.read()).decode(errors="replace").strip()
                await self.proc.wait()
                self.on_state(f"ssh to {self.host.ssh} ended at {time.strftime('%H:%M')}: "
                              f"{err.splitlines()[-1] if err else self.proc.returncode}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.on_state(f"ssh failed: {e}")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


def load_report(view, buffer):
    """Fill the buffer with a finished run's report files."""
    buffer.clear()
    for name in view.files:
        buffer.note(f"──── {name} " + "─" * max(0, 60 - len(name)))
        path = os.path.join(view.report_dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    buffer.add(line)
        except OSError as e:
            buffer.add(f"(could not read: {e})")
        buffer.add("")
