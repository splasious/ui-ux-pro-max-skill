"""Broker safeguards, execution modes, candle building and notifications."""
import unittest
from datetime import datetime

from swing_master.data.websocket import CandleBuilder
from swing_master.execution import (BrokerError, NetworkError, OrderManager, OrderRequest, PaperBroker,
                                    SafeBrokerGateway)
from swing_master.notifications import NotificationBus


class FlakyBroker(PaperBroker):
    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    def place_order(self, req):
        if self.failures:
            self.failures -= 1
            raise NetworkError("timeout")
        return super().place_order(req)


class ExecutionTests(unittest.TestCase):
    def gw(self, broker=None, **kw):
        return SafeBrokerGateway(broker or PaperBroker(), max_daily_loss=20_000, max_open_risk=50_000,
                                 sleep=lambda s: None, **kw)

    def test_duplicate_orders_prevented(self):
        g = self.gw()
        a = g.submit(OrderRequest("RELIANCE", "BUY", 10, client_id="sig-1"))
        b = g.submit(OrderRequest("RELIANCE", "BUY", 10, client_id="sig-1"))
        self.assertEqual(a.order_id, b.order_id)
        self.assertEqual(len(g.broker.orders()), 1)

    def test_kill_switch_and_limits(self):
        g = self.gw()
        g.kill_switch = True
        with self.assertRaises(BrokerError):
            g.submit(OrderRequest("TCS", "BUY", 1))
        g.kill_switch = False
        g.day_pnl = -25_000
        with self.assertRaises(BrokerError):
            g.submit(OrderRequest("TCS", "BUY", 1))
        g.day_pnl = 0
        with self.assertRaises(BrokerError):
            g.submit(OrderRequest("TCS", "BUY", 1), added_risk=60_000)

    def test_retry_on_network_errors_only(self):
        g = self.gw(FlakyBroker(2))
        rec = g.submit(OrderRequest("INFY", "BUY", 5))
        self.assertTrue(rec.order_id.startswith("PAPER"))
        g2 = self.gw(FlakyBroker(5), max_retries=3)
        with self.assertRaises(NetworkError):
            g2.submit(OrderRequest("INFY", "BUY", 5))

    def test_rate_limit(self):
        g = self.gw(rate_per_sec=0.0, burst=2)
        g.submit(OrderRequest("A", "BUY", 1))
        g.submit(OrderRequest("B", "BUY", 1))
        with self.assertRaises(BrokerError):
            g.submit(OrderRequest("C", "BUY", 1))

    def test_reconciliation_detects_status_changes(self):
        g = self.gw()
        rec = g.submit(OrderRequest("A", "BUY", 1))
        g.broker.fill(rec.order_id, 100.0, 1)
        issues = g.reconcile()
        self.assertEqual(issues, [])  # paper broker mutates the same record; nothing missing

    def test_auto_mode_requires_live_flag_and_validation(self):
        with self.assertRaises(BrokerError):
            OrderManager("AUTO", self.gw())
        with self.assertRaises(BrokerError):
            OrderManager("AUTO", self.gw(), live_enabled=True, validated=False)
        OrderManager("AUTO", self.gw(), live_enabled=True, validated=True)

    def test_manual_mode_sends_nothing(self):
        g = self.gw()
        om = OrderManager("MANUAL", g)
        om("PLACE", {"eval_id": "e1", "symbol": "A", "direction": "LONG", "qty": 5})
        self.assertEqual(len(g.broker.orders()), 0)
        self.assertEqual(om.proposals["P00001"]["status"], "PROPOSED")

    def test_semi_auto_requires_confirmation(self):
        g = self.gw()
        om = OrderManager("SEMI_AUTO", g)
        om("PLACE", {"eval_id": "e1", "symbol": "A", "direction": "LONG", "qty": 5})
        self.assertEqual(len(g.broker.orders()), 0)
        om.confirm("P00001")
        self.assertEqual(len(g.broker.orders()), 1)

    def test_candle_builder_emits_only_complete_bars(self):
        cb = CandleBuilder("5m")
        d = datetime(2024, 1, 2)
        self.assertIsNone(cb.on_tick("X", d.replace(hour=9, minute=15, second=5), 100.0, 1))
        self.assertIsNone(cb.on_tick("X", d.replace(hour=9, minute=17), 101.0, 1))
        done = cb.on_tick("X", d.replace(hour=9, minute=20, second=1), 99.0, 1)
        self.assertIsNotNone(done)
        self.assertEqual((done.open, done.high, done.low, done.close), (100.0, 101.0, 100.0, 101.0))
        self.assertEqual(cb.on_clock(d.replace(hour=9, minute=24)), [])
        self.assertEqual(len(cb.on_clock(d.replace(hour=9, minute=25))), 1)
        self.assertIsNone(cb.on_tick("X", d.replace(hour=16), 99.0, 1))  # outside session ignored

    def test_notification_channel_failure_is_isolated(self):
        bus = NotificationBus()
        got = []

        def broken(kind, payload):
            raise RuntimeError("telegram down")

        bus.subscribe(broken)
        bus.subscribe(lambda k, p: got.append(k))
        bus.publish("T1_HIT", {"symbol": "A"})
        self.assertEqual(got, ["T1_HIT"])
        self.assertEqual(len(bus.errors), 1)


if __name__ == "__main__":
    unittest.main()
