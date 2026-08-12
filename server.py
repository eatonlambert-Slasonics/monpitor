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

"""
Monpitor WebRTC Signaling Server

A lightweight WebRTC signaling and media relay server optimized for Raspberry Pi 3.
Handles peer connection negotiation via the Offer/Answer protocol and manages
bidirectional media streams.

Architecture:
- Signaling: HTTP-based SDP negotiation endpoints (/offer, /stats, /health)
- Peer Connections: Maintains active RTCPeerConnection objects for each client
- Media Relay: Optional media relay for connection routing and stream management
- Logging: Comprehensive async logging with file rotation

Key Features:
- Asynchronous I/O for efficient resource usage on constrained hardware
- WebRTC SDP offer/answer negotiation
- Connection state tracking and metrics
- Graceful shutdown with connection cleanup
- Comprehensive error handling and logging

Performance Optimizations:
- Low memory footprint for Raspberry Pi 3 (1GB RAM)
- Non-blocking I/O with asyncio
- Efficient media relay using aiortc MediaRelay
- Rotating file logs to prevent disk fill
"""

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
    """
    Serve the main HTML interface for the WebRTC monitor.
    
    Loads and returns the index.html static file to clients accessing the root path.
    This provides the browser-based UI for WebRTC peer connection monitoring.
    
    Args:
        request: aiohttp.web.Request object containing client connection information
    
    Returns:
        web.Response: HTML content with content-type text/html
        web.Response (500): On file read or processing errors
    """
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
    """
    Handle WebRTC SDP offer and generate answer for peer connection negotiation.
    
    This is the core signaling endpoint implementing the WebRTC offer/answer exchange:
    1. Receives SDP (Session Description Protocol) offer from client browser
    2. Creates a new RTCPeerConnection on the server
    3. Sets the remote description (client's offer) on the peer connection
    4. Generates a local answer with server capabilities
    5. Returns the answer SDP back to the client
    
    The client then uses this answer to establish the WebRTC connection.
    This endpoint handles the server side of the WebRTC signaling protocol.
    
    Args:
        request: aiohttp.web.Request containing JSON payload with:
            - sdp (str): Session Description Protocol string from client offer
            - type (str): Description type (should be "offer")
    
    Returns:
        web.Response (200): JSON with answer SDP and type on success
        web.Response (400): On missing/invalid offer parameters
        web.Response (500): On SDP processing or peer connection errors
    
    Side Effects:
        - Creates a new RTCPeerConnection and adds it to the pcs set
        - Registers event handlers for connection state changes and track reception
        - Updates connection statistics (total, active, failed)
    """
    pc = None
    pc_id = None
    connection_start_time = None
    
    # ==================== WebRTC SIGNALING FLOW ====================
    # This endpoint implements the server-side of the WebRTC Offer/Answer model:
    #
    # CLIENT (Browser)                  SIGNALING (HTTP)              SERVER
    # ==================              =================              =========
    #         |                                                          |
    #         |  1. Generate Offer                                       |
    #         |     (codecs, ICE candidates)                             |
    #         |                                                          |
    #         |  2. POST /offer (with offer SDP)                         |
    #         |----------------------------------------------------->    |
    #         |                                                          |
    #         |                     3. Create RTCPeerConnection          |
    #         |                        Set remote description (offer)    |
    #         |                        Create answer (server capabilities)|
    #         |                        Set local description (answer)    |
    #         |                                                          |
    #         |  4. HTTP 200 (with answer SDP)                           |
    #         |<-----------------------------------------------------    |
    #         |                                                          |
    #         |  5. Set remote description (answer)                      |
    #         |     Begin ICE candidate gathering & exchange             |
    #         |                                                          |
    #         |  6. Exchange ICE candidates via signaling                |
    #         |  ======> (ICE trickle) <======                           |
    #         |                                                          |
    #         |  7. DTLS-SRTP connection established                     |
    #         |<========== WebRTC Media Flow (encrypted) =========>      |
    #         |                                                          |
    #
    # After successful negotiation, both client and server maintain their
    # RTCPeerConnection objects and can exchange media streams directly
    # using the established DTLS-SRTP tunnel. The server monitors connection
    # state changes, received tracks, and handles graceful disconnection.
    #
    try:
        client_ip = request.remote or 'unknown'
        
        # ========== STAGE 1: PARSE SIGNALING MESSAGE ==========
        # Receive and validate the SDP offer from the client browser.
        # The offer contains the client's media capabilities and ICE candidates info.
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
        
        # ========== STAGE 2: CREATE PEER CONNECTION ==========
        # Initialize a new RTCPeerConnection on the server. Each client gets a unique
        # peer connection object that will handle the bidirectional WebRTC communication.
        # The connection state machine manages: new -> connecting -> connected/failed -> closed
        offer = RTCSessionDescription(sdp=offer_sdp, type=offer_type)
        pc = RTCPeerConnection()
        pc_id = f"PC-{uuid.uuid4().hex[:8]}"
        connection_start_time = time.time()
        
        pcs.add(pc)
        stats['connections_total'] += 1
        stats['connections_active'] += 1
        
        logger.info(f"[{pc_id}] Peer connection created from {client_ip} (total: {stats['connections_active']} active)")
        
        # ========== STAGE 3: REGISTER CONNECTION STATE HANDLER ==========
        # Monitor peer connection lifecycle events. This callback fires when the connection
        # state changes (connected, failed, disconnected, closed). Used to track metrics and
        # clean up resources when connections end.
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
            # ========== STAGE 4B: RECEIVE REMOTE MEDIA TRACKS ==========
            # When the remote peer sends audio/video, this handler is triggered.
            # Each track represents a stream (audio or video) from the client.
            # Register track-ended handler to detect when client stops sending media.
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
        
        # ========== STAGE 4A: ANSWER NEGOTIATION ==========
        # Create an answer SDP that describes our server's media capabilities
        # and network configuration, based on the client's offer.
        answer = await pc.createAnswer()
        
        logger.debug(f"[{pc_id}] Setting local description")
        await pc.setLocalDescription(answer)
        logger.debug(f"[{pc_id}] Local description set")
        
        response_data = {
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        }
        
        # ========== STAGE 5: SEND ANSWER BACK TO CLIENT ==========
        # Return the answer SDP to the client. The client will set this as their
        # remote description, completing the SDP negotiation. After this, both
        # sides have agreed on media formats, codecs, and connection parameters.
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
    """
    Return real-time application statistics and connection metrics.
    
    Provides a JSON snapshot of the server's current state including:
    - Total connections created since startup
    - Currently active peer connections
    - Failed connection attempts
    - Received and ended media tracks
    - Application errors encountered
    
    Used by monitoring dashboards to display server health and connection stats.
    
    Args:
        request: aiohttp.web.Request object
    
    Returns:
        web.Response: JSON object with timestamp, stats dictionary, and active connection count
    """
    return web.Response(
        content_type="application/json",
        text=json.dumps({
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
            "connections_active": len(pcs)
        }, indent=2)
    )

async def health_check(request):
    """
    Perform basic health check and return server status.
    
    Provides a lightweight endpoint for monitoring systems to verify the server
    is running and accepting connections. Includes current active connection count.
    
    Args:
        request: aiohttp.web.Request object
    
    Returns:
        web.Response: JSON object with status, active connection count, and current timestamp
    """
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
    """
    Application startup lifecycle hook.
    
    Initializes and logs the server startup sequence. Displays configuration,
    process information, and readiness status. Called once when the aiohttp
    server starts accepting connections.
    
    Args:
        app: aiohttp.web.Application instance containing host and port configuration
    """
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
    """
    Application shutdown lifecycle hook.
    
    Gracefully terminates all active peer connections and logs shutdown metrics.
    Ensures all WebRTC connections are properly closed before server stops,
    preventing resource leaks and unclean client disconnections.
    
    Args:
        app: aiohttp.web.Application instance
    
    Side Effects:
        - Closes all RTCPeerConnection objects in the pcs set
        - Clears the pcs set
        - Logs final statistics
    """
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
    """
    HTTP request/response logging middleware.
    
    Logs all incoming HTTP requests and outgoing responses with timing information
    and client IP address. Tracks both successful responses and exceptions.
    Captures performance metrics and error diagnostics.
    
    Args:
        request: aiohttp.web.Request object
        handler: Callable async function that processes the request
    
    Returns:
        web.Response: Response from the handler
    
    Side Effects:
        - Logs request method, path, status code, duration, and client IP
        - Increments stats['errors'] on exception
        - Re-raises exceptions for further processing
    """
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
