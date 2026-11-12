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
