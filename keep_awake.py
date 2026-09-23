"""
KEEP_AWAKE.PY - Prevent Windows Sleep During Trading
═══════════════════════════════════════════════════════════════════════════════

Prevents Windows from:
├─ Going to sleep
├─ Turning off display (optional)
└─ Entering hibernate mode

Uses Windows SetThreadExecutionState API.

Usage:
    from keep_awake import KeepAwake
    
    # Option 1: Context manager (auto cleanup)
    with KeepAwake():
        # Your trading code here
        orchestrator.run()
    
    # Option 2: Manual start/stop
    awake = KeepAwake()
    awake.start()
    # ... trading ...
    awake.stop()

Author: Dheebanraj
Version: 1.0.0
Date: 2026-01-14
"""

import ctypes
import logging
import threading
import time
import sys

logger = logging.getLogger('KeepAwake')

# Windows API Constants
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040


class KeepAwake:
    """
    Prevent Windows from sleeping during trading hours.
    
    Features:
    ├─ Blocks system sleep
    ├─ Optionally keeps display on
    ├─ Background heartbeat thread (extra safety)
    └─ Proper cleanup on exit
    """
    
    def __init__(self, keep_display_on: bool = False, heartbeat_interval: int = 60):
        """
        Initialize keep-awake system.
        
        Args:
            keep_display_on: If True, also prevents display from turning off
            heartbeat_interval: Seconds between heartbeat pulses (safety refresh)
        """
        self.keep_display_on = keep_display_on
        self.heartbeat_interval = heartbeat_interval
        self._active = False
        self._heartbeat_thread = None
        self._stop_event = threading.Event()
        
        # Check if running on Windows
        self.is_windows = sys.platform == 'win32'
        
        if not self.is_windows:
            logger.warning(f"⚠️ KeepAwake only works on Windows. Current OS: {sys.platform}")
    
    def start(self) -> bool:
        """
        Start preventing sleep.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.is_windows:
            logger.warning("⚠️ KeepAwake not supported on this OS")
            return False
        
        if self._active:
            logger.info("KeepAwake already active")
            return True
        
        try:
            # Build execution state flags
            flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            
            if self.keep_display_on:
                flags |= ES_DISPLAY_REQUIRED
            
            # Call Windows API
            result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
            
            if result == 0:
                logger.error("❌ Failed to set execution state")
                return False
            
            self._active = True
            
            # Start heartbeat thread for extra safety
            self._stop_event.clear()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                daemon=True,
                name="KeepAwake-Heartbeat"
            )
            self._heartbeat_thread.start()
            
            logger.info("=" * 60)
            logger.info("✅ KEEP AWAKE ACTIVATED")
            logger.info("=" * 60)
            logger.info(f"   System sleep: BLOCKED")
            logger.info(f"   Display sleep: {'BLOCKED' if self.keep_display_on else 'ALLOWED'}")
            logger.info(f"   Heartbeat: Every {self.heartbeat_interval}s")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ KeepAwake failed to start: {e}")
            return False
    
    def stop(self) -> bool:
        """
        Stop preventing sleep (restore normal behavior).
        
        Returns:
            True if successful
        """
        if not self.is_windows:
            return False
        
        if not self._active:
            return True
        
        try:
            # Stop heartbeat thread
            self._stop_event.set()
            if self._heartbeat_thread and self._heartbeat_thread.is_alive():
                self._heartbeat_thread.join(timeout=2)
            
            # Reset execution state (allow sleep again)
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            
            self._active = False
            
            logger.info("=" * 60)
            logger.info("✅ KEEP AWAKE DEACTIVATED")
            logger.info("=" * 60)
            logger.info("   System can now sleep normally")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ KeepAwake failed to stop: {e}")
            return False
    
    def _heartbeat_loop(self):
        """Background thread that periodically refreshes the awake state."""
        while not self._stop_event.is_set():
            try:
                if self._active:
                    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                    if self.keep_display_on:
                        flags |= ES_DISPLAY_REQUIRED
                    
                    ctypes.windll.kernel32.SetThreadExecutionState(flags)
                    logger.debug(f"💓 KeepAwake heartbeat")
                
            except Exception as e:
                logger.warning(f"Heartbeat error: {e}")
            
            self._stop_event.wait(timeout=self.heartbeat_interval)
    
    def is_active(self) -> bool:
        """Check if keep-awake is currently active."""
        return self._active
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


# Global convenience functions
_global_instance = None

def prevent_sleep(keep_display_on: bool = False):
    """Global function to prevent sleep."""
    global _global_instance
    if _global_instance is None:
        _global_instance = KeepAwake(keep_display_on=keep_display_on)
    return _global_instance.start()

def allow_sleep():
    """Allow system to sleep again."""
    global _global_instance
    if _global_instance is not None:
        return _global_instance.stop()
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    print("\nKEEP AWAKE TEST - 30 seconds\n")
    
    try:
        with KeepAwake(keep_display_on=True) as awake:
            for i in range(30, 0, -1):
                print(f"\rCountdown: {i}s ", end="", flush=True)
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped")
    
    print("\n✅ Done!")
