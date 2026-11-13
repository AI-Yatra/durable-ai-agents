"""temporal_agent.py against a running Temporal dev server (skipped if none on 127.0.0.1:7233).

Worker 1 SIGKILLs itself right after the charge. Worker 2 starts afterwards, picks the run up,
re-runs the charge with the same key (the bank says "not charged again") and finishes. Nobody restarts worker 1.
"""

import os
import socket
import subprocess
import sys
import time
import uuid

import pytest

from conftest import ROOT


def temporal_up():
    try:
        socket.create_connection(("127.0.0.1", 7233), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not temporal_up(), reason="no Temporal dev server on 127.0.0.1:7233")
def test_worker_killed_after_charge_other_worker_finishes_paying_once(shop, tmp_path):
    queue = f"chai-test-{uuid.uuid4().hex[:6]}"
    env = {**os.environ, "SHOP_URL": shop.url, "MOCK_LLM": "1", "TASK_QUEUE": queue, "DEMO_PAUSE": "0"}
    env.pop("CRASH_AT", None)
    py = [sys.executable, "temporal_agent.py"]

    starter = subprocess.Popen(py + ["start", f"order-{queue}"], cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    w1 = subprocess.run(py + ["worker"], cwd=ROOT, env={**env, "CRASH_AT": "after_pay", "WORKER_NAME": "worker-1"}, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert w1.returncode == (9 if os.name == "nt" else -9), w1.stdout + w1.stderr
    assert shop("/stats")["payments"] == 1

    w2 = subprocess.Popen(py + ["worker"], cwd=ROOT, env={**env, "WORKER_NAME": "worker-2"}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    try:
        out, _ = starter.communicate(timeout=60)
    finally:
        w2.terminate()
        w2_out, _ = w2.communicate(timeout=10)
    assert starter.returncode == 0, out
    assert "not charged again" in w2_out, w2_out
    assert "LLM call" not in w2_out  # read_order came back from Temporal's history
    s = shop("/stats")
    assert (s["payments"], s["sms"], s["kitchen"]) == (1, 1, 1)


# --- the same waits as durable_agent.py: the bank, the customer, an admin -------------
@pytest.fixture
def order(shop):
    """One worker on its own task queue, plus `order(...)` to run temporal_agent.py commands for one order."""
    queue = f"chai-test-{uuid.uuid4().hex[:6]}"
    order_id = f"order-{queue}"
    env = {**os.environ, "SHOP_URL": shop.url, "MOCK_LLM": "1", "TASK_QUEUE": queue, "DEMO_PAUSE": "0", "ORDER_ID": order_id}
    env.pop("CRASH_AT", None)
    py = [sys.executable, "temporal_agent.py"]
    w = subprocess.Popen(py + ["worker", "worker-1"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def call(*args, **more):
        e = {**env, **{k: str(v) for k, v in more.items()}}
        p = subprocess.run(py + list(args), cwd=ROOT, env=e, capture_output=True, text=True, encoding="utf-8", timeout=60)
        return p.returncode, p.stdout + p.stderr

    yield call
    w.kill()
    w.wait(timeout=10)


needs_temporal = pytest.mark.skipif(not temporal_up(), reason="no Temporal dev server on 127.0.0.1:7233")


@needs_temporal
def test_temporal_pending_waits_then_bank_success(shop, order):
    shop("/mode", {"pending": True})
    rc, out = order("start")
    assert rc == 0 and "waiting for the bank" in out, out
    assert shop("/stats")["payments"] == 1
    rc, out = order("bank", "success")
    assert rc == 0 and "done" in out, out
    s = shop("/stats")
    assert (s["payments"], s["kitchen"], s["refunds"]) == (1, 1, 0)


@needs_temporal
def test_temporal_bank_reversed_tells_customer(shop, order):
    shop("/mode", {"pending": True})
    order("start")
    rc, out = order("bank", "reversed")
    assert "payment reversed" in out, out
    s = shop("/stats")
    assert (s["kitchen"], s["refunds"], s["sms"]) == (0, 0, 1)


@needs_temporal
def test_temporal_sold_out_no_reply_refunds_once(shop, order):
    shop("/mode", {"pending": True})
    order("start")
    order("stock", "0")  # chai runs out while we wait
    rc, out = order("bank", "success")
    assert "waiting for the customer" in out, out
    rc, out = order("customer", "no-reply")
    assert rc == 0 and "done" in out, out
    rc, out = order("customer", "refund")  # late answer: nothing waiting
    assert "nobody is waiting" in out, out
    s = shop("/stats")
    assert (s["payments"], s["refunds"], s["kitchen"]) == (1, 1, 0)


@needs_temporal
def test_temporal_customer_never_replies_refunds_by_itself(shop, order):
    order("stock", "0")
    rc, out = order("start", CUSTOMER_TIMEOUT=2)
    assert "waiting for the customer" in out, out
    deadline = time.time() + 30
    while shop("/stats")["refunds"] == 0 and time.time() < deadline:  # nobody answers; the timer does it
        time.sleep(0.5)
    assert shop("/stats")["refunds"] == 1


@needs_temporal
def test_temporal_sold_out_wait_then_coffee(shop, order):
    order("stock", "0")
    order("start")
    rc, out = order("customer", "wait")  # still sold out: asked again
    assert "waiting for the customer" in out, out
    rc, out = order("customer", "coffee")
    assert "kitchen coffee" in out, out
    s = shop("/stats")
    assert (s["refunds"], s["kitchen"]) == (0, 0)


@needs_temporal
def test_temporal_big_refund_waits_for_admin_and_audit(shop, order):
    order("stock", "0")
    order("start", REFUND_AUTO_LIMIT=50)
    rc, out = order("customer", "refund")
    assert "waiting for the admin" in out, out
    assert shop("/stats")["refunds"] == 0
    rc, out = order("admin", "approve")
    assert rc == 0, out
    assert shop("/stats")["refunds"] == 1
    rc, out = order("audit")
    assert rc == 0, out
    for line in ("read_order", "charge_upi", "check_payment", "check_stock", "ask_customer", "customer", "admin", "refund"):
        assert line in out, out
