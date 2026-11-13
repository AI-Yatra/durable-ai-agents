"""The normal chai agent: four steps, everything in memory. This is the one we crash.

    read_order -> charge_upi -> send_receipt -> send_to_kitchen

Kill it right after charge_upi and start it again: it starts from scratch and
charges the customer a second time. (Dashboard: payments made 2.)
durable_agent.py is the same agent with the four fixes.
"""

import os
import sys
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from common import PRICE, banner, crash_point, llm_read_order, say, shop, show_graph

# Which order this run is working on. Running the same order again is the bug
# we want to show (the customer pays twice); a new order needs a new id:
#     ORDER_ID=order-2 python normal_agent.py
ORDER_ID = os.environ.get("ORDER_ID", "order-2")


# Everything the agent knows about one order. Each step reads what it needs
# from here and returns the new fields it wants to add.
class State(TypedDict, total=False):
    text: str  # the customer's message, as they typed it
    phone: str  # who to send the receipt to
    qty: int  # how many chai
    receipt: str  # payment receipt number from the shop
    kitchen: str  # kitchen ticket, or "sold out"


def read_order(state: State) -> dict:
    # Ask the LLM to pull the phone number and quantity out of the message.
    order = llm_read_order(state["text"])
    say(f"read_order: {order['qty']} chai for {order['phone']}")
    return order


def charge_upi(state: State) -> dict:
    # Take the money. This is the step we must never run twice.
    amount = state["qty"] * PRICE
    banner(f"about to charge ₹{amount}")
    response = shop("/pay", {"order_id": ORDER_ID, "phone": state["phone"], "amount": amount})
    say(f"charge_upi: ₹{amount} -> {response['receipt']}")

    # The demo kills the agent here: the customer has paid, but we haven't
    # saved that anywhere yet.
    crash_point("after_pay")
    banner(f"charged ₹{amount} · moving on")
    return {"receipt": response["receipt"]}


def send_receipt(state: State) -> dict:
    # Text the customer their receipt.
    amount = state["qty"] * PRICE
    message = f"Paid ₹{amount}, receipt {state['receipt']}"
    shop("/sms", {"to": state["phone"], "text": message})
    say("send_receipt: sms sent")
    return {}


def send_to_kitchen(state: State) -> dict:
    # Tell the kitchen to start making the chai. It may be sold out.
    response = shop("/kitchen", {"order_id": ORDER_ID, "qty": state["qty"]})
    say(f"send_to_kitchen: {response.get('ticket') or response.get('error')}")
    return {"kitchen": response.get("ticket", "sold out")}


def build_graph(checkpointer):
    builder = StateGraph(State)

    # The four steps.
    builder.add_node("read_order", read_order)
    builder.add_node("charge_upi", charge_upi)
    builder.add_node("send_receipt", send_receipt)
    builder.add_node("send_to_kitchen", send_to_kitchen)

    # Run them one after another, in a straight line.
    builder.add_edge(START, "read_order")
    builder.add_edge("read_order", "charge_upi")
    builder.add_edge("charge_upi", "send_receipt")
    builder.add_edge("send_receipt", "send_to_kitchen")
    builder.add_edge("send_to_kitchen", END)

    return builder.compile(checkpointer=checkpointer)


if __name__ == "__main__":
    # InMemorySaver keeps the progress in this process's memory, so it is
    # gone the moment the process dies. That is the whole problem.
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": ORDER_ID}}

    # `python normal_agent.py graph` saves a picture of the graph as
    # normal_agent_graph.png, opens it and stops. Needs internet.
    if sys.argv[1:] == ["graph"]:
        show_graph("normal_agent_graph", graph.get_graph().draw_mermaid())
        sys.exit()

    prompt = "4 chai for me my number is 98765 43210"  # the customer's message
    say(f"starting fresh · {ORDER_ID} · {prompt!r}")
    result = graph.invoke({"text": prompt}, config)

    stats = shop("/stats")
    say(f"done · payments made {stats['payments']} · kitchen {result['kitchen']}")
