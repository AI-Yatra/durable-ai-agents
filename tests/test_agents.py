"""Both agents under a real SIGKILL (CRASH_AT=after_pay), then a restart."""


# --- the normal agent -------------------------------------------------------------
def test_normal_runs_clean(shop, run):
    rc, out = run("normal_agent.py")
    assert rc == 0, out
    s = shop("/stats")
    assert (s["payments"], s["sms"], s["kitchen"]) == (1, 1, 1)


def test_normal_kill_after_charge_pays_twice(shop, run):
    rc, _ = run("normal_agent.py", CRASH_AT="after_pay")
    assert rc == -9
    rc, out = run("normal_agent.py")
    assert rc == 0, out
    assert shop("/stats")["payments"] == 2


# --- the durable agent: fix 1 + 2, resume at the step and charge once ---------------
def test_durable_runs_clean(shop, run):
    rc, out = run("durable_agent.py")
    assert rc == 0, out
    s = shop("/stats")
    assert (s["payments"], s["sms"], s["kitchen"]) == (1, 1, 1)


def test_durable_kill_after_charge_pays_once(shop, run):
    rc, _ = run("durable_agent.py", CRASH_AT="after_pay")
    assert rc == -9
    rc, out = run("durable_agent.py")
    assert rc == 0, out
    assert "resuming at ['charge_upi']" in out
    assert "LLM call" not in out  # read_order came back from the checkpoint
    assert "not charged again" in out
    s = shop("/stats")
    assert (s["payments"], s["sms"], s["kitchen"]) == (1, 1, 1)


def test_durable_trap_key_in_node_pays_twice(shop, run):
    run("durable_agent.py", CRASH_AT="after_pay", KEY_FROM="node")
    run("durable_agent.py", KEY_FROM="node")
    assert shop("/stats")["payments"] == 2


def test_durable_finished_order_does_nothing(shop, run):
    run("durable_agent.py")
    rc, out = run("durable_agent.py")
    assert "already finished" in out
    assert shop("/stats")["payments"] == 1


def test_durable_new_order_id_is_a_new_order(shop, run):
    run("durable_agent.py")
    run("durable_agent.py", ORDER_ID="order-2")
    assert shop("/stats")["payments"] == 2


# --- fix 3: wait for the bank / the customer / an admin ----------------------------
def test_pending_waits_across_a_restart_then_bank_success(shop, run):
    shop("/mode", {"pending": True})
    rc, out = run("durable_agent.py")
    assert rc == 0 and "waiting for the bank" in out, out
    rc, out = run("durable_agent.py")  # a restart while waiting: still waiting, no new charge
    assert "waiting for the bank" in out
    assert shop("/stats")["payments"] == 1
    rc, out = run("durable_agent.py", "bank", "success")
    assert rc == 0, out
    s = shop("/stats")
    assert (s["payments"], s["kitchen"], s["refunds"]) == (1, 1, 0)


def test_bank_reversed_tells_customer(shop, run):
    shop("/mode", {"pending": True})
    run("durable_agent.py")
    rc, out = run("durable_agent.py", "bank", "reversed")
    assert "no money taken" in out, out
    s = shop("/stats")
    assert (s["kitchen"], s["refunds"]) == (0, 0)


def test_sold_out_no_reply_refunds_once(shop, run):
    shop("/mode", {"pending": True})
    run("durable_agent.py")
    run("durable_agent.py", "stock", "0")  # chai runs out while we wait
    rc, out = run("durable_agent.py", "bank", "success")
    assert "waiting for the customer" in out, out
    rc, out = run("durable_agent.py", "customer", "no-reply")
    assert rc == 0, out
    rc, out = run("durable_agent.py", "customer", "refund")  # late answer: nothing waiting
    assert "nobody is waiting" in out
    s = shop("/stats")
    assert (s["payments"], s["refunds"], s["kitchen"]) == (1, 1, 0)


def test_sold_out_coffee(shop, run):
    run("durable_agent.py", "stock", "0")
    run("durable_agent.py")
    rc, out = run("durable_agent.py", "customer", "coffee")
    assert "coffee" in out, out
    s = shop("/stats")
    assert (s["refunds"], s["kitchen"]) == (0, 0)


def test_big_refund_waits_for_admin(shop, run):
    run("durable_agent.py", "stock", "0")
    run("durable_agent.py", REFUND_AUTO_LIMIT=50)
    rc, out = run("durable_agent.py", "customer", "refund", REFUND_AUTO_LIMIT=50)
    assert "waiting for the admin" in out, out
    assert shop("/stats")["refunds"] == 0
    run("durable_agent.py", "admin", "approve", REFUND_AUTO_LIMIT=50)
    assert shop("/stats")["refunds"] == 1


# --- fix 4: every step written down ------------------------------------------------
def test_audit_lists_every_step(shop, run):
    shop("/mode", {"pending": True})
    run("durable_agent.py")
    run("durable_agent.py", "bank", "success")
    rc, out = run("durable_agent.py", "audit")
    assert rc == 0, out
    for step in ("read_order", "charge_upi", "check_payment", "check_stock", "send_receipt", "send_to_kitchen"):
        assert step in out, out
    assert "waited for the bank" in out
