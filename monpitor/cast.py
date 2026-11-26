"""Screen-cast mode: a browser sends its screen over WebRTC, the Pi shows it full screen.

The original MonPitor negotiated the connection but dropped the video. Here the
received frames are scaled down and piped as raw YUV into mpv, which draws
straight to the HDMI output (``--vo=drm``) and covers the log console while a
cast is live. When the cast ends, mpv exits and the log view comes back.

Untested on the Pi so far. The Pi 3 decodes WebRTC video in software, so expect
roughly 720p at a modest frame rate; ``cast.max_width`` trades sharpness for speed.
"""

import asyncio
import logging
import time
import uuid

from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError

log = logging.getLogger("monpitor.cast")


def scaled_size(width, height, max_width):
    """Fit within max_width keeping aspect ratio; both sides even for yuv420p."""
    if width > max_width:
        height = height * max_width // width
        width = max_width
    return width - width % 2, height - height % 2


def frame_bytes(frame):
    """Packed yuv420p bytes of a frame, without the per-row padding PyAV may add."""
    out = bytearray()
    for i, plane in enumerate(frame.planes):
        w = frame.width if i == 0 else frame.width // 2
        h = frame.height if i == 0 else frame.height // 2
        data = memoryview(plane)
        if plane.line_size == w:
            out += data[: w * h]
        else:
            for row in range(h):
                start = row * plane.line_size
                out += data[start:start + w]
    return bytes(out)


class Player:
    """One mpv process fed raw frames of a fixed size."""

    def __init__(self, cmd, width, height):
        self.cmd, self.width, self.height = cmd, width, height
        self.proc = None

    async def start(self):
        args = [
            self.cmd, "--no-terminal", "--really-quiet", "--vo=drm", "--hwdec=no",
            "--untimed", "--no-cache", "--profile=low-latency",
            "--demuxer=rawvideo", f"--demuxer-rawvideo-w={self.width}",
            f"--demuxer-rawvideo-h={self.height}", "--demuxer-rawvideo-mp-format=yuv420p",
            "--demuxer-rawvideo-fps=30", "-",
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

    async def write(self, data):
        self.proc.stdin.write(data)
        await self.proc.stdin.drain()

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), 2)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()


class CastReceiver:
    """Accepts one cast at a time; a new cast replaces the old one."""

    def __init__(self, cfg, on_active):
        self.cfg = cfg
        self.on_active = on_active
        self.pc = None
        self.pc_id = ""
        self.started = None
        self.frames = 0

    def status(self):
        return {
            "active": self.pc is not None and self.pc.connectionState == "connected",
            "id": self.pc_id,
            "frames": self.frames,
            "seconds": round(time.time() - self.started, 1) if self.started else 0,
        }

    async def close(self):
        if self.pc:
            pc, self.pc = self.pc, None
            await pc.close()
        self.started = None
        self.on_active(False)

    async def accept(self, sdp, kind):
        """Answer a browser's offer and start receiving its screen."""
        await self.close()
        pc = RTCPeerConnection()
        self.pc, self.pc_id, self.frames = pc, f"cast-{uuid.uuid4().hex[:6]}", 0

        @pc.on("connectionstatechange")
        async def on_state():
            log.info("[%s] %s", self.pc_id, pc.connectionState)
            if pc.connectionState in ("failed", "closed") and self.pc is pc:
                await self.close()

        @pc.on("track")
        def on_track(track):
            log.info("[%s] track %s", self.pc_id, track.kind)
            if track.kind == "video":
                asyncio.create_task(self._show(pc, track))

        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=kind))
        await pc.setLocalDescription(await pc.createAnswer())
        return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

    async def _show(self, pc, track):
        player = None
        self.started = time.time()
        self.on_active(True)
        try:
            while self.pc is pc:
                frame = await track.recv()
                w, h = scaled_size(frame.width, frame.height, self.cfg.cast_max_width)
                if player is None or (player.width, player.height) != (w, h):
                    if player:
                        await player.stop()
                    player = Player(self.cfg.cast_player, w, h)
                    await player.start()
                    log.info("[%s] showing %dx%d", self.pc_id, w, h)
                frame = frame.reformat(width=w, height=h, format="yuv420p")
                await player.write(frame_bytes(frame))
                self.frames += 1
        except (MediaStreamError, ConnectionError, BrokenPipeError) as e:
            log.info("[%s] cast ended: %s", self.pc_id, type(e).__name__)
        except Exception:
            log.exception("[%s] cast display failed", self.pc_id)
        finally:
            if player:
                await player.stop()
            if self.pc is pc:
                await self.close()
