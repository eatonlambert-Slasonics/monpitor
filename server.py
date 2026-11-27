"""MonPitor: a Raspberry Pi display for overnight-runs logs, with a screen-cast mode.

Log mode (default): shows the live log of whichever overnight run is selected in
the overnight-runs repo (``monitor/target``), or a finished run's report. It is
drawn on the HDMI text console and also served at ``/`` for any browser.

Cast mode: open ``/cast`` on a laptop, press Cast, and the Pi shows that screen
full screen until the cast stops. Then the log view comes back.
"""

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import ssl

from aiohttp import web

from monpitor import config as config_mod
from monpitor.console import ConsoleRenderer
from monpitor.logsource import LineBuffer, LiveTail, load_report
from monpitor.target import TargetWatcher

ROOT = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("monpitor")


def setup_logging(verbose, log_file):
    """Log to stderr (journald) and a small rotating file."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.handlers.RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2))
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)
    for noisy in ("aioice", "aiortc", "aiohttp.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class Monitor:
    """Ties the target watcher, the log source and the outputs together."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.buffer = LineBuffer(cfg.buffer_lines)
        self.console = ConsoleRenderer(cfg.tty, self.buffer) if cfg.console else None
        self.watcher = TargetWatcher(cfg, self.set_view)
        self.tail = None
        self.view = None
        self.state = ""
        self.cast = None
        self.casting = False
        self.web_clients = set()
        if cfg.cast_enabled:
            try:
                from monpitor.cast import CastReceiver  # aiortc is only needed for cast mode
                self.cast = CastReceiver(cfg, self.set_casting)
            except ImportError as e:
                # Keep the log display running on Pis where aiortc/av didn't install (e.g. 32-bit OS).
                log.warning("Cast mode off: %s. Install aiortc and av to enable it.", e)

    def set_view(self, view):
        asyncio.create_task(self._apply(view))

    async def _apply(self, view):
        same_live = (self.view and self.view.kind == view.kind == "live" and self.view.host == view.host)
        self.view = view
        if not same_live:
            if self.tail:
                await self.tail.stop()
                self.tail = None
            self.buffer.clear()
            if view.kind == "live":
                self.tail = LiveTail(self.cfg.hosts.get(view.host) or config_mod.HostConfig(view.host),
                                     self.buffer, self.set_state)
                self.tail.start()
            elif view.kind == "report":
                self.set_state("")
                load_report(view, self.buffer)
            else:
                self.set_state("")
        if self.console:
            self.console.set_view(view.title, view.note)
        self.broadcast()

    def set_state(self, state):
        self.state = state
        if self.console:
            self.console.set_state(state)
        self.broadcast()

    def set_casting(self, active):
        self.casting = active
        if self.console:
            self.console.pause(active)
        self.broadcast()

    def snapshot(self):
        v = self.view
        return {
            "title": v.title if v else "Starting",
            "kind": v.kind if v else "empty",
            "host": v.host if v else "",
            "project": v.project if v else "",
            "note": v.note if v else "",
            "state": self.state,
            "casting": self.casting,
            "repo_error": self.watcher.error,
        }

    def broadcast(self):
        msg = {"view": self.snapshot()}
        for q in list(self.web_clients):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass


# ==================== HTTP handlers ====================

async def page(name):
    path = os.path.join(ROOT, "static", name)

    async def handler(request):
        return web.FileResponse(path)
    return handler


async def api_state(request):
    mon = request.app["monitor"]
    return web.json_response({**mon.snapshot(), "lines": list(mon.buffer.lines)[-500:]})


async def api_events(request):
    """Server-sent events: view changes and new log lines."""
    mon = request.app["monitor"]
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    lines = mon.buffer.subscribe()
    views = asyncio.Queue(maxsize=100)
    mon.web_clients.add(views)
    try:
        await resp.write(f"data: {json.dumps({'view': mon.snapshot(), 'reset': True})}\n\n".encode())
        for line in list(mon.buffer.lines)[-500:]:
            await resp.write(f"data: {json.dumps({'line': line})}\n\n".encode())
        while True:
            getters = [asyncio.create_task(lines.get()), asyncio.create_task(views.get())]
            done, pending = await asyncio.wait(getters, timeout=20, return_when=asyncio.FIRST_COMPLETED)
            for p in pending:
                p.cancel()
            if not done:
                await resp.write(b": keepalive\n\n")
            for d in done:
                await resp.write(f"data: {json.dumps(d.result())}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        mon.buffer.unsubscribe(lines)
        mon.web_clients.discard(views)
    return resp


async def offer(request):
    mon = request.app["monitor"]
    if not mon.cast:
        return web.json_response({"error": "Cast mode is turned off in monpitor.toml"}, status=404)
    try:
        params = await request.json()
        sdp, kind = params["sdp"], params["type"]
    except (ValueError, KeyError):
        return web.json_response({"error": "Expected JSON with sdp and type"}, status=400)
    try:
        return web.json_response(await mon.cast.accept(sdp, kind))
    except Exception as e:
        log.exception("Cast offer failed")
        return web.json_response({"error": str(e)}, status=500)


async def cast_stop(request):
    mon = request.app["monitor"]
    if mon.cast:
        await mon.cast.close()
    return web.json_response({"ok": True})


async def health(request):
    mon = request.app["monitor"]
    return web.json_response({
        "status": "ok",
        "view": mon.snapshot(),
        "cast": mon.cast.status() if mon.cast else None,
    })


async def build_app(cfg):
    mon = Monitor(cfg)
    app = web.Application()
    app["monitor"] = mon
    app.router.add_get("/", await page("index.html"))
    app.router.add_get("/cast", await page("cast.html"))
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/events", api_events)
    app.router.add_post("/offer", offer)
    app.router.add_post("/cast/stop", cast_stop)
    app.router.add_get("/health", health)
    app.router.add_static("/static/", os.path.join(ROOT, "static"))

    async def start(app):
        app["tasks"] = [asyncio.create_task(mon.watcher.run())]
        if mon.console:
            app["tasks"].append(asyncio.create_task(mon.console.run()))

    async def stop(app):
        for t in app["tasks"]:
            t.cancel()
        if mon.tail:
            await mon.tail.stop()
        if mon.cast:
            await mon.cast.close()

    app.on_startup.append(start)
    app.on_shutdown.append(stop)
    return app


def main():
    parser = argparse.ArgumentParser(description="MonPitor overnight-runs display")
    parser.add_argument("--config", default=os.path.join(ROOT, "monpitor.toml"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-console", action="store_true", help="Do not draw on the HDMI console")
    parser.add_argument("--https-port", type=int, default=8443,
                        help="HTTPS port for /cast; browsers only allow screen capture on HTTPS")
    parser.add_argument("--cert", default=os.path.join(ROOT, "certs", "monpitor.crt"))
    parser.add_argument("--key", default=os.path.join(ROOT, "certs", "monpitor.key"))
    parser.add_argument("--log-file", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    setup_logging(args.verbose, args.log_file)
    cfg = config_mod.load(args.config)
    if args.no_console:
        cfg.console = False
    log.info("MonPitor on %s:%d, repo %s", args.host, args.port, cfg.checkout_path)
    asyncio.run(serve(cfg, args))


async def serve(cfg, args):
    """Serve HTTP for the log page and, when a cert exists, HTTPS for casting."""
    runner = web.AppRunner(await build_app(cfg))
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    if os.path.exists(args.cert) and os.path.exists(args.key):
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(args.cert, args.key)
        await web.TCPSite(runner, args.host, args.https_port, ssl_context=ctx).start()
        log.info("Cast page: https://<pi>:%d/cast", args.https_port)
    else:
        log.warning("No TLS cert at %s: browsers will refuse screen capture over plain HTTP", args.cert)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    main()
