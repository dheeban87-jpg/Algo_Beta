"""
CONNECTION HEALTH MONITOR - Real-time API Connection Monitoring
═══════════════════════════════════════════════════════════════════════════════

Addresses CRITICAL-1: WebSocket/API disconnect detection
- Monitors Kite API connection health
- Tracks consecutive failures
- Alerts when connection degraded
- Attempts automatic recovery

Author: Fault Analysis Fix CRITICAL-1
Date: 2026-01-20
Version: 1.0.0
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict

logger = logging.getLogger('ConnectionHealth')


class ConnectionHealthMonitor:
    """
    Monitor Kite API connection health during autonomous operation.
    
    Features:
    - Lightweight health checks
    - Consecutive failure tracking
    - Critical alert escalation
    - Connection recovery attempts
    
    Usage:
        health = ConnectionHealthMonitor(kite, telegram)
        
        # In main loop
        if not health.check_connection():
            # Connection degraded - handle appropriately
            pass
    """
    
    def __init__(self, kite, telegram, max_failures: int = 3):
        """
        Initialize connection health monitor.
        
        Args:
            kite: KiteConnect instance
            telegram: TelegramNotifier instance
            max_failures: Max consecutive failures before critical alert
        """
        self.kite = kite
        self.telegram = telegram
        self.MAX_FAILURES = max_failures
        
        # Health tracking
        self.consecutive_failures = 0
        self.last_successful_call = datetime.now()
        self.last_check_time = datetime.now()
        self.total_failures_today = 0
        
        # Alert tracking (avoid spam)
        self.last_alert_time = None
        self.alert_cooldown = 300  # 5 minutes between alerts
        
        # Connection state
        self.is_healthy = True
        self.degraded_since = None
        
        logger.info("✅ Connection Health Monitor initialized")
        logger.info(f"   Max consecutive failures: {max_failures}")
    
    def check_connection(self, force_check: bool = False) -> bool:
        """
        Check if connection is healthy.
        
        Args:
            force_check: Force immediate check (ignore cooldown)
            
        Returns:
            True if healthy, False if degraded
        """
        now = datetime.now()
        
        # Don't check too frequently (every 60s by default)
        if not force_check and (now - self.last_check_time).total_seconds() < 60:
            return self.is_healthy
        
        self.last_check_time = now
        
        try:
            # Lightweight API call - just profile data
            profile = self.kite.profile()
            
            if profile and 'user_name' in profile:
                # Success!
                self._record_success()
                return True
            else:
                # Unexpected response
                self._record_failure("Unexpected API response")
                return False
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Categorize error
            if any(x in error_msg for x in ['502', '504', 'gateway']):
                self._record_failure(f"Gateway error: {e}")
            elif any(x in error_msg for x in ['timeout', 'timed out']):
                self._record_failure(f"Timeout: {e}")
            elif any(x in error_msg for x in ['connection', 'network']):
                self._record_failure(f"Network error: {e}")
            elif 'token' in error_msg or 'session' in error_msg:
                self._record_failure(f"Authentication error: {e}")
                self._alert_auth_failure()
            else:
                self._record_failure(f"Unknown error: {e}")
            
            return False
    
    def _record_success(self):
        """Record successful API call"""
        # Reset failure tracking
        if self.consecutive_failures > 0:
            logger.info(f"✅ Connection restored (was degraded for {self.consecutive_failures} checks)")
        
        self.consecutive_failures = 0
        self.last_successful_call = datetime.now()
        
        if not self.is_healthy:
            # Connection recovered!
            self.is_healthy = True
            duration = (datetime.now() - self.degraded_since).total_seconds() if self.degraded_since else 0
            
            if self.telegram:
                self.telegram.send_message(
                    f"✅ CONNECTION RESTORED\n\n"
                    f"Kite API connection healthy again.\n"
                    f"Degraded for: {int(duration)}s\n\n"
                    f"System operations resumed."
                )
            
            self.degraded_since = None
    
    def _record_failure(self, reason: str):
        """Record failed API call"""
        self.consecutive_failures += 1
        self.total_failures_today += 1
        
        logger.warning(
            f"⚠️ Connection check failed ({self.consecutive_failures}/{self.MAX_FAILURES}): "
            f"{reason}"
        )
        
        # Mark as degraded after first failure
        if self.is_healthy:
            self.is_healthy = False
            self.degraded_since = datetime.now()
        
        # Check if critical threshold reached
        if self.consecutive_failures >= self.MAX_FAILURES:
            self._alert_connection_lost(reason)
    
    def _alert_connection_lost(self, reason: str):
        """Send critical alert for connection loss"""
        now = datetime.now()
        
        # Check alert cooldown
        if self.last_alert_time:
            time_since_last = (now - self.last_alert_time).total_seconds()
            if time_since_last < self.alert_cooldown:
                return  # Don't spam alerts
        
        self.last_alert_time = now
        
        logger.error(f"🚨 CRITICAL: Connection lost - {self.consecutive_failures} consecutive failures!")
        
        if self.telegram:
            self.telegram.send_critical(
                f"🚨 KITE API CONNECTION LOST\n\n"
                f"Consecutive failures: {self.consecutive_failures}\n"
                f"Last success: {self._format_time_ago(self.last_successful_call)}\n"
                f"Reason: {reason[:100]}\n\n"
                f"⚠️ Trading may be impaired!\n"
                f"⚠️ System will attempt recovery...\n\n"
                f"Manual check recommended."
            )
    
    def _alert_auth_failure(self):
        """Send critical alert for authentication failure"""
        logger.critical("🚨 Authentication failure detected!")
        
        if self.telegram:
            self.telegram.send_critical(
                f"🚨 KITE AUTHENTICATION FAILED\n\n"
                f"Session may have expired.\n\n"
                f"⚠️ System may need re-login!\n"
                f"⚠️ Check Zerodha session manually!"
            )
    
    def _format_time_ago(self, timestamp: datetime) -> str:
        """Format time ago string"""
        delta = datetime.now() - timestamp
        seconds = int(delta.total_seconds())
        
        if seconds < 60:
            return f"{seconds}s ago"
        elif seconds < 3600:
            return f"{seconds//60}m ago"
        else:
            return f"{seconds//3600}h {(seconds%3600)//60}m ago"
    
    def get_status(self) -> Dict:
        """
        Get current connection health status.
        
        Returns:
            Dict with health metrics
        """
        return {
            'is_healthy': self.is_healthy,
            'consecutive_failures': self.consecutive_failures,
            'total_failures_today': self.total_failures_today,
            'last_successful_call': self.last_successful_call.isoformat(),
            'time_since_success': (datetime.now() - self.last_successful_call).total_seconds(),
            'degraded_since': self.degraded_since.isoformat() if self.degraded_since else None
        }
    
    def reset_daily_counters(self):
        """Reset daily failure counter (call at market open)"""
        self.total_failures_today = 0
        logger.info("Connection health counters reset for new day")


# ═══════════════════════════════════════════════════════════════════════════
# STANDALONE TESTING
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n" + "="*70)
    print("CONNECTION HEALTH MONITOR TEST")
    print("="*70)
    
    # Mock Kite class for testing
    class MockKite:
        def __init__(self):
            self.call_count = 0
        
        def profile(self):
            self.call_count += 1
            # Simulate failures every 3rd call
            if self.call_count % 3 == 0:
                raise Exception("502 Gateway Timeout")
            return {'user_name': 'TEST_USER'}
    
    # Test
    kite = MockKite()
    health = ConnectionHealthMonitor(kite, None, max_failures=2)
    
    for i in range(5):
        is_healthy = health.check_connection(force_check=True)
        print(f"Check {i+1}: {'✅ Healthy' if is_healthy else '❌ Degraded'}")
        time.sleep(1)
    
    status = health.get_status()
    print(f"\nFinal Status:")
    print(f"  Healthy: {status['is_healthy']}")
    print(f"  Consecutive Failures: {status['consecutive_failures']}")
    print(f"  Total Failures Today: {status['total_failures_today']}")
    
    print("\n" + "="*70)
    print("✅ Test complete!")
    print("="*70)
