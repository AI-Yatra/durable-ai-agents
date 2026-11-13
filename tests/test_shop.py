def test_same_key_charges_once(shop):
    a = shop("/pay", {"order_id": "o", "amount": 80, "key": "k1"})
    b = shop("/pay", {"order_id": "o", "amount": 80, "key": "k1"})
    assert a["receipt"] == b["receipt"] and b["duplicate"]
    assert shop("/stats")["payments"] == 1


def test_no_key_charges_every_time(shop):
    shop("/pay", {"order_id": "o", "amount": 80})
    shop("/pay", {"order_id": "o", "amount": 80})
    assert shop("/stats")["payments"] == 2


def test_pending_then_settle(shop):
    shop("/mode", {"pending": True})
    r = shop("/pay", {"order_id": "o", "amount": 80, "key": "k"})
    assert r["status"] == "pending"
    assert shop("/settle", {"receipt": r["receipt"], "outcome": "success"})["status"] == "success"


def test_kitchen_sold_out(shop):
    shop("/stock", {"chai": 2})
    assert shop("/kitchen", {"order_id": "o", "qty": 4})["error"] == "sold out"


def test_refund_once(shop):
    r = shop("/pay", {"order_id": "o", "amount": 80})
    shop("/refund", {"receipt": r["receipt"], "key": "rk"})
    shop("/refund", {"receipt": r["receipt"], "key": "rk"})
    assert shop("/stats")["refunds"] == 1


def test_double_charge_is_per_order_and_customer(shop):
    pay = lambda order, phone: shop("/pay", {"order_id": order, "phone": phone, "amount": 80})
    pay("o1", "111")
    pay("o1", "222")  # same order id, another customer: not a double charge
    pay("o2", "111")  # same customer, another order: not a double charge
    assert not [e for e in shop("/stats")["events"] if e["kind"] == "bad"]
    pay("o1", "111")  # same order, same customer, paid again
    bad = [e["text"] for e in shop("/stats")["events"] if e["kind"] == "bad"]
    assert len(bad) == 1 and "o1 (111) is now paid 2×" in bad[0]
