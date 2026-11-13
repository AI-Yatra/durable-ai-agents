"""The durable chai agent: agent.py plus the four fixes. Kill it anywhere; run it again; it finishes.

  1. Resume from the exact step   every finished step is saved to SQLite before the next starts
                                  (SqliteSaver + durability="sync")
  2. Side effects happen once     the payment key is made once, in read_order, and saved; a
                                  re-run charge sends the same key and the bank says "already paid"
  3. Wait for a person            payment pending? wait for the bank. Sold out? ask the customer.
                                  Big refund? ask an admin. Each wait is saved (interrupt()), so a
                                  restart comes back still waiting, never retrying
  4. Write every step down        every checkpoint is kept: `python durable_agent.py audit`

    read_order -> charge_upi -> check_payment --pending--> (wait for the bank) ---------------+
                                    |   ^__________________________________________________|
                                    |--reversed--> tell_customer -> END        (no money taken)
                                    '--success---> check_stock --in stock--> send_receipt -> send_to_kitchen -> END
                                                       '--sold out--> ask_customer (wait for the customer)
                                                                         |-- wait   -> check_stock
                                                                         |-- coffee -> send_receipt -> send_to_kitchen
                                                                         '-- refund / no-reply -> refund -> END
                                                                             (above ₹2,000: wait for an admin)

    python durable_agent.py                         run the order, or carry on from where it stopped
    python durable_agent.py bank success|reversed   the bank settles a pending payment
    python durable_agent.py customer wait|coffee|refund|no-reply
    python durable_agent.py admin approve|reject    for refunds above the limit
    python durable_agent.py stock 0                 the chai runs out
    python durable_agent.py audit                   every step this order took
    python durable_agent.py graph                   save a picture of the graph (durable_agent_graph.png)

ORDER_ID picks the order (default order-1): a new id is a new order with its own saved history.
"""

import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from common import ORDER, PRICE, banner, crash_point, llm_read_order, say, shop, show_graph

ORDER_ID = os.environ.get("ORDER_ID", "order-1")
CHECKPOINTS = os.path.join(os.environ.get("CHECKPOINT_DIR", "."), "durable.db")
REFUND_AUTO_LIMIT = int(os.environ.get("REFUND_AUTO_LIMIT", "2000"))  # ₹; above this an admin approves
CUSTOMER_TIMEOUT = int(os.environ.get("CUSTOMER_TIMEOUT", str(2 * 3600)))  # seconds; then we refund


class State(TypedDict, total=False):
    text: str
    phone: str
    qty: int
    pay_key: str
    receipt: str
    payment: str  # success | pending | reversed
    in_stock: bool
    choice: str  # wait | coffee | refund | no-reply
    item: str  # chai | coffee
    kitchen: str
    refund: str


# --- the steps -----------------------------------------------------------------
def read_order(state: State) -> dict:
    order = llm_read_order(state["text"])
    say(f"read_order: {order['qty']} chai for {order['phone']}")
    # fix 2: the payment key is made here, once, and saved with this step
    return {**order, "pay_key": f"{ORDER_ID}:{uuid.uuid4().hex[:8]}"}


def charge_upi(state: State) -> dict:
    amount = state["qty"] * PRICE
    key = state["pay_key"]
    if os.environ.get("KEY_FROM") == "node":
        key = f"{ORDER_ID}:{uuid.uuid4().hex[:8]}"  # the trap: a new key every time this step re-runs
    banner(f"about to charge ₹{amount} · key {key}")
    r = shop("/pay", {"order_id": ORDER_ID, "phone": state["phone"], "amount": amount, "key": key})
    say(f"charge_upi: ₹{amount} -> {r['receipt']} ({r['status']})" + ("  · bank: same key, not charged again" if r["duplicate"] else ""))
    crash_point("after_pay")
    banner(f"charged ₹{amount} · moving on")
    return {"receipt": r["receipt"]}


def check_payment(state: State) -> dict:
    status = shop(f"/payment?receipt={state['receipt']}")["status"]
    if status == "pending":
        # fix 3: not "retry" (a new payment) and not "failed" (the money may still land). Wait.
        # Everything above this line runs again on resume, so it only reads.
        interrupt({"waiting_for": "bank", "receipt": state["receipt"]})
        status = shop(f"/payment?receipt={state['receipt']}")["status"]  # the bank is the truth
    say(f"check_payment: {state['receipt']} is {status}")
    return {"payment": status}


def tell_customer(state: State) -> dict:
    shop("/sms", {"to": state["phone"], "text": "Your payment didn't go through. No money was taken.", "key": f"{ORDER_ID}:sms:reversed"})
    say("tell_customer: no money taken")
    return {}


def check_stock(state: State) -> dict:
    left = shop("/stock")["chai"]
    say(f"check_stock: {left} chai left, need {state['qty']}")
    return {"in_stock": left >= state["qty"]}


def ask_customer(state: State) -> dict:
    shop("/sms", {"to": state["phone"], "text": "Sorry, chai's sold out. Reply WAIT (10 min), COFFEE or REFUND.", "key": f"{ORDER_ID}:sms:ask"})
    choice = interrupt({"waiting_for": "customer", "options": ["wait", "coffee", "refund"], "deadline": time.time() + CUSTOMER_TIMEOUT})
    say(f"ask_customer: customer said {choice}")
    return {"choice": choice, "item": "coffee" if choice == "coffee" else "chai"}


def send_receipt(state: State) -> dict:
    # every side effect carries a key, so a re-run step never sends twice
    shop("/sms", {"to": state["phone"], "text": f"Paid ₹{state['qty'] * PRICE}, receipt {state['receipt']}", "key": f"{ORDER_ID}:sms:receipt"})
    say("send_receipt: sms sent")
    return {}


def send_to_kitchen(state: State) -> dict:
    if state.get("item") == "coffee":
        say(f"send_to_kitchen: {state['qty']} coffee")
        return {"kitchen": "coffee"}
    r = shop("/kitchen", {"order_id": ORDER_ID, "qty": state["qty"], "key": f"{ORDER_ID}:kitchen"})
    say(f"send_to_kitchen: {r.get('ticket') or r.get('error')}")
    return {"kitchen": r.get("ticket", "sold out")}


def refund(state: State) -> dict:
    amount = state["qty"] * PRICE
    if amount > REFUND_AUTO_LIMIT:
        if interrupt({"waiting_for": "admin", "refund": amount}) != "approve":
            say("refund: admin rejected")
            return {"refund": "rejected"}
    r = shop("/refund", {"receipt": state["receipt"], "key": f"{ORDER_ID}:refund"})  # once, even if re-run
    shop("/sms", {"to": state["phone"], "text": f"Refunded ₹{amount} ({r['refund']})", "key": f"{ORDER_ID}:sms:refund"})
    say(f"refund: ₹{amount} -> {r['refund']}")
    return {"refund": r["refund"]}


# --- the graph -------------------------------------------------------------------
def build(checkpointer):
    g = StateGraph(State)
    for node in (read_order, charge_upi, check_payment, tell_customer, check_stock, ask_customer, send_receipt, send_to_kitchen, refund):
        g.add_node(node)
    g.add_edge(START, "read_order")
    g.add_edge("read_order", "charge_upi")
    g.add_edge("charge_upi", "check_payment")

    g.add_conditional_edges("check_payment", lambda s: {"reversed": "tell_customer"}.get(s["payment"], "check_stock"), ["tell_customer", "check_stock"])
    g.add_edge("tell_customer", END)

    g.add_conditional_edges("check_stock", lambda s: "send_receipt" if s["in_stock"] else "ask_customer", ["send_receipt", "ask_customer"])
    g.add_conditional_edges("ask_customer", lambda s: {"wait": "check_stock", "coffee": "send_receipt"}.get(s["choice"], "refund"), ["check_stock", "send_receipt", "refund"])

    g.add_edge("send_receipt", "send_to_kitchen")
    g.add_edge("send_to_kitchen", END)
    g.add_edge("refund", END)
    return g.compile(checkpointer=checkpointer)


def saver() -> SqliteSaver:
    # fix 1: checkpoints on disk, not in RAM
    return SqliteSaver(sqlite3.connect(CHECKPOINTS, check_same_thread=False))


def go(graph, config, value):
    # fix 1: durability="sync" writes each step to disk before the next one starts
    # (the default, "async", saves in the background and a kill can lose the last step)
    graph.invoke(value, config, durability="sync")


# --- fix 4: every step, written down ---------------------------------------------
def audit(graph, config) -> list[str]:
    history = list(graph.get_state_history(config))[::-1]  # oldest first
    lines = []
    for before, after in zip(history, history[1:]):
        changed = {k: v for k, v in after.values.items() if before.values.get(k) != v and k not in ("text", "pay_key")}
        note = ", ".join(f"{k}={v}" for k, v in changed.items())
        waited = [i.value for t in before.tasks for i in t.interrupts]  # this step paused before it finished
        if waited:
            took = datetime.fromisoformat(after.created_at) - datetime.fromisoformat(before.created_at)
            note = f"⏸ waited for the {waited[0]['waiting_for']} ({str(took).split('.')[0]}) · " + note
        when = datetime.fromisoformat(after.created_at).astimezone().strftime("%a %H:%M:%S")
        lines.append(f"{when}  {', '.join(before.next) or 'input':<16} {note}")
    if history and history[-1].interrupts:
        lines.append(f"{'now':<12}  {', '.join(history[-1].next):<16} ⏸ waiting for the {history[-1].interrupts[0].value['waiting_for']}")
    return lines


# --- run it ---------------------------------------------------------------------
def report(graph, config):
    snap = graph.get_state(config)
    if snap.interrupts:
        who = snap.interrupts[0].value["waiting_for"]
        hint = {"bank": "bank success|reversed", "customer": "customer wait|coffee|refund|no-reply", "admin": "admin approve|reject"}[who]
        say(f"⏸ paused · waiting for the {who} · saved, safe to kill · next: python durable_agent.py {hint}")
    else:
        v = snap.values
        say(f"done · payment {v.get('payment')} · kitchen {v.get('kitchen', '-')} · refund {v.get('refund', '-')} · payments made {shop('/stats')['payments']}")


def main(argv):
    if argv == ["graph"]:  # only draws the graph: no saved runs needed, so no durable.db
        return show_graph("durable_agent_graph", build(None).get_graph().draw_mermaid())

    graph = build(saver())
    config = {"configurable": {"thread_id": ORDER_ID}}
    cmd = argv[0] if argv else "run"

    if cmd == "audit":
        return print("\n".join(audit(graph, config)) or "no saved steps for " + ORDER_ID)

    if cmd == "stock":
        shop("/stock", {"chai": int(argv[1])})
        return say(f"stock set to {argv[1]}")

    if cmd in ("bank", "customer", "admin"):
        answer = argv[1]
        waits = [i.value for i in graph.get_state(config).interrupts]
        if not waits or waits[0]["waiting_for"] != cmd:
            return say(f"nobody is waiting for the {cmd} right now")
        if cmd == "bank":
            shop("/settle", {"receipt": waits[0]["receipt"], "outcome": answer})
        go(graph, config, Command(resume=answer))
        return report(graph, config)

    snap = graph.get_state(config)
    if snap.interrupts:
        return report(graph, config)  # still waiting: nothing to do until someone answers
    if snap.next:
        say(f"found a saved run · resuming at {list(snap.next)} · done so far: {sorted(k for k in snap.values if k != 'text')}")
        go(graph, config, None)
    elif snap.values:
        say(f"{ORDER_ID} already finished · nothing to do")
    else:
        say(f"starting fresh · {ORDER_ID}")
        go(graph, config, {"text": ORDER})
    report(graph, config)


if __name__ == "__main__":
    main(sys.argv[1:])
