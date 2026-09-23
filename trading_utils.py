"""
TRADING UTILITIES - Common Fixes for Autonomous Operation
═══════════════════════════════════════════════════════════════════════════════

Addresses fault analysis findings:
- API retry wrapper (HIGH-4)
- Timeout wrapper (MEDIUM-8)
- Cache cleanup (MEDIUM-3)
- Time sync verification (MEDIUM-1)
- JSON backup/recovery (MEDIUM-2)

Author: System Fault Analysis Fixes
Date: 2026-01-20
Version: 1.0.0
"""

import os
import json
import time
import shutil
import threading
import functools
import gc
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable, Any, Dict

logger = logging.getLogger('TradingUtils')


# ═══════════════════════════════════════════════════════════════════════════
# KITE API RETRY WRAPPER (Fixes HIGH-4: Gateway Timeout)
# ═══════════════════════════════════════════════════════════════════════════

def kite_api_retry(max_retries=3, backoff_factor=2, timeout=30):
    """
    Decorator to add retry logic to Kite API calls.
    
    Handles:
    - 502/504 Gateway errors
    - Timeout errors
    - Connection errors
    
    Args:
        max_retries: Number of retry attempts
        backoff_factor: Exponential backoff multiplier
        timeout: Timeout in seconds
        
    Usage:
        @kite_api_retry(max_retries=3)
        def get_quote(self, symbol):
            return self.kite.quote([f"NSE:{symbol}"])
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                    
                except Exception as e:
                    last_exception = e
                    error_str = str(e).lower()
                    
                    # Retry on gateway/timeout errors
                    should_retry = any(x in error_str for x in [
                        '502', '504', 'gateway', 'timeout', 
                        'timed out', 'connection', 'network'
                    ])
                    
                    if should_retry and attempt < max_retries - 1:
                        wait = backoff_factor ** attempt
                        logger.warning(
                            f"Kite API error (attempt {attempt+1}/{max_retries}), "
                            f"retry in {wait}s: {e}"
                        )
                        time.sleep(wait)
                    else:
                        # Don't retry on other errors or last attempt
                        raise
            
            raise last_exception
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════════
# TIMEOUT WRAPPER (Fixes MEDIUM-8: Deadlock Detection)
# ═══════════════════════════════════════════════════════════════════════════

def run_with_timeout(func: Callable, timeout: int = 30, 
                     func_args: tuple = (), func_kwargs: dict = None) -> tuple:
    """
    Run a function with timeout protection.
    
    Returns:
        (result, exception) tuple
        - If successful: (result, None)
        - If timeout: (None, TimeoutError)
        - If error: (None, Exception)
        
    Usage:
        result, error = run_with_timeout(
            expensive_function, 
            timeout=60,
            func_args=(arg1, arg2)
        )
        if error:
            handle_error(error)
    """
    if func_kwargs is None:
        func_kwargs = {}
    
    result = [None]
    exception = [None]
    
    def target():
        try:
            result[0] = func(*func_args, **func_kwargs)
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        error = TimeoutError(f"{func.__name__} timed out after {timeout}s")
        logger.error(f"⚠️ Thread timeout: {error}")
        return None, error
    
    return result[0], exception[0]


# ═══════════════════════════════════════════════════════════════════════════
# CACHE CLEANUP (Fixes MEDIUM-3: Memory Leak)
# ═══════════════════════════════════════════════════════════════════════════

class CacheManager:
    """
    Manages cache cleanup to prevent memory leaks.
    
    Usage:
        cache_mgr = CacheManager()
        cache_mgr.register_cache('news', news_cache, max_age_minutes=30)
        cache_mgr.cleanup_all()  # Call periodically
    """
    
    def __init__(self):
        self.caches = {}
    
    def register_cache(self, name: str, cache_dict: dict, 
                       max_age_minutes: int = 30):
        """Register a cache for automatic cleanup"""
        self.caches[name] = {
            'cache': cache_dict,
            'max_age': timedelta(minutes=max_age_minutes)
        }
    
    def cleanup_all(self):
        """Clean all registered caches"""
        now = datetime.now()
        total_removed = 0
        
        for name, config in self.caches.items():
            cache = config['cache']
            max_age = config['max_age']
            cutoff = now - max_age
            
            # Cache entries should be: {key: (timestamp, value)}
            initial_size = len(cache)
            
            # Remove old entries
            keys_to_remove = [
                k for k, v in cache.items()
                if isinstance(v, tuple) and len(v) >= 2 and v[0] < cutoff
            ]
            
            for key in keys_to_remove:
                del cache[key]
            
            removed = initial_size - len(cache)
            if removed > 0:
                logger.info(f"Cleaned cache '{name}': removed {removed} entries")
                total_removed += removed
        
        # Force garbage collection
        if total_removed > 0:
            gc.collect()
            logger.info(f"Total cache entries removed: {total_removed}")


# ═══════════════════════════════════════════════════════════════════════════
# TIME SYNC VERIFICATION (Fixes MEDIUM-1)
# ═══════════════════════════════════════════════════════════════════════════

def verify_system_time(max_drift_seconds: int = 5) -> tuple:
    """
    Verify system time against NTP server.
    
    Returns:
        (is_synced, offset_seconds, message)
    """
    try:
        import ntplib
        
        ntp = ntplib.NTPClient()
        response = ntp.request('time.google.com', version=3, timeout=5)
        offset = response.offset
        
        if abs(offset) > max_drift_seconds:
            return (
                False, 
                offset,
                f"⚠️ System clock drift: {offset:.1f}s (max: {max_drift_seconds}s)"
            )
        else:
            return (
                True,
                offset,
                f"✅ System time synchronized (drift: {offset:.2f}s)"
            )
            
    except ImportError:
        return (
            None,
            0,
            "⚠️ ntplib not installed - cannot verify time sync (pip install ntplib)"
        )
    except Exception as e:
        return (
            None,
            0,
            f"⚠️ Could not verify system time: {e}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# JSON FILE BACKUP/RECOVERY (Fixes MEDIUM-2)
# ═══════════════════════════════════════════════════════════════════════════

def safe_read_json(filepath: str, max_retries: int = 3) -> Optional[dict]:
    """
    Safely read JSON file with backup recovery.
    
    Tries:
    1. Primary file (with retries)
    2. Backup file (.backup)
    3. Returns None if both fail
    """
    # Try primary file
    data = _try_read_json(filepath, max_retries)
    if data is not None:
        return data
    
    # Try backup file
    backup_path = filepath + '.backup'
    if os.path.exists(backup_path):
        logger.warning(f"Primary file corrupted, trying backup: {backup_path}")
        data = _try_read_json(backup_path, 1)
        if data is not None:
            # Restore primary from backup
            try:
                shutil.copy(backup_path, filepath)
                logger.info(f"✅ Restored {filepath} from backup")
            except Exception as e:
                logger.error(f"Could not restore from backup: {e}")
            return data
    
    logger.error(f"❌ All attempts failed for {filepath}")
    return None


def _try_read_json(filepath: str, max_retries: int) -> Optional[dict]:
    """Try reading JSON file with retries"""
    for attempt in range(max_retries):
        try:
            if not os.path.exists(filepath):
                return None
            
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error (attempt {attempt+1}): {e}")
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Read error (attempt {attempt+1}): {e}")
            time.sleep(0.5)
    
    return None


def atomic_write_json(filepath: str, data: dict, create_backup: bool = True):
    """
    Write JSON file atomically with backup.
    
    Steps:
    1. Create backup of existing file
    2. Write to temporary file
    3. Atomic rename to target
    """
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    # Create backup of existing file
    if create_backup and os.path.exists(filepath):
        backup_path = filepath + '.backup'
        try:
            shutil.copy(filepath, backup_path)
        except Exception as e:
            logger.warning(f"Could not create backup: {e}")
    
    # Write to temp file
    temp_path = filepath + '.tmp'
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Atomic rename
        if os.name == 'nt':  # Windows
            if os.path.exists(filepath):
                os.remove(filepath)
        os.rename(temp_path, filepath)
        
    except Exception as e:
        logger.error(f"Atomic write failed: {e}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


# ═══════════════════════════════════════════════════════════════════════════
# HEARTBEAT DURING LONG OPERATIONS (Fixes MEDIUM-4)
# ═══════════════════════════════════════════════════════════════════════════

class LongOperationHeartbeat:
    """
    Send heartbeats during long operations.
    
    Usage:
        with LongOperationHeartbeat("Phase 1 Scan", telegram, interval=60):
            # Long operation here
            phase1.run_selection()
    """
    
    def __init__(self, operation_name: str, telegram, interval: int = 60):
        self.operation_name = operation_name
        self.telegram = telegram
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
    
    def start(self):
        """Start heartbeat thread"""
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name=f"Heartbeat-{self.operation_name}"
        )
        self.thread.start()
    
    def stop(self):
        """Stop heartbeat thread"""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
    
    def _heartbeat_loop(self):
        """Background heartbeat loop"""
        start_time = datetime.now()
        
        while not self.stop_event.is_set():
            elapsed = (datetime.now() - start_time).total_seconds()
            
            if self.telegram and elapsed >= self.interval:
                message = (
                    f"💓 Long Operation Heartbeat\n"
                    f"Operation: {self.operation_name}\n"
                    f"Elapsed: {int(elapsed)}s\n"
                    f"Status: In progress..."
                )
                try:
                    self.telegram.send_message(message)
                except Exception as e:
                    logger.error(f"Heartbeat send failed: {e}")
            
            self.stop_event.wait(timeout=min(30, self.interval))


# ═══════════════════════════════════════════════════════════════════════════
# DEPENDENCY VERSION CHECK (Fixes LOW-4)
# ═══════════════════════════════════════════════════════════════════════════

def check_dependency_versions() -> Dict[str, str]:
    """
    Check versions of critical dependencies.
    
    Returns:
        Dict of {package: version}
    """
    versions = {}
    critical_packages = [
        'kiteconnect',
        'pandas',
        'numpy',
        'requests',
        'selenium',
        'transformers',
        'torch'
    ]
    
    for package in critical_packages:
        try:
            import importlib
            mod = importlib.import_module(package)
            version = getattr(mod, '__version__', 'unknown')
            versions[package] = version
        except ImportError:
            versions[package] = 'NOT_INSTALLED'
        except Exception as e:
            versions[package] = f'ERROR: {e}'
    
    return versions


# ═══════════════════════════════════════════════════════════════════════════
# STANDALONE TESTING
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "="*70)
    print("TRADING UTILITIES TEST")
    print("="*70)
    
    # Test time sync
    print("\n1. Testing time synchronization...")
    synced, offset, message = verify_system_time()
    print(f"   {message}")
    
    # Test dependency versions
    print("\n2. Checking dependency versions...")
    versions = check_dependency_versions()
    for pkg, ver in versions.items():
        print(f"   {pkg}: {ver}")
    
    # Test JSON backup/recovery
    print("\n3. Testing JSON backup/recovery...")
    test_data = {'test': 'data', 'timestamp': datetime.now().isoformat()}
    test_file = 'test_utils.json'
    atomic_write_json(test_file, test_data)
    read_data = safe_read_json(test_file)
    print(f"   Write/Read: {'✅ PASS' if read_data == test_data else '❌ FAIL'}")
    
    # Cleanup
    for f in [test_file, test_file + '.backup', test_file + '.tmp']:
        if os.path.exists(f):
            os.remove(f)
    
    print("\n" + "="*70)
    print("✅ All tests complete!")
    print("="*70)
