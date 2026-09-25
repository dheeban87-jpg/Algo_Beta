"""Paper-mode guard between an executor and KiteConnect.

Read-only calls (quote, margins, holdings, ...) pass through to the real client. Every
order-writing call is answered locally with a simulated result, so nothing can reach the
broker while MASTER_PAPER_MODE is on, whichever code path the executor takes.
"""

import logging
import threading
import uuid

logger = logging.getLogger("PaperKiteProxy")

_ORDER_WRITE = {"cancel_order", "modify_order", "exit_order", "convert_position"}
_GTT_WRITE = {"place_gtt", "modify_gtt", "delete_gtt"}


class PaperKiteProxy:
    def __init__(self, kite, tag="PH3"):
        object.__setattr__(self, "_kite", kite)
        object.__setattr__(self, "_tag", tag)
        object.__setattr__(self, "_orders", {})
        object.__setattr__(self, "_lock", threading.Lock())

    def _last_price(self, exchange, symbol, fallback=0.0):
        try:
            q = self._kite.quote([f"{exchange}:{symbol}"])
            return float(q.get(f"{exchange}:{symbol}", {}).get("last_price", fallback) or fallback)
        except Exception:
            return fallback

    def _place_order(self, *args, **kwargs):
        symbol = kwargs.get("tradingsymbol", "")
        exchange = kwargs.get("exchange", "NSE")
        qty = int(kwargs.get("quantity", 0) or 0)
        limit_price = float(kwargs.get("price") or 0)
        price = limit_price if limit_price > 0 else self._last_price(exchange, symbol)
        oid = f"{self._tag}_PAPER_{uuid.uuid4().hex[:8].upper()}"
        with self._lock:
            self._orders[oid] = {"symbol": symbol, "quantity": qty, "price": price,
                                 "side": kwargs.get("transaction_type", "")}
        logger.info(f"📝 PAPER ORDER (blocked from broker): {kwargs.get('transaction_type')} "
                    f"{qty} {symbol} @ ₹{price:.2f} id={oid}")
        return oid

    def _order_history(self, order_id, *args, **kwargs):
        rec = self._orders.get(order_id)
        if rec is None:
            return self._kite.order_history(order_id)
        return [{"order_id": order_id, "status": "COMPLETE", "quantity": rec["quantity"],
                 "filled_quantity": rec["quantity"], "pending_quantity": 0,
                 "average_price": rec["price"], "tradingsymbol": rec["symbol"]}]

    def _noop_order(self, *args, **kwargs):
        oid = kwargs.get("order_id") or (args[1] if len(args) > 1 else "")
        logger.info(f"📝 PAPER: order write ignored ({oid})")
        return oid

    def _gtt(self, *args, **kwargs):
        logger.info("📝 PAPER: GTT write ignored")
        return {"trigger_id": f"PAPER_GTT_{uuid.uuid4().hex[:6].upper()}"}

    def __getattr__(self, name):
        if name == "place_order":
            return self._place_order
        if name == "order_history":
            return self._order_history
        if name in _ORDER_WRITE:
            return self._noop_order
        if name in _GTT_WRITE:
            return self._gtt
        return getattr(self._kite, name)
