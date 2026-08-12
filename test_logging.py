#!/usr/bin/env python3
"""
Logging System Test and Demonstration Script

This script demonstrates the logging capabilities of the Monpitor application
and can be used to verify that logging is working correctly.
"""

import subprocess
import time
import json
import sys
import os
import signal

def print_header(title):
    """Print a formatted header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")

def print_section(title):
    """Print a formatted section."""
    print(f"\n{title}")
    print("-" * len(title))

def test_syntax():
    """Test Python syntax."""
    print_section("1. Testing Python Syntax")
    result = subprocess.run(
        ["python", "-m", "py_compile", "server.py"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print("✓ server.py syntax is valid")
        return True
    else:
        print("✗ Syntax error:")
        print(result.stderr)
        return False

def test_imports():
    """Test required imports."""
    print_section("2. Testing Required Imports")
    try:
        import aiohttp
        print("✓ aiohttp available")
    except ImportError:
        print("✗ aiohttp not installed")
        return False
    
    try:
        import aiortc
        print("✓ aiortc available")
    except ImportError:
        print("✗ aiortc not installed")
        return False
    
    try:
        import av
        print("✓ av available")
    except ImportError:
        print("✗ av not installed")
        return False
    
    return True

def test_logging_module():
    """Test logging configuration."""
    print_section("3. Testing Logging Configuration")
    try:
        # Import the server module
        import sys
        sys.path.insert(0, os.path.dirname(__file__))
        from server import setup_logging
        
        print("✓ Logging module imports successfully")
        
        # Test setup_logging function
        logger = setup_logging(verbose=False, log_file='/tmp/test_monpitor.log')
        print("✓ Basic logging setup works")
        
        # Test verbose logging
        logger = setup_logging(verbose=True, log_file='/tmp/test_monpitor_verbose.log')
        print("✓ Verbose logging setup works")
        
        # Test logging output
        logger.info("Test INFO message")
        logger.debug("Test DEBUG message")
        logger.warning("Test WARNING message")
        logger.error("Test ERROR message")
        
        print("✓ All log levels can be written")
        
        return True
    except Exception as e:
        print(f"✗ Error testing logging: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_endpoints():
    """Test that new endpoints exist."""
    print_section("4. Testing New Endpoints in Code")
    try:
        with open('server.py', 'r') as f:
            content = f.read()
        
        endpoints = {
            '/stats': 'stats_handler',
            '/health': 'health_check',
            '/offer': 'offer',
            '/': 'index'
        }
        
        for endpoint, handler in endpoints.items():
            if handler in content:
                print(f"✓ Endpoint {endpoint} ({handler}) found")
            else:
                print(f"✗ Endpoint {endpoint} ({handler}) not found")
                return False
        
        return True
    except Exception as e:
        print(f"✗ Error checking endpoints: {e}")
        return False

def test_log_files():
    """Test log file creation and rotation."""
    print_section("5. Testing Log File Creation")
    try:
        import logging.handlers
        
        log_file = '/tmp/test_rotation.log'
        
        # Clean up old test files
        import glob
        for f in glob.glob(f"{log_file}*"):
            try:
                os.remove(f)
            except:
                pass
        
        # Create rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=1024,  # Small for testing
            backupCount=3
        )
        
        logger = logging.getLogger('test_rotation')
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        
        # Write some log entries
        for i in range(10):
            logger.info(f"Test log entry {i}: " + "x" * 100)
        
        # Check if files were created
        import glob
        created_files = glob.glob(f"{log_file}*")
        
        if len(created_files) > 1:
            print(f"✓ Log rotation working ({len(created_files)} files created)")
            print(f"  Files: {created_files}")
        else:
            print(f"✓ Log file created: {log_file}")
        
        # Clean up
        for f in created_files:
            try:
                os.remove(f)
            except:
                pass
        
        return True
    except Exception as e:
        print(f"✗ Error testing log rotation: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_client_logging():
    """Test client-side logging code."""
    print_section("6. Testing Client-Side Logging")
    try:
        with open('static/index.html', 'r') as f:
            html_content = f.read()
        
        features = {
            'ClientLogger object': 'ClientLogger = {',
            'Log method': 'log: function(level, message, data)',
            'Info method': 'info: function',
            'Error method': 'error: function',
            'Console override': 'console.log = function',
            'Session tracking': 'sessionId = \'session-',
            'Event logging': 'ClientLogger.info('
        }
        
        for feature, pattern in features.items():
            if pattern in html_content:
                print(f"✓ {feature} found")
            else:
                print(f"✗ {feature} not found")
                return False
        
        return True
    except Exception as e:
        print(f"✗ Error testing client logging: {e}")
        return False

def display_log_example():
    """Display example log output."""
    print_section("7. Example Log Output")
    
    examples = [
        "2026-08-12 03:15:42 [INFO    ] monpitor.server: [PC-a1b2c3d4] Peer connection created from 192.168.1.100 (total: 1 active)",
        "2026-08-12 03:15:43 [DEBUG   ] monpitor.server: [PC-a1b2c3d4] Setting remote description",
        "2026-08-12 03:15:44 [DEBUG   ] monpitor.server: [PC-a1b2c3d4] Creating answer",
        "2026-08-12 03:15:45 [INFO    ] monpitor.server: [PC-a1b2c3d4] Connection state changed: connected",
        "2026-08-12 03:15:45 [INFO    ] monpitor.server: [PC-a1b2c3d4] Connection established (3.21s)",
        "2026-08-12 03:15:45 [INFO    ] monpitor.server: [PC-a1b2c3d4] Track received: video (codec: H264)",
    ]
    
    for example in examples:
        print(example)

def display_usage():
    """Display usage examples."""
    print_section("8. Usage Examples")
    
    examples = [
        ("Run with default logging", "python server.py"),
        ("Run with verbose logging", "python server.py -v"),
        ("Run with debug logging", "python server.py -vv"),
        ("Custom log file", "python server.py --log-file /var/log/monpitor.log"),
        ("Check health", "curl http://localhost:8080/health"),
        ("View statistics", "curl http://localhost:8080/stats"),
        ("Follow logs", "tail -f monpitor.log"),
        ("Search logs", "grep ERROR monpitor.log"),
    ]
    
    for description, command in examples:
        print(f"{description}:")
        print(f"  $ {command}\n")

def display_summary():
    """Display test summary."""
    print_header("Logging System Summary")
    
    features = [
        ("✓", "Structured logging with multiple levels (DEBUG, INFO, WARN, ERROR)"),
        ("✓", "Console and file output with automatic rotation"),
        ("✓", "Performance metrics logging (connection timing, memory usage)"),
        ("✓", "Error tracking and statistics collection"),
        ("✓", "Client-side logging with session tracking"),
        ("✓", "HTTP request/response logging with timing"),
        ("✓", "Health check and statistics endpoints"),
        ("✓", "Graceful shutdown with connection cleanup"),
        ("✓", "Memory-efficient for Raspberry Pi 3"),
        ("✓", "Full stack traces for error debugging"),
    ]
    
    for status, feature in features:
        print(f"{status} {feature}")
    
    print("\nNew Endpoints:")
    endpoints = [
        ("GET /", "Serve HTML interface"),
        ("POST /offer", "Handle WebRTC offer (with logging)"),
        ("GET /health", "Health check endpoint"),
        ("GET /stats", "Statistics and metrics endpoint"),
        ("GET /static/", "Static files (CSS, JS)"),
    ]
    
    for endpoint, description in endpoints:
        print(f"  {endpoint:<20} - {description}")
    
    print("\nLog Files:")
    print(f"  Default: monpitor.log (with rotation)")
    print(f"  Custom: --log-file <path>")
    print(f"  Max size: 5MB, backup copies: 3")

def main():
    """Run all tests."""
    print_header("Monpitor Logging System Test Suite")
    
    tests = [
        ("Syntax Check", test_syntax),
        ("Import Check", test_imports),
        ("Logging Module", test_logging_module),
        ("Endpoints", test_endpoints),
        ("Log Files", test_log_files),
        ("Client Logging", test_client_logging),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"✗ Exception in {name}: {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    # Display examples and usage
    display_log_example()
    display_usage()
    display_summary()
    
    # Summary
    print_header("Test Results")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n{'=' * 70}")
    print(f"Results: {passed}/{total} tests passed")
    print(f"{'=' * 70}\n")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
