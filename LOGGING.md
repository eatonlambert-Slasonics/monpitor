# Monpitor Logging Guide

Comprehensive logging documentation for the Raspberry Pi Wireless Monitor application.

## Overview

The Monpitor application includes robust, multi-level logging for both server-side (Python) and client-side (JavaScript) operations. Logging is designed to:

- Provide detailed diagnostic information for troubleshooting
- Track connection lifecycle and performance metrics
- Maintain low memory overhead on Raspberry Pi 3
- Enable both console and file-based log storage
- Capture errors with full stack traces for debugging

## Server-Side Logging (Python)

### Configuration

Logging is configured via the `setup_logging()` function in `server.py`:

```python
setup_logging(verbose=False, log_file=None)
```

**Parameters:**
- `verbose` (bool): Enable DEBUG level logging (default: INFO)
- `log_file` (str): Path to log file (default: `monpitor.log`)

### Running with Different Log Levels

#### Standard (INFO level)
```bash
python server.py
```
Logs important events: startup, connections, track reception, shutdown.

#### Verbose (DEBUG level)
```bash
python server.py -v
# or
python server.py --verbose
```
Logs detailed diagnostic information: SDP negotiation, ICE gathering, request timing.

#### Multiple Verbosity Levels
```bash
python server.py -vv  # Maximum debug output
```

#### Custom Log File Location
```bash
python server.py --log-file /var/log/monpitor/server.log
```

### Log Output Formats

#### Console Format (Human-Readable)
```
2026-08-12 03:15:42 [INFO    ] monpitor.server: [PC-a1b2c3d4] Peer connection created from 192.168.1.100 (total: 1 active)
2026-08-12 03:15:44 [INFO    ] monpitor.server: [PC-a1b2c3d4] Connection established (2.15s)
```

#### File Format (Detailed with Function Names)
```
2026-08-12 03:15:42 [INFO    ] monpitor.server - offer(): [PC-a1b2c3d4] Peer connection created from 192.168.1.100 (total: 1 active)
2026-08-12 03:15:44 [INFO    ] monpitor.server - on_connectionstatechange(): [PC-a1b2c3d4] Connection established (2.15s)
```

### Log Rotation

Log files are automatically rotated when they exceed 5MB:

- **Max file size:** 5MB
- **Backup count:** 3 rotated files kept
- **Naming:** `monpitor.log`, `monpitor.log.1`, `monpitor.log.2`, `monpitor.log.3`

This prevents excessive disk usage on Raspberry Pi storage.

### Log Levels Explained

| Level | Description | Example Events |
|-------|-------------|-----------------|
| **DEBUG** | Detailed diagnostic information | SDP details, ICE candidates, request timing, buffer content |
| **INFO** | General informational events | Connection created, stream started, data flows |
| **WARNING** | Warning conditions (recoverable) | Invalid offer format, connection attempts with failures |
| **ERROR** | Error conditions (failures requiring attention) | Connection failures, JSON parse errors, exception traces |

### Key Logged Events

#### Server Startup
```
========================================================
Monpitor WebRTC Server Starting
========================================================
Host: 0.0.0.0
Port: 8080
Process ID: 12345
Log Level: DEBUG
Ready to accept connections
========================================================
```

#### Connection Lifecycle
```
[PC-a1b2c3d4] Peer connection created from 192.168.1.100 (total: 1 active)
[PC-a1b2c3d4] Setting remote description
[PC-a1b2c3d4] Creating answer
[PC-a1b2c3d4] Sending answer to 192.168.1.100
[PC-a1b2c3d4] Connection state changed: connecting
[PC-a1b2c3d4] Connection established (2.15s)
[PC-a1b2c3d4] Track received: video (codec: H264)
[PC-a1b2c3d4] Connection state changed: disconnected
```

#### Error Scenarios
```
[PC-a1b2c3d4] Connection failed
[PC-a1b2c3d4] Track ended: video (ended: 1 total)
[PC-a1b2c3d4] Connection closed (active: 0)
Error handling offer: Connection reset by peer
```

#### Graceful Shutdown
```
========================================================
Monpitor WebRTC Server Shutting Down
========================================================
Active connections: 1
Closing peer connection: <RTCPeerConnection object>
All connections closed
Final Statistics: {'connections_total': 5, 'connections_active': 0, ...}
Shutdown complete
========================================================
```

### Statistics Tracking

The server tracks detailed statistics available via the `/stats` endpoint:

```bash
curl http://localhost:8080/stats
```

**Response:**
```json
{
  "timestamp": "2026-08-12T03:15:45.123456",
  "stats": {
    "connections_total": 5,
    "connections_active": 1,
    "connections_failed": 2,
    "tracks_received": 5,
    "tracks_ended": 4,
    "errors": 0
  },
  "connections_active": 1
}
```

**Fields:**
- `connections_total`: All connections ever created
- `connections_active`: Currently active connections
- `connections_failed`: Failed connection attempts
- `tracks_received`: Video/audio tracks received
- `tracks_ended`: Completed tracks
- `errors`: Total errors encountered

### Health Check Endpoint

Check server health:

```bash
curl http://localhost:8080/health
```

**Response:**
```json
{
  "status": "healthy",
  "active_connections": 1,
  "timestamp": "2026-08-12T03:15:45.123456"
}
```

### HTTP Request Logging

All HTTP requests are logged with timing information:

```
DEBUG GET / -> 200 (15.32ms) [192.168.1.100]
DEBUG POST /offer -> 200 (245.67ms) [192.168.1.100]
DEBUG GET /stats -> 200 (5.23ms) [192.168.1.100]
```

Includes:
- HTTP method and path
- Response status code
- Request duration in milliseconds
- Client IP address

## Client-Side Logging (JavaScript)

### ClientLogger Object

A comprehensive logging system built into the HTML interface:

```javascript
ClientLogger.info('Message', {optional: 'data'});
ClientLogger.debug('Debug info', {details: 'here'});
ClientLogger.warn('Warning', {reason: 'something'});
ClientLogger.error('Error', {error: 'details'});
```

### Automatic Console Override

All console output is automatically captured:

```javascript
console.log('message')   // Logged as INFO
console.debug('info')    // Logged as DEBUG
console.warn('warning')  // Logged as WARN
console.error('error')   // Logged as ERROR
```

### Session Tracking

Each cast session is assigned a unique session ID:

```
session-1691841342000-a1b2c3d4e5f6g7h8
```

All logs for a session include this ID for correlation.

### Key Client-Side Events Logged

#### Page Load
```
Page loaded and ready
Browser capabilities: {
  "hasWebRTC": true,
  "hasGetDisplayMedia": true
}
```

#### Cast Initiation
```
Cast session starting: {
  "sessionId": "session-1691841342000-a1b2c3d4e5f6g7h8"
}
```

#### Display Media Acquisition
```
Display media acquired: {
  "tracks": 1,
  "videoTracks": 1
}
```

#### WebRTC Peer Connection
```
Creating peer connection
RTCPeerConnection created: {
  "config": {
    "sdpSemantics": "unified-plan",
    "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
  }
}
```

#### Connection States
```
Connection state changed: connecting
ICE connection state changed: {
  "state": "checking",
  "connected": false
}
ICE connection state changed: {
  "state": "connected",
  "connected": true
}
```

#### Successful Connection
```
Offer created: {
  "type": "offer",
  "sdpLength": 1234
}
Sending offer to server: {
  "sessionId": "session-1691841342000-a1b2c3d4e5f6g7h8"
}
Offer sent successfully
Answer received from server: {
  "type": "answer",
  "sdpLength": 567
}
Remote description set - connection negotiation complete
Cast session established successfully: {
  "sessionId": "session-1691841342000-a1b2c3d4e5f6g7h8"
}
```

#### Error Scenarios
```
Cast session failed: {
  "sessionId": "session-1691841342000-a1b2c3d4e5f6g7h8",
  "error": "User canceled the dialog",
  "stack": "Error: User canceled the dialog\n    at start (index.html:...)"
}
```

### Viewing Client Logs

#### In Browser Console

Open Developer Tools (F12) and check Console tab. All logs appear with timestamps and levels.

#### Programmatic Access

Access collected logs:

```javascript
// Get all logs
const allLogs = ClientLogger.getLogs();

// Latest 10 logs
const recent = ClientLogger.getLogs().slice(-10);

// Filter by level
const errors = ClientLogger.getLogs().filter(l => l.level === 'ERROR');
```

#### Maximum Log Capacity

- Client logs stored in memory: Max 100 entries
- Oldest entries automatically removed when limit exceeded
- Prevents excessive memory usage on client

## Debugging Workflows

### Connection Failure Troubleshooting

1. **Check server logs:**
   ```bash
   tail -f monpitor.log
   ```
   Look for `Connection failed` or error messages

2. **Enable verbose logging:**
   ```bash
   python server.py -v
   ```

3. **Check client logs:**
   - Open browser DevTools (F12)
   - Go to Console tab
   - Look for red error messages or connection state changes

4. **Monitor in real-time:**
   - Server: `tail -f monpitor.log`
   - Client: DevTools Console
   - Stats endpoint: `watch -n 1 'curl -s http://localhost:8080/stats | jq'`

### Performance Analysis

1. **Check connection timing:**
   ```
   [PC-a1b2c3d4] Connection established (2.15s)
   ```
   Connection took 2.15 seconds to establish.

2. **Monitor active connections:**
   ```bash
   curl http://localhost:8080/stats | jq '.stats.connections_active'
   ```

3. **Check request latency:**
   ```
   DEBUG POST /offer -> 200 (245.67ms)
   ```
   WebRTC negotiation took 245ms.

### Memory Monitoring

Check memory usage:

```bash
ps aux | grep server.py
# Check RSS column for actual memory usage

# Or use psutil if installed
python -c "import psutil; p = psutil.Process(); print(f'Memory: {p.memory_info().rss / 1024 / 1024:.1f}MB')"
```

Expected memory usage:
- Idle: 40-60 MB
- Streaming: 100-150 MB

### Error Investigation

When errors occur:

1. **Full stack traces logged** in file with `exc_info=True`
2. **Error counters incremented** in stats
3. **Exception details captured** with context

Example error log:
```
ERROR monpitor.server - offer(): [PC-a1b2c3d4] Error handling offer: ...
Traceback (most recent call last):
  File "server.py", line 145, in offer
    ...
ValueError: Invalid SDP format
```

## Log Files Location

### Default Location
```
/home/tone/projects/monpitor/monpitor.log
```

### Custom Location
```bash
python server.py --log-file /tmp/monpitor.log
```

### Viewing Log Files

```bash
# View last 50 lines
tail -50 monpitor.log

# Follow log in real-time
tail -f monpitor.log

# Search for errors
grep ERROR monpitor.log

# Count connection attempts
grep "Peer connection created" monpitor.log | wc -l

# View specific session
grep "PC-a1b2c3d4" monpitor.log
```

### Log Analysis

```bash
# Count connection failures
grep "Connection failed" monpitor.log | wc -l

# Average connection time
grep "Connection established" monpitor.log | grep -oP '\(\K[0-9.]+' | awk '{s+=$1; c++} END {print s/c}'

# Error distribution
grep ERROR monpitor.log | cut -d: -f3 | sort | uniq -c
```

## Best Practices

### For Operators

1. **Monitor logs during testing:**
   ```bash
   tail -f monpitor.log
   ```

2. **Enable verbose logging only when needed:**
   - Production: Normal (INFO)
   - Troubleshooting: Verbose (-v)
   - Deep debugging: Extra verbose (-vv)

3. **Rotate logs regularly:**
   - Automatic rotation at 5MB
   - Manually clean old logs: `rm monpitor.log.[0-9]`

4. **Save logs before troubleshooting:**
   ```bash
   cp monpitor.log monpitor.log.backup-$(date +%s)
   ```

### For Developers

1. **Add logging to new features:**
   ```python
   logger.debug(f"[{pc_id}] Custom operation: {status}")
   ```

2. **Use appropriate log levels:**
   - DEBUG: Detailed flow information
   - INFO: Significant events
   - WARNING: Recoverable issues
   - ERROR: Failures requiring attention

3. **Include context in logs:**
   ```python
   logger.info(f"[{pc_id}] Connection from {client_ip}")  # Good
   logger.info("Connection created")  # Bad - missing context
   ```

4. **Client-side logging pattern:**
   ```javascript
   ClientLogger.info('Event name', {key: 'value', status: 'ok'});
   ```

## Performance Impact

Logging overhead on Raspberry Pi 3:

| Scenario | CPU Impact | Memory Impact |
|----------|-----------|----------------|
| Logging disabled | Baseline | ~10MB less |
| INFO level | <2% | ~5-10MB |
| DEBUG level | 2-5% | ~5-10MB |
| File logging (5MB) | <1% | <1MB (buffered) |

Recommend:
- Production: INFO level, file logging
- Testing: DEBUG level, file logging
- Troubleshooting: DEBUG level, watch log file real-time

## Conclusion

The comprehensive logging system provides visibility into every aspect of the Monpitor application, from connection negotiation to error handling. Use the appropriate log levels and monitoring techniques for your operational needs.

For support, review logs with verbose mode enabled and check the `/stats` and `/health` endpoints for system status.
