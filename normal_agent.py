"""The normal chai agent: four steps, everything in memory. This is the one we crash.

    read_order -> charge_upi -> send_receipt -> send_to_kitchen

Kill it right after charge_upi and start it again: it starts from scratch and
charges the customer a second time. (Dashboard: payments made 2.)
durable_agent.py is the same agent with the four fixes.
"""

from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from common import ORDER, PRICE, banner, crash_point, llm_read_order, say, shop


class State(TypedDict, total=False):
    text: str
    phone: str
    qty: int
    receipt: str
    kitchen: str


def read_order(state: State) -> dict:
    order = llm_read_order(state["text"])
    say(f"read_order: {order['qty']} chai for {order['phone']}")
    return order


def charge_upi(state: State) -> dict:
    amount = state["qty"] * PRICE
    banner(f"about to charge ₹{amount}")
    r = shop("/pay", {"order_id": "order-1", "amount": amount})
    say(f"charge_upi: ₹{amount} -> {r['receipt']}")
    crash_point("after_pay")
    banner(f"charged ₹{amount} · moving on")
    return {"receipt": r["receipt"]}


def send_receipt(state: State) -> dict:
    shop("/sms", {"to": state["phone"], "text": f"Paid ₹{state['qty'] * PRICE}, receipt {state['receipt']}"})
    say("send_receipt: sms sent")
    return {}


def send_to_kitchen(state: State) -> dict:
    r = shop("/kitchen", {"order_id": "order-1", "qty": state["qty"]})
    say(f"send_to_kitchen: {r.get('ticket') or r.get('error')}")
    return {"kitchen": r.get("ticket", "sold out")}


def build(checkpointer):
    g = StateGraph(State)
    for node in (read_order, charge_upi, send_receipt, send_to_kitchen):
        g.add_node(node)
    g.add_edge(START, "read_order")
    g.add_edge("read_order", "charge_upi")
    g.add_edge("charge_upi", "send_receipt")
    g.add_edge("send_receipt", "send_to_kitchen")
    g.add_edge("send_to_kitchen", END)
    return g.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    graph = build(InMemorySaver())
    config = {"configurable": {"thread_id": "order-1"}}
    say("starting fresh")
    result = graph.invoke({"text": ORDER}, config)
    stats = shop("/stats")
    say(f"done · payments made {stats['payments']} · kitchen {result['kitchen']}")
