# Monpitor Logging Quick Start

Fast reference guide for using the comprehensive logging system.

## Quick Commands

### Start with Normal Logging (INFO level)
```bash
python server.py
```
Shows important events: connections, tracks, errors.

### Start with Debug Logging (DEBUG level)
```bash
python server.py -v
```
Shows detailed diagnostics: SDP negotiation, ICE gathering, timing.

### Watch Logs in Real-Time
```bash
tail -f monpitor.log
```

### View Statistics
```bash
curl http://localhost:8080/stats
```

### Check Server Health
```bash
curl http://localhost:8080/health
```

## Log Levels

| Command | Level | Use Case |
|---------|-------|----------|
| `python server.py` | INFO | Normal operation |
| `python server.py -v` | DEBUG | Troubleshooting |
| `python server.py -vv` | DEBUG | Deep debugging |

## Common Log Patterns

### Connection Established
```
[PC-a1b2c3d4] Connection established (2.15s)
```
Normal and expected.

### Connection Failed
```
[PC-a1b2c3d4] Connection failed
```
Check logs before this message for root cause.

### Track Received
```
[PC-a1b2c3d4] Track received: video (codec: H264)
```
Stream successfully started.

### Error
```
ERROR [PC-a1b2c3d4] Error handling offer: ...
```
Check full error message for details.

## Troubleshooting Checklist

### 1. Connection Issues
```bash
# Check if server is running
curl http://localhost:8080/health

# View logs with verbose mode
python server.py -v &
tail -f monpitor.log

# Look for these patterns:
# - "Connection state changed: connected" (good)
# - "Connection failed" (bad - check earlier logs)
```

### 2. Browser Console Debugging
1. Open browser DevTools (F12)
2. Go to Console tab
3. Look for:
   - Red error messages (failures)
   - Yellow warnings (issues)
   - Blue info messages (events)

### 3. Performance Issues
```bash
# Check statistics
curl http://localhost:8080/stats | jq '.stats'

# Monitor memory
ps aux | grep server.py | grep -v grep
# Check RSS column (in KB)

# Monitor logs for timing
grep "Connection established" monpitor.log | tail -5
```

### 4. Find Specific Sessions
```bash
# List unique session IDs
grep "session-" monpitor.log | cut -d' ' -f3 | sort -u

# View all logs for a session
grep "session-XXXXX" monpitor.log
```

## Log File Management

### Default Location
```
./monpitor.log
```

### Files Created
- `monpitor.log` - Current log file
- `monpitor.log.1` - Previous log
- `monpitor.log.2` - Older log
- `monpitor.log.3` - Oldest log (auto-deleted)

### Manual Cleanup
```bash
# Backup current log
cp monpitor.log monpitor.log.backup-$(date +%s)

# Remove old logs
rm monpitor.log.[0-9]

# Clear current log
> monpitor.log
```

## Key Metrics to Monitor

### Connection Statistics
```bash
# View stats endpoint
curl http://localhost:8080/stats

# Count connections today
grep "$(date +%Y-%m-%d)" monpitor.log | grep "Peer connection created" | wc -l

# Average connection time
grep "Connection established" monpitor.log | grep -oP '\(\K[0-9.]+(?=s\))' | awk '{s+=$1; c++} END {printf "%.2f\n", s/c}'
```

### Active Connections
```bash
# Current active connections
curl http://localhost:8080/stats | jq '.stats.connections_active'

# Failed connections
curl http://localhost:8080/stats | jq '.stats.connections_failed'
```

### Error Rate
```bash
# Count errors
grep "ERROR" monpitor.log | wc -l

# Error types
grep "ERROR" monpitor.log | grep -oP '(?<=: )[^,]+' | sort | uniq -c
```

## Browser Debugging

### View Client Logs
```javascript
// In browser console:
ClientLogger.getLogs()

// Last 10 logs
ClientLogger.getLogs().slice(-10)

// All errors
ClientLogger.getLogs().filter(l => l.level === 'ERROR')

// Export as JSON
JSON.stringify(ClientLogger.getLogs(), null, 2)
```

### Filter Logs
```javascript
// By level
ClientLogger.getLogs().filter(l => l.level === 'DEBUG')

// By message
ClientLogger.getLogs().filter(l => l.message.includes('Connection'))

// By session
ClientLogger.getLogs().filter(l => l.data && l.data.sessionId)
```

## Performance Tips

### Memory Usage
- Expected: 40-60 MB idle, 100-150 MB streaming
- Check with: `ps aux | grep server.py`

### CPU Usage
- Expected: <5% idle, 30-50% during 1080p stream
- Monitor: `top -p $(pgrep -f server.py)`

### Log File Size
- Max per file: 5 MB
- Backup copies: 3
- Auto rotation prevents disk fill

## Integration with Monitoring

### Prometheus Metrics
```bash
# Parse logs for metrics
grep "Connection established" monpitor.log | wc -l
grep "ERROR" monpitor.log | wc -l
curl http://localhost:8080/stats | jq '.stats'
```

### Send to Syslog
```bash
# Linux only - forward to syslog
python server.py | tee >(nc localhost 514 -u)
```

### Log Aggregation
```bash
# Tail and forward to ELK, Splunk, etc.
tail -f monpitor.log | logstash-forwarder
```

## Advanced Usage

### Rotate Logs Manually
```bash
# Force rotation without restarting
kill -USR1 $(pgrep -f server.py)
```

### Change Log Level at Runtime
```python
# In Python interactive session with running server
import logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)  # Change level
```

### Parse and Analyze
```bash
# Connection duration analysis
grep "Connection established" monpitor.log | \
  sed -E 's/.*\(([0-9.]+)s\)/\1/' | \
  awk '{s+=$1; c++} END {printf "Avg: %.2fs, Count: %d\n", s/c, c}'

# Error distribution
grep "ERROR" monpitor.log | \
  sed -E 's/.*: ([^,]+).*/\1/' | \
  sort | uniq -c | sort -rn
```

## Support

For detailed logging documentation, see [LOGGING.md](LOGGING.md)

For troubleshooting help, follow these steps:
1. Run with verbose logging (`python server.py -v`)
2. Reproduce the issue
3. Check logs: `grep ERROR monpitor.log`
4. Check stats: `curl http://localhost:8080/stats`
5. Check browser console (F12 → Console tab)

---

**Last Updated:** 2026-08-12  
**Version:** 1.0  
**Logging Version:** 2.0 (Robust)
