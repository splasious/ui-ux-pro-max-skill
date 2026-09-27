"""Broker abstraction and safety gateway (Sections 48 & 49).

Strategy code never talks to a broker directly.  Orders flow

    OrderManager -> SafeBrokerGateway (safeguards) -> BrokerInterface implementation

Credentials are read from environment variables at connection time and are
never stored in source control or in config files.
"""
from __future__ import annotations

import hashlib
import os
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional


class BrokerError(Exception):
    pass


class NetworkError(BrokerError):
    """Transient failure -- safe to retry."""


class BrokerNotConfigured(BrokerError):
    pass


@dataclass
class OrderRequest:
    symbol: str
    side: str  # BUY | SELL
    quantity: int
    order_type: str = "MARKET"  # MARKET | LIMIT | SL | SL-M
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    product: str = "CNC"
    tag: str = ""
    client_id: str = ""  # idempotency key

    def key(self) -> str:
        if self.client_id:
            return self.client_id
        raw = f"{self.symbol}|{self.side}|{self.quantity}|{self.order_type}|{self.price}|{self.trigger_price}|{self.tag}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass
class OrderRecord:
    order_id: str
    request: OrderRequest
    status: str  # OPEN | COMPLETE | CANCELLED | REJECTED
    filled_qty: int = 0
    average_price: Optional[float] = None
    message: str = ""
    history: List[Dict] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


class BrokerInterface(ABC):
    name = "abstract"

    @abstractmethod
    def place_order(self, req: OrderRequest) -> OrderRecord: ...

    @abstractmethod
    def modify_order(self, order_id: str, **changes) -> OrderRecord: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> OrderRecord: ...

    @abstractmethod
    def orders(self) -> List[OrderRecord]: ...

    @abstractmethod
    def positions(self) -> List[Dict]: ...

    @abstractmethod
    def status(self) -> Dict: ...


class TokenBucket:
    def __init__(self, rate_per_sec: float, burst: int, clock: Callable[[], float] = time.monotonic):
        self.rate, self.capacity, self.clock = rate_per_sec, burst, clock
        self.tokens = float(burst)
        self.last = clock()

    def take(self) -> bool:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class SafeBrokerGateway:
    """Safeguards every order: kill switch, loss/risk limits, duplicates, rate limit, retries."""

    def __init__(self, broker: BrokerInterface, max_daily_loss: float, max_open_risk: float,
                 rate_per_sec: float = 3.0, burst: int = 5, max_retries: int = 3,
                 sleep: Callable[[float], None] = time.sleep):
        self.broker = broker
        self.max_daily_loss = max_daily_loss
        self.max_open_risk = max_open_risk
        self.kill_switch = False
        self.day_pnl = 0.0
        self.open_risk = 0.0
        self._sent: Dict[str, OrderRecord] = {}
        self.bucket = TokenBucket(rate_per_sec, burst)
        self.max_retries = max_retries
        self.sleep = sleep
        self.audit: List[Dict] = []

    def _log(self, event: str, **kw):
        self.audit.append({"ts": time.time(), "event": event, **kw})

    def submit(self, req: OrderRequest, added_risk: float = 0.0) -> OrderRecord:
        key = req.key()
        if self.kill_switch:
            self._log("blocked", reason="kill switch", key=key)
            raise BrokerError("Kill switch engaged -- no new orders")
        if self.day_pnl <= -abs(self.max_daily_loss):
            self._log("blocked", reason="daily loss", key=key)
            raise BrokerError("Maximum daily loss reached")
        if self.open_risk + added_risk > self.max_open_risk:
            self._log("blocked", reason="open risk", key=key)
            raise BrokerError("Maximum open risk would be exceeded")
        if key in self._sent:
            self._log("duplicate", key=key)
            return self._sent[key]
        if not self.bucket.take():
            self._log("rate_limited", key=key)
            raise BrokerError("Rate limit: retry later")
        delay = 0.5
        for attempt in range(1, self.max_retries + 1):
            try:
                rec = self.broker.place_order(req)
                self._sent[key] = rec
                self.open_risk += added_risk
                self._log("placed", key=key, order_id=rec.order_id, attempt=attempt)
                return rec
            except NetworkError as exc:
                self._log("network_error", key=key, attempt=attempt, error=str(exc))
                if attempt == self.max_retries:
                    raise
                self.sleep(delay)
                delay *= 2
        raise BrokerError("unreachable")

    def reconcile(self) -> List[Dict]:
        """Compare locally-sent orders with the broker's order book."""
        remote = {o.order_id: o for o in self.broker.orders()}
        issues = []
        for key, rec in self._sent.items():
            r = remote.get(rec.order_id)
            if r is None:
                issues.append({"key": key, "order_id": rec.order_id, "issue": "missing at broker"})
            elif r.status != rec.status:
                issues.append({"key": key, "order_id": rec.order_id, "issue": f"status {rec.status} -> {r.status}"})
                self._sent[key] = r
        self._log("reconciled", issues=len(issues))
        return issues


class ZerodhaKiteBroker(BrokerInterface):
    """Adapter for Zerodha Kite Connect.  REQUIRES LIVE CREDENTIALS + the ``kiteconnect`` package.

    Reads ``KITE_API_KEY`` / ``KITE_ACCESS_TOKEN`` from the environment.  It is
    never constructed automatically; live execution also requires
    ``SM_LIVE_TRADING_ENABLED=1`` and a validated research record.
    """
    name = "zerodha-kite"

    def __init__(self, api_key_env: str = "KITE_API_KEY", token_env: str = "KITE_ACCESS_TOKEN"):
        api_key, token = os.environ.get(api_key_env), os.environ.get(token_env)
        if not api_key or not token:
            raise BrokerNotConfigured(f"Set {api_key_env} and {token_env} in the environment")
        try:
            from kiteconnect import KiteConnect  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise BrokerNotConfigured("pip install kiteconnect to enable the Kite adapter") from exc
        self.kite = KiteConnect(api_key=api_key)
        self.kite.set_access_token(token)

    def place_order(self, req: OrderRequest) -> OrderRecord:  # pragma: no cover - needs live broker
        try:
            oid = self.kite.place_order(variety="regular", exchange="NSE", tradingsymbol=req.symbol,
                                        transaction_type=req.side, quantity=req.quantity, product=req.product,
                                        order_type=req.order_type, price=req.price, trigger_price=req.trigger_price,
                                        tag=(req.tag or "")[:20])
        except Exception as exc:
            if "timed out" in str(exc).lower() or "connection" in str(exc).lower():
                raise NetworkError(str(exc)) from exc
            raise BrokerError(str(exc)) from exc
        return OrderRecord(str(oid), req, "OPEN")

    def modify_order(self, order_id: str, **changes) -> OrderRecord:  # pragma: no cover
        self.kite.modify_order(variety="regular", order_id=order_id, **changes)
        return OrderRecord(order_id, OrderRequest("", "", 0), "OPEN", message="modified")

    def cancel_order(self, order_id: str) -> OrderRecord:  # pragma: no cover
        self.kite.cancel_order(variety="regular", order_id=order_id)
        return OrderRecord(order_id, OrderRequest("", "", 0), "CANCELLED")

    def orders(self) -> List[OrderRecord]:  # pragma: no cover
        out = []
        for o in self.kite.orders():
            req = OrderRequest(o["tradingsymbol"], o["transaction_type"], int(o["quantity"]), o["order_type"])
            out.append(OrderRecord(str(o["order_id"]), req, o["status"], int(o.get("filled_quantity") or 0),
                                   o.get("average_price")))
        return out

    def positions(self) -> List[Dict]:  # pragma: no cover
        return self.kite.positions().get("net", [])

    def status(self) -> Dict:  # pragma: no cover
        return {"broker": self.name, "connected": True}
