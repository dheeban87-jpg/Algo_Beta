"""
MARKER STRATEGY MONITOR
═══════════════════════════════════════════════════════════════════════════════
1-share equity "radar" positions opened by Phase 3 in MARKER mode.

  • No quick exits: TCAS/ILS/trailing/ChatGPT exits do NOT apply.
  • Only automatic exit: disaster stop (MARKER_DISASTER_STOP_PCT below entry).
  • Kalman runs as a SENSOR on 5-min bars. When price has dipped from its
    post-entry peak and the fall slows and turns up, a SECOND-DIP signal is
    sent to Telegram and to Phase 6 (options suggestion, manual entry only).

Signal parameters (MARKER_* in config.py) were tuned by replaying 60 days of
5-min NSE data for the F&O list (see scratch simulation, 2026-09-24).
"""

import logging
from datetime import datetime, timedelta, date
from typing import Dict, Optional

import numpy as np

from kalman_filter import KalmanMAPFilter

logger = logging.getLogger('MarkerMonitor')


class _MarkerTrack:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.kf = KalmanMAPFilter()
        self.kf.set_symbol(symbol)
        self.bucket = None
        self.bar_o = self.bar_h = self.bar_l = self.bar_c = None
        self.bar_start_volume = None
        self.last_day_volume = 0
        self.vol_hist = []
        self.avg_gain = None
        self.avg_loss = None
        self.prev_close = None
        self.rsi_seed = []
        # Post-entry structure (bar based)
        self.bars = []          # list of (time, high, low, close, vel_pct, acc_pct, rsi_mom)
        self.peak = None
        self.peak_idx = 0
        self.warmed = False


class MarkerMonitor:
    def __init__(self, kite, config, telegram=None):
        self.kite = kite
        self.config = config
        self.telegram = telegram
        self.phase6 = None
        self.tracks: Dict[str, _MarkerTrack] = {}
        self._tokens: Optional[Dict[str, int]] = None

        c = config
        self.dip_min = float(getattr(c, 'MARKER_DIP_MIN_PCT', 1.5))
        self.confirm = float(getattr(c, 'MARKER_CONFIRM_BOUNCE_PCT', 0.4))
        self.acc_min = float(getattr(c, 'MARKER_KALMAN_ACCEL_MIN', 0.0))
        self.vel_min = float(getattr(c, 'MARKER_KALMAN_VEL_MIN', 0.0))
        self.fresh = int(getattr(c, 'MARKER_BOTTOM_FRESH_BARS', 12))
        self.use_kalman = bool(getattr(c, 'MARKER_USE_KALMAN', True))
        self.max_hold_days = int(getattr(c, 'MARKER_MAX_HOLD_DAYS', 6))

    # ─────────────────────────────────────────────────────────────────────
    # public
    # ─────────────────────────────────────────────────────────────────────
    def on_price(self, symbol: str, position: Dict, ltp: float,
                 day_volume: float = 0, now: datetime = None) -> Optional[str]:
        """Feed a live price. Returns 'DISASTER_EXIT' when the marker must be closed."""
        now = now or datetime.now()
        track = self.tracks.get(symbol)
        if track is None:
            track = self.tracks[symbol] = _MarkerTrack(symbol)
            self._warmup(track, position, now)

        stop = float(position.get('stop_price', 0) or 0)
        if stop > 0 and ltp <= stop:
            live_gtt = position.get('gtt_protected') and not position.get('is_paper_trade')
            if not live_gtt:
                return 'DISASTER_EXIT'

        self._feed_tick(track, position, ltp, day_volume, now, live=True)
        self._check_max_hold(symbol, position, now)
        return None

    def forget(self, symbol: str):
        self.tracks.pop(symbol, None)

    # ─────────────────────────────────────────────────────────────────────
    # bar building
    # ─────────────────────────────────────────────────────────────────────
    def _feed_tick(self, t: _MarkerTrack, position, ltp, day_volume, now, live):
        bucket = now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)
        if t.bucket is None:
            t.bucket, t.bar_o = bucket, ltp
            t.bar_h = t.bar_l = t.bar_c = ltp
            t.bar_start_volume = day_volume
            return
        if bucket != t.bucket:
            bar_vol = max(0.0, (t.last_day_volume or 0) - (t.bar_start_volume or 0))
            self._close_bar(t, position, t.bucket, t.bar_h, t.bar_l, t.bar_c, bar_vol, live)
            new_day = bucket.date() != t.bucket.date()
            t.bucket, t.bar_o = bucket, ltp
            t.bar_h = t.bar_l = t.bar_c = ltp
            t.bar_start_volume = 0 if new_day else day_volume
        else:
            t.bar_h = max(t.bar_h, ltp)
            t.bar_l = min(t.bar_l, ltp)
            t.bar_c = ltp
        t.last_day_volume = day_volume

    def _rsi(self, t: _MarkerTrack, close: float) -> float:
        if t.prev_close is None:
            t.prev_close = close
            return 50.0
        d = close - t.prev_close
        t.prev_close = close
        gain, loss = max(d, 0.0), max(-d, 0.0)
        if t.avg_gain is None:
            t.rsi_seed.append((gain, loss))
            if len(t.rsi_seed) < 14:
                return 50.0
            t.avg_gain = sum(g for g, _ in t.rsi_seed) / 14
            t.avg_loss = sum(l for _, l in t.rsi_seed) / 14
        else:
            t.avg_gain = (t.avg_gain * 13 + gain) / 14
            t.avg_loss = (t.avg_loss * 13 + loss) / 14
        return 100 - 100 / (1 + t.avg_gain / max(t.avg_loss, 1e-9))

    def _close_bar(self, t: _MarkerTrack, position, bar_time, h, l, c, vol, live):
        rsi = self._rsi(t, c)
        t.vol_hist = (t.vol_hist + [vol])[-20:]
        avg_v = sum(t.vol_hist) / len(t.vol_hist)
        vol_mom = float(np.clip(vol / max(avg_v, 1) - 1, -1, 3))

        if not t.kf.initialized:
            t.kf.initialize(c, rsi, vol_mom)
        else:
            t.kf.predict()
            t.kf.update(c, rsi, vol_mom)
        vel_pct = float(t.kf.x[1, 0]) / c * 100
        acc_pct = float(t.kf.x[2, 0]) / c * 100
        rsi_mom = float(t.kf.x[4, 0])

        entry_time = self._entry_time(position)
        if entry_time and bar_time < entry_time:
            return

        t.bars.append((bar_time, h, l, c, vel_pct, acc_pct, rsi_mom))
        idx = len(t.bars) - 1
        if t.peak is None or c > t.peak:
            t.peak, t.peak_idx = c, idx
        position['marker_peak_price'] = round(t.peak, 2)

        if position.get('second_dip_signaled'):
            return
        sig = self._evaluate(t, position)
        if sig and live:
            self._fire(t.symbol, position, sig)
        elif sig:
            position['second_dip_signaled'] = True
            logger.info(f"📍 {t.symbol}: 2nd-dip already occurred at {sig['time']} (warm-up replay) — not re-sent")

    # ─────────────────────────────────────────────────────────────────────
    # 2nd-dip detection
    # ─────────────────────────────────────────────────────────────────────
    def _evaluate(self, t: _MarkerTrack, position) -> Optional[Dict]:
        bars = t.bars
        j = len(bars) - 1
        if j <= t.peak_idx:
            return None
        lows = [b[2] for b in bars[t.peak_idx:j + 1]]
        lo_rel = int(np.argmin(lows))
        lo_i = t.peak_idx + lo_rel
        lo = lows[lo_rel]
        dip = (t.peak - lo) / t.peak * 100
        _, _, _, c, vel_pct, acc_pct, rsi_mom = bars[j]

        if dip < self.dip_min or j - lo_i > self.fresh:
            return None
        if c < lo * (1 + self.confirm / 100):
            return None
        if self.use_kalman:
            recent = [b[4] for b in bars[max(lo_i - 6, 0):lo_i + 1]]
            was_falling = min(recent) < 0 if recent else False
            if not (was_falling and acc_pct >= self.acc_min and vel_pct >= self.vel_min and rsi_mom > 0):
                return None

        entry = float(position.get('entry_price', 0) or 0)
        return {
            'symbol': t.symbol,
            'time': bars[j][0],
            'price': round(c, 2),
            'entry_price': entry,
            'peak_price': round(t.peak, 2),
            'dip_low': round(lo, 2),
            'dip_pct': round(dip, 2),
            'bounce_pct': round((c / lo - 1) * 100, 2),
            'kalman_velocity_pct': round(vel_pct, 4),
            'kalman_accel_pct': round(acc_pct, 5),
            'rsi_momentum': round(rsi_mom, 3),
            'structural_stop': round(lo * 0.997, 2),
        }

    def _fire(self, symbol: str, position: Dict, sig: Dict):
        position['second_dip_signaled'] = True
        position['second_dip_signal'] = {k: (v.isoformat() if isinstance(v, datetime) else v)
                                         for k, v in sig.items()}
        logger.info(f"📍🎯 MARKER 2ND-DIP: {symbol} @ ₹{sig['price']:.2f} "
                    f"(dip {sig['dip_pct']:.2f}% from ₹{sig['peak_price']:.2f}, bounce {sig['bounce_pct']:.2f}%)")
        if self.telegram:
            try:
                self.telegram.send_message(
                    f"📍🎯 2ND-DIP SIGNAL — {symbol}\n"
                    f"{'=' * 30}\n"
                    f"Price: ₹{sig['price']:.2f} | Marker entry: ₹{sig['entry_price']:.2f}\n"
                    f"Peak ₹{sig['peak_price']:.2f} → Low ₹{sig['dip_low']:.2f} (−{sig['dip_pct']:.2f}%)\n"
                    f"Bounce off low: +{sig['bounce_pct']:.2f}% | Kalman turning up\n"
                    f"Structure stop (dip low): ₹{sig['structural_stop']:.2f}\n\n"
                    f"Options suggestion follows from Phase 6.\n"
                    f"⚠️ SUGGESTION ONLY — enter manually"
                )
            except Exception as e:
                logger.warning(f"Marker Telegram failed: {e}")
        if self.phase6 and hasattr(self.phase6, 'on_marker_second_dip'):
            try:
                self.phase6.on_marker_second_dip(sig)
            except Exception as e:
                logger.error(f"Phase 6 marker handoff failed for {symbol}: {e}")

    # ─────────────────────────────────────────────────────────────────────
    # helpers
    # ─────────────────────────────────────────────────────────────────────
    def _entry_time(self, position) -> Optional[datetime]:
        et = position.get('entry_time')
        if isinstance(et, datetime):
            return et.replace(tzinfo=None)
        try:
            return datetime.fromisoformat(str(et)).replace(tzinfo=None)
        except (TypeError, ValueError):
            return None

    def _check_max_hold(self, symbol, position, now):
        et = self._entry_time(position)
        if not et or position.get('marker_hold_expired_notified'):
            return
        held = int(np.busday_count(et.date(), now.date()))
        if held >= self.max_hold_days:
            position['marker_hold_expired_notified'] = True
            msg = (f"📍⌛ MARKER WINDOW OVER — {symbol}\n"
                   f"Held {held} trading days. No automatic exit.\n"
                   f"Review manually: keep or close the 1-share marker.")
            logger.info(msg.replace('\n', ' | '))
            if self.telegram:
                try:
                    self.telegram.send_message(msg)
                except Exception:
                    pass

    def _token(self, symbol) -> Optional[int]:
        if self._tokens is None:
            try:
                self._tokens = {i['tradingsymbol']: i['instrument_token'] for i in self.kite.instruments('NSE')}
            except Exception as e:
                logger.warning(f"Marker: instrument list unavailable ({e})")
                self._tokens = {}
        return self._tokens.get(symbol)

    def _warmup(self, t: _MarkerTrack, position, now):
        """Replay recent 5-min history so Kalman/RSI/peak are ready on the first live bar."""
        token = self._token(t.symbol)
        if not token:
            return
        try:
            candles = self.kite.historical_data(token, now - timedelta(days=10), now, '5minute')
        except Exception as e:
            logger.warning(f"Marker warm-up failed for {t.symbol}: {e}")
            return
        cur_bucket = now.replace(minute=now.minute - now.minute % 5, second=0, microsecond=0)
        for cd in candles:
            bt = cd['date'].replace(tzinfo=None) if isinstance(cd['date'], datetime) else cd['date']
            if bt >= cur_bucket:
                break
            self._close_bar(t, position, bt, cd['high'], cd['low'], cd['close'], cd.get('volume', 0), live=False)
        t.warmed = True
        logger.info(f"📍 Marker warm-up {t.symbol}: {len(candles)} bars | peak ₹{(t.peak or 0):.2f} "
                    f"| 2nd-dip signaled={position.get('second_dip_signaled', False)}")
