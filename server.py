import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import ssl
import time
import uuid
from datetime import datetime

from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

ROOT = os.path.dirname(__file__)

# ==================== Logging Configuration ====================

def setup_logging(verbose=False, log_file=None):
    """
    Configure application logging with console and optional file handlers.
    
    Args:
        verbose: Enable DEBUG level logging (default: INFO)
        log_file: Path to log file (optional, default: None)
    
    Returns:
        logger instance
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Create formatters
    console_formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)-8s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)-8s] %(name)s - %(funcName)s(): %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler with rotation (5MB max, keep 3 backups)
    if log_file is None:
        log_file = os.path.join(ROOT, 'monpitor.log')
    
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        logger.info(f"File logging enabled: {log_file}")
    except IOError as e:
        logger.warning(f"Could not create file handler for {log_file}: {e}")
    
    return logger

# ==================== Application State ====================

logger = logging.getLogger("monpitor.server")
pcs = set()
relay = MediaRelay()
stats = {
    'connections_total': 0,
    'connections_active': 0,
    'connections_failed': 0,
    'tracks_received': 0,
    'tracks_ended': 0,
    'errors': 0
}
connection_start_times = {}

# ==================== Request Handlers ====================

async def index(request):
    """Serve the main HTML interface."""
    try:
        client_ip = request.remote or 'unknown'
        logger.info(f"Serving UI to {client_ip}")
        
        content = open(os.path.join(ROOT, "static/index.html"), "r").read()
        logger.debug(f"UI content loaded ({len(content)} bytes)")
        
        return web.Response(content_type="text/html", text=content)
    except Exception as e:
        logger.error(f"Error serving index: {e}", exc_info=True)
        stats['errors'] += 1
        return web.Response(status=500, text="Internal Server Error")

async def offer(request):
    """Handle WebRTC offer negotiation."""
    pc = None
    pc_id = None
    connection_start_time = None
    
    try:
        client_ip = request.remote or 'unknown'
        
        # Parse request
        try:
            params = await request.json()
            offer_sdp = params.get("sdp")
            offer_type = params.get("type")
            
            if not offer_sdp or not offer_type:
                logger.warning(f"Invalid offer from {client_ip}: missing sdp or type")
                stats['errors'] += 1
                return web.Response(
                    status=400,
                    content_type="application/json",
                    text=json.dumps({"error": "Missing sdp or type"})
                )
            
            logger.debug(f"Offer received from {client_ip}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error from {client_ip}: {e}")
            stats['errors'] += 1
            return web.Response(
                status=400,
                content_type="application/json",
                text=json.dumps({"error": "Invalid JSON"})
            )
        
        # Create peer connection
        offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
        pc = RTCPeerConnection()
        pc_id = f"PC-{uuid.uuid4().hex[:8]}"
        connection_start_time = time.time()
        
        pcs.add(pc)
        stats['connections_total'] += 1
        stats['connections_active'] += 1
        
        logger.info(f"[{pc_id}] Peer connection created from {client_ip} (total: {stats['connections_active']} active)")
        
        # Connection state change handler
        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            state = pc.connectionState
            logger.info(f"[{pc_id}] Connection state changed: {state}")
            
            if state == "connected":
                duration = time.time() - connection_start_time
                logger.info(f"[{pc_id}] Connection established ({duration:.2f}s)")
            
            elif state == "failed":
                stats['connections_failed'] += 1
                stats['connections_active'] = max(0, stats['connections_active'] - 1)
                logger.warning(f"[{pc_id}] Connection failed")
                try:
                    await pc.close()
                except Exception as e:
                    logger.error(f"[{pc_id}] Error closing connection: {e}")
                finally:
                    pcs.discard(pc)
            
            elif state == "disconnected":
                stats['connections_active'] = max(0, stats['connections_active'] - 1)
                logger.info(f"[{pc_id}] Connection disconnected (active: {stats['connections_active']})")
            
            elif state == "closed":
                stats['connections_active'] = max(0, stats['connections_active'] - 1)
                logger.info(f"[{pc_id}] Connection closed (active: {stats['connections_active']})")
                pcs.discard(pc)
        
        # Track handler
        @pc.on("track")
        def on_track(track):
            stats['tracks_received'] += 1
            logger.info(f"[{pc_id}] Track received: {track.kind} (codec: {track.codec_context.codec.name if hasattr(track, 'codec_context') else 'unknown'})")
            logger.debug(f"[{pc_id}] Track details - kind: {track.kind}, mid: {track.mid}")
            
            @track.on("ended")
            async def on_ended():
                stats['tracks_ended'] += 1
                logger.info(f"[{pc_id}] Track ended: {track.kind} (ended: {stats['tracks_ended']} total)")
        
        # Set remote description
        logger.debug(f"[{pc_id}] Setting remote description")
        await pc.setRemoteDescription(offer)
        logger.debug(f"[{pc_id}] Remote description set")
        
        # Create and set local description
        logger.debug(f"[{pc_id}] Creating answer")
        answer = await pc.createAnswer()
        
        logger.debug(f"[{pc_id}] Setting local description")
        await pc.setLocalDescription(answer)
        logger.debug(f"[{pc_id}] Local description set")
        
        response_data = {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
        
        logger.info(f"[{pc_id}] Sending answer to {client_ip}")
        return web.Response(
            content_type="application/json",
            text=json.dumps(response_data)
        )
    
    except Exception as e:
        stats['errors'] += 1
        logger.error(f"[{pc_id}] Error handling offer: {e}", exc_info=True)
        
        # Clean up peer connection on error
        if pc:
            try:
                await pc.close()
            except Exception as close_error:
                logger.error(f"[{pc_id}] Error closing failed connection: {close_error}")
            finally:
                pcs.discard(pc)
                stats['connections_active'] = max(0, stats['connections_active'] - 1)
        
        return web.Response(
            status=500,
            content_type="application/json",
            text=json.dumps({"error": str(e)})
        )

async def stats_handler(request):
    """Return application statistics."""
    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
            "connections_active": len(pcs)
        }, indent=2)
    )

async def health_check(request):
    """Health check endpoint."""
    logger.debug(f"Health check from {request.remote}")
    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "status": "healthy",
            "active_connections": len(pcs),
            "timestamp": datetime.now().isoformat()
        })
    )

# ==================== Lifecycle Handlers ====================

async def on_startup(app):
    """Log application startup."""
    logger.info("=" * 60)
    logger.info("Monpitor WebRTC Server Starting")
    logger.info("=" * 60)
    logger.info(f"Host: {app['host']}")
    logger.info(f"Port: {app['port']}")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info(f"Log Level: {'DEBUG' if logger.level == logging.DEBUG else 'INFO'}")
    logger.info("Ready to accept connections")
    logger.info("=" * 60)

async def on_shutdown(app):
    """Gracefully shutdown all connections."""
    logger.info("=" * 60)
    logger.info("Monpitor WebRTC Server Shutting Down")
    logger.info("=" * 60)
    logger.info(f"Active connections: {len(pcs)}")
    
    # Close all peer connections
    coros = []
    for pc in list(pcs):
        logger.info(f"Closing peer connection: {pc}")
        coros.append(pc.close())
    
    if coros:
        await asyncio.gather(*coros, return_exceptions=True)
    
    pcs.clear()
    logger.info("All connections closed")
    logger.info(f"Final Statistics: {stats}")
    logger.info("Shutdown complete")
    logger.info("=" * 60)

# ==================== Middleware ====================

@web.middleware
async def logging_middleware(request, handler):
    """Log HTTP requests and responses."""
    start_time = time.time()
    
    try:
        response = await handler(request)
        duration = time.time() - start_time
        
        # Log successful requests
        logger.debug(
            f"{request.method} {request.path} -> {response.status} ({duration*1000:.2f}ms) "
            f"[{request.remote}]"
        )
        
        return response
    
    except web.HTTPException as e:
        duration = time.time() - start_time
        logger.warning(
            f"{request.method} {request.path} -> {e.status} ({duration*1000:.2f}ms) "
            f"[{request.remote}]"
        )
        raise
    
    except Exception as e:
        duration = time.time() - start_time
        logger.error(
            f"{request.method} {request.path} raised exception ({duration*1000:.2f}ms) "
            f"[{request.remote}]: {e}",
            exc_info=True
        )
        stats['errors'] += 1
        raise

# ==================== Main ====================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WebRTC monitor server for Raspberry Pi"
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host for HTTP server (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for HTTP server (default: 8080)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="count",
        default=0,
        help="Enable verbose logging (DEBUG level)"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to log file (default: monpitor.log in project root)"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(verbose=args.verbose > 0, log_file=args.log_file)
    
    # Create and configure app
    app = web.Application(middlewares=[logging_middleware])
    app['host'] = args.host
    app['port'] = args.port
    
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    # Routes
    app.router.add_get("/", index)
    app.router.add_post("/offer", offer)
    app.router.add_get("/stats", stats_handler)
    app.router.add_get("/health", health_check)
    app.router.add_static("/static/", path=os.path.join(ROOT, "static"), name="static")
    
    logger.info(f"Starting server on {args.host}:{args.port}")
    web.run_app(app, host=args.host, port=args.port, print=lambda *args: None)
