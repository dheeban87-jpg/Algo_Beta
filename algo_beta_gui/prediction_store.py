"""
Prediction History Store
========================
SQLite-backed storage for Kalman prediction snapshots and actual price outcomes.
Enables deviation analysis for Kalman filter calibration feedback.
"""

import sqlite3
import json
import os
import sys
import datetime
import math

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT    NOT NULL,
    timestamp       TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,
    kalman_scale    TEXT,
    current_price   REAL    NOT NULL,
    velocity        REAL,
    acceleration    REAL,
    atr             REAL,
    prediction_points TEXT  NOT NULL,
    ils_target      REAL,
    tcas_floor      REAL,
    predicted_eta_minutes REAL,
    confidence      REAL,
    trade_type      TEXT,
    created_at      TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS actuals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    timestamp   TEXT    NOT NULL,
    price       REAL    NOT NULL,
    created_at  TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS deviation_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id   INTEGER NOT NULL,
    symbol          TEXT    NOT NULL,
    timeframe       TEXT    NOT NULL,
    avg_error_pct   REAL,
    max_error_pct   REAL,
    direction_correct INTEGER,
    eta_error_minutes REAL,
    target_reached  INTEGER,
    prediction_time TEXT,
    evaluation_time TEXT,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);

CREATE INDEX IF NOT EXISTS idx_pred_symbol_time
    ON predictions(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_pred_symbol_tf
    ON predictions(symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_actual_symbol_time
    ON actuals(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_dev_sym_tf
    ON deviation_analysis(symbol, timeframe);
"""


class PredictionStore:
    """Stores and retrieves prediction history for Kalman calibration."""

    def __init__(self, db_path=None):
        if db_path is None:
            gui_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(gui_dir, "prediction_history.db")

        self._db_path = db_path
        self._conn = None
        self._init_db()

    # ------------------------------------------------------------------
    #  DB lifecycle
    # ------------------------------------------------------------------
    def _init_db(self):
        """Create tables if they don't exist."""
        try:
            self._conn = sqlite3.connect(self._db_path,
                                         check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA_SQL)
        except Exception as e:
            print(f"[PredictionStore] DB init error: {e}", file=sys.stderr)

    def close(self):
        """Close the SQLite connection."""
        try:
            if self._conn:
                self._conn.close()
                self._conn = None
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  Write operations
    # ------------------------------------------------------------------
    def save_prediction(self, symbol, timeframe, current_price,
                        velocity, acceleration, prediction_points,
                        ils_target=None, tcas_floor=None,
                        predicted_eta=None, confidence=None,
                        trade_type=None, kalman_scale=None,
                        entry=None, atr=None):
        """
        Save a prediction snapshot.

        Args:
            prediction_points: list of {"t": float, "p": float} dicts.

        Returns:
            prediction_id (int) or None on error.
        """
        try:
            timestamp = datetime.datetime.now().isoformat()
            points_json = json.dumps(prediction_points)

            cursor = self._conn.execute("""
                INSERT INTO predictions
                (symbol, timestamp, timeframe, kalman_scale,
                 current_price, velocity, acceleration, atr,
                 prediction_points, ils_target, tcas_floor,
                 predicted_eta_minutes, confidence, trade_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, timestamp, timeframe, kalman_scale,
                  current_price, velocity, acceleration, atr,
                  points_json, ils_target, tcas_floor,
                  predicted_eta, confidence, trade_type))
            self._conn.commit()
            return cursor.lastrowid
        except Exception as e:
            print(f"[PredictionStore] save_prediction error: {e}",
                  file=sys.stderr)
            return None

    def save_actual_price(self, symbol, price):
        """Record current actual price for later comparison."""
        try:
            timestamp = datetime.datetime.now().isoformat()
            self._conn.execute("""
                INSERT INTO actuals (symbol, timestamp, price)
                VALUES (?, ?, ?)
            """, (symbol, timestamp, price))
            self._conn.commit()
        except Exception as e:
            print(f"[PredictionStore] save_actual error: {e}",
                  file=sys.stderr)

    # ------------------------------------------------------------------
    #  Read operations
    # ------------------------------------------------------------------
    def get_predictions_for_symbol(self, symbol, timeframe=None, limit=10):
        """
        Get recent predictions for a symbol.

        Returns:
            list of dicts with prediction data (most recent first).
        """
        try:
            query = "SELECT * FROM predictions WHERE symbol = ?"
            params = [symbol]

            if timeframe:
                query += " AND timeframe = ?"
                params.append(timeframe)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            self._conn.row_factory = sqlite3.Row
            rows = self._conn.execute(query, params).fetchall()
            self._conn.row_factory = None

            results = []
            for row in rows:
                d = dict(row)
                try:
                    d['prediction_points'] = json.loads(
                        d['prediction_points'])
                except (json.JSONDecodeError, TypeError):
                    d['prediction_points'] = []
                results.append(d)
            return results
        except Exception as e:
            print(f"[PredictionStore] get_predictions error: {e}",
                  file=sys.stderr)
            return []

    def get_actuals_for_period(self, symbol, start_time, end_time):
        """Get actual prices between two ISO timestamps."""
        try:
            self._conn.row_factory = sqlite3.Row
            rows = self._conn.execute("""
                SELECT timestamp, price FROM actuals
                WHERE symbol = ? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """, (symbol, start_time, end_time)).fetchall()
            self._conn.row_factory = None
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"[PredictionStore] get_actuals error: {e}",
                  file=sys.stderr)
            return []

    # ------------------------------------------------------------------
    #  Deviation analysis
    # ------------------------------------------------------------------
    def calculate_deviation(self, prediction_id):
        """
        Compare a stored prediction with actual prices.

        Returns:
            dict with deviation metrics, or None if not enough data.
        """
        try:
            self._conn.row_factory = sqlite3.Row
            pred_row = self._conn.execute(
                "SELECT * FROM predictions WHERE id = ?",
                (prediction_id,)
            ).fetchone()
            self._conn.row_factory = None

            if not pred_row:
                return None

            pred = dict(pred_row)
            pred_points = json.loads(pred['prediction_points'])
            pred_time = datetime.datetime.fromisoformat(pred['timestamp'])

            # End time = prediction time + max predicted offset
            if not pred_points:
                return None
            max_t = max(p['t'] for p in pred_points)
            end_time = pred_time + datetime.timedelta(minutes=max_t)

            self._conn.row_factory = sqlite3.Row
            actuals = self._conn.execute("""
                SELECT timestamp, price FROM actuals
                WHERE symbol = ? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp
            """, (pred['symbol'],
                  pred_time.isoformat(),
                  end_time.isoformat())).fetchall()
            self._conn.row_factory = None

            if len(actuals) < 3:
                return None  # Not enough actual data

            # Calculate deviation at each predicted point
            errors = []
            for pp in pred_points:
                target_time = pred_time + datetime.timedelta(
                    minutes=pp['t'])

                # Find closest actual price
                closest = min(actuals, key=lambda a: abs(
                    datetime.datetime.fromisoformat(a['timestamp'])
                    - target_time
                ).total_seconds())

                actual_price = closest['price']
                predicted_price = pp['p']
                if actual_price > 0:
                    error_pct = (abs(predicted_price - actual_price)
                                 / actual_price * 100)
                    errors.append(error_pct)

            if not errors:
                return None

            # Direction accuracy
            pred_dir = (1 if pred_points[-1]['p'] > pred_points[0]['p']
                        else -1)
            actual_dir = (1 if actuals[-1]['price'] > actuals[0]['price']
                          else -1)
            direction_correct = 1 if pred_dir == actual_dir else 0

            return {
                'avg_error_pct': sum(errors) / len(errors),
                'max_error_pct': max(errors),
                'direction_correct': direction_correct,
                'prediction_id': prediction_id,
            }
        except Exception as e:
            print(f"[PredictionStore] deviation error: {e}",
                  file=sys.stderr)
            return None

    def get_calibration_summary(self, symbol=None, timeframe=None,
                                last_n=20):
        """
        Aggregate deviation stats for Kalman calibration.

        Returns:
            dict with overall accuracy metrics, or None.
        """
        try:
            predictions = self.get_predictions_for_symbol(
                symbol, timeframe=timeframe, limit=last_n)

            if not predictions:
                return None

            all_errors = []
            direction_hits = 0
            total_evaluated = 0

            for pred in predictions:
                deviation = self.calculate_deviation(pred['id'])
                if deviation:
                    all_errors.append(deviation['avg_error_pct'])
                    direction_hits += deviation['direction_correct']
                    total_evaluated += 1

            if total_evaluated == 0:
                return {
                    'count': 0,
                    'avg_error_pct': 0,
                    'max_error_pct': 0,
                    'direction_accuracy': 0,
                    'suggestion': 'Recording predictions... need more data.',
                }

            dir_acc = (direction_hits / total_evaluated) * 100

            return {
                'count': total_evaluated,
                'avg_error_pct': sum(all_errors) / len(all_errors),
                'max_error_pct': max(all_errors),
                'direction_accuracy': dir_acc,
                'suggestion': _suggest_calibration(
                    sum(all_errors) / len(all_errors), dir_acc),
            }
        except Exception as e:
            print(f"[PredictionStore] summary error: {e}",
                  file=sys.stderr)
            return None

    # ------------------------------------------------------------------
    #  Maintenance
    # ------------------------------------------------------------------
    def prune_old(self, days=7):
        """Delete predictions and actuals older than N days."""
        try:
            cutoff = (datetime.datetime.now()
                      - datetime.timedelta(days=days)).isoformat()
            self._conn.execute(
                "DELETE FROM actuals WHERE timestamp < ?", (cutoff,))
            self._conn.execute(
                "DELETE FROM predictions WHERE timestamp < ?", (cutoff,))
            self._conn.execute(
                "DELETE FROM deviation_analysis WHERE prediction_time < ?",
                (cutoff,))
            self._conn.commit()
        except Exception as e:
            print(f"[PredictionStore] prune error: {e}",
                  file=sys.stderr)


def _suggest_calibration(avg_err, dir_acc):
    """Generate calibration suggestion based on deviation history."""
    suggestions = []

    if avg_err > 2.0:
        suggestions.append(
            f"High avg error ({avg_err:.1f}%) \u2014 "
            "consider reducing prediction horizon")
    elif avg_err > 1.0:
        suggestions.append(
            "Moderate error \u2014 Kalman Q (process noise) may be too low")

    if dir_acc < 60:
        suggestions.append(
            "Direction accuracy <60% \u2014 velocity estimate unreliable")
    elif dir_acc > 85:
        suggestions.append(
            "Direction accuracy >85% \u2014 velocity tracking is strong")

    if avg_err < 0.5 and dir_acc > 80:
        suggestions.append(
            "Excellent prediction quality \u2014 Kalman well-tuned")

    if not suggestions:
        suggestions.append("Moderate accuracy \u2014 monitor for changes")

    return " | ".join(suggestions)
