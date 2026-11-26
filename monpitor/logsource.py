"""Produces the lines MonPitor shows: a live ssh tail or a finished report."""

import asyncio
import json
import logging
import os
import re
from collections import deque

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


class LineBuffer:
    """Ring buffer of display lines with subscribers."""

    def __init__(self, size):
        self.lines = deque(maxlen=size)
        self.subscribers = set()

    def clear(self):
        self.lines.clear()
        self._emit({"reset": True})

    def add(self, raw):
        for line in format_line(raw):
            self.lines.append(line)
            self._emit({"line": line})

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


class LiveTail:
    """Runs ``ssh <host> tail -F <log>`` and restarts it when it drops."""

    def __init__(self, host_cfg, buffer, on_state):
        self.host = host_cfg
        self.buffer = buffer
        self.on_state = on_state
        self.task = None
        self.proc = None

    def start(self):
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()

    async def _run(self):
        if not self.host.ssh:
            self.on_state(f"No ssh address set for {self.host.name} in monpitor.toml")
            return
        delay = 2
        while True:
            cmd = [
                "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                self.host.ssh, f"tail -n 300 -F {self.host.log}",
            ]
            self.on_state(f"connecting to {self.host.ssh}")
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                first = True
                async for raw in self.proc.stdout:
                    if first:
                        self.on_state("")
                        first = False
                        delay = 2
                    self.buffer.add(raw.decode("utf-8", errors="replace"))
                err = (await self.proc.stderr.read()).decode(errors="replace").strip()
                await self.proc.wait()
                self.on_state(f"ssh to {self.host.ssh} ended: {err.splitlines()[-1] if err else self.proc.returncode}")
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
        buffer.add(f"──── {name} " + "─" * max(0, 60 - len(name)))
        path = os.path.join(view.report_dir, name)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    buffer.add(line)
        except OSError as e:
            buffer.add(f"(could not read: {e})")
        buffer.add("")
