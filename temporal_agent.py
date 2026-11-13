"""The same chai agent on Temporal. Kill the worker; nobody restarts anything; it finishes.

This is durable_agent.py's flow, step for step, with Temporal doing the remembering:

  1. Resume from the exact step   Temporal keeps the history of each run on its server. When a
                                  worker dies mid-step, another worker picks the run up; finished
                                  steps (like the LLM call) come back from history
  2. Side effects happen once     still our job: every step sends a key, so a retried charge gets
                                  "already paid" from the bank
  3. Wait for a person            payment pending? wait for the bank. Sold out? ask the customer
                                  (and refund by ourselves if they never reply). Big refund? ask an
                                  admin. A wait costs nothing and survives any restart
  4. Write every step down        the history is the record: `python temporal_agent.py audit`,
                                  or the UI at http://localhost:8233

The workflow is the agent loop. The LLM call and every tool are activities.

Free, no account:  temporal server start-dev   (or the `temporal` service in compose.yaml)

    python temporal_agent.py worker worker-1            run two of these, worker-1 and worker-2
    pkill -9 -f "worker worker-1"                       kill one of them
    python temporal_agent.py start [order-1]            place the order; returns when it is done or waiting
    python temporal_agent.py bank success|reversed [order-1]      the bank settles a pending payment
    python temporal_agent.py customer wait|coffee|refund|no-reply [order-1]
    python temporal_agent.py admin approve|reject [order-1]       for refunds above the limit
    python temporal_agent.py stock 0                    the chai runs out
    python temporal_agent.py audit [order-1]            every step this order took
    python temporal_agent.py graph                      save a picture of the workflow (temporal_agent_graph.png)
"""

import asyncio
import json
import os
import signal
import sys
from datetime import timedelta, timezone

from temporalio import activity, workflow
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from common import ORDER, PRICE, crash_point, llm_read_order, say, shop, show_graph

TEMPORAL = os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233")
QUEUE = os.environ.get("TASK_QUEUE", "chai")
REFUND_AUTO_LIMIT = int(os.environ.get("REFUND_AUTO_LIMIT", "2000"))  # ₹; above this an admin approves
CUSTOMER_TIMEOUT = int(os.environ.get("CUSTOMER_TIMEOUT", str(2 * 3600)))  # seconds; then we refund


# --- activities: the steps that touch the outside world -----------------------
# Same steps as durable_agent.py. Temporal may run a step again (a worker died, a call timed
# out), so each one that changes something sends a key and the shop does it only once.
@activity.defn
async def read_order(text: str) -> dict:
    return llm_read_order(text)


@activity.defn
async def charge_upi(order_id: str, phone: str, amount: int, key: str) -> str:
    say(f"[{os.environ.get('WORKER_NAME', 'worker')}] about to charge ₹{amount} · key {key}")
    r = shop("/pay", {"order_id": order_id, "phone": phone, "amount": amount, "key": key})
    say(f"charge_upi: ₹{amount} -> {r['receipt']} ({r['status']})" + ("  · bank: same key, not charged again" if r["duplicate"] else ""))
    crash_point("after_pay")
    pause = int(os.environ.get("DEMO_PAUSE", "0"))
    if pause:
        say(f"▶ charged ₹{amount} · {pause}s to kill me…")
    for left in range(pause, 0, -1):
        activity.heartbeat(left)  # tells Temporal we're alive; stop heartbeating and it moves on
        await asyncio.sleep(1)
    return r["receipt"]


@activity.defn
async def check_payment(receipt: str) -> str:
    status = shop(f"/payment?receipt={receipt}")["status"]  # the bank is the truth
    say(f"check_payment: {receipt} is {status}")
    return status


@activity.defn
async def tell_customer(order_id: str, phone: str) -> None:
    shop("/sms", {"to": phone, "text": "Your payment didn't go through. No money was taken.", "key": f"{order_id}:sms:reversed"})
    say("tell_customer: no money taken")


@activity.defn
async def check_stock(qty: int) -> bool:
    left = shop("/stock")["chai"]
    say(f"check_stock: {left} chai left, need {qty}")
    return left >= qty


@activity.defn
async def ask_customer(order_id: str, phone: str) -> None:
    shop("/sms", {"to": phone, "text": "Sorry, chai's sold out. Reply WAIT (10 min), COFFEE or REFUND.", "key": f"{order_id}:sms:ask"})
    say("ask_customer: asked wait / coffee / refund")


@activity.defn
async def send_receipt(order_id: str, phone: str, amount: int, receipt: str) -> None:
    shop("/sms", {"to": phone, "text": f"Paid ₹{amount}, receipt {receipt}", "key": f"{order_id}:sms:receipt"})
    say("send_receipt: sms sent")


@activity.defn
async def send_to_kitchen(order_id: str, qty: int) -> str:
    r = shop("/kitchen", {"order_id": order_id, "qty": qty, "key": f"{order_id}:kitchen"})
    say(f"send_to_kitchen: {r.get('ticket') or r.get('error')}")
    return r.get("ticket", "sold out")


@activity.defn
async def refund(order_id: str, phone: str, amount: int, receipt: str) -> str:
    r = shop("/refund", {"receipt": receipt, "key": f"{order_id}:refund"})  # once, even if re-run
    shop("/sms", {"to": phone, "text": f"Refunded ₹{amount} ({r['refund']})", "key": f"{order_id}:sms:refund"})
    say(f"refund: ₹{amount} -> {r['refund']}")
    return r["refund"]


# --- the workflow: the agent loop ----------------------------------------------
STEP = dict(
    start_to_close_timeout=timedelta(seconds=60),
    heartbeat_timeout=timedelta(seconds=3),  # a dead worker is noticed within ~3s
    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1)),
)


@workflow.defn
class ChaiOrder:
    def __init__(self) -> None:
        self._waiting: dict | None = None  # who we are waiting for right now, if anyone
        self._answers: dict[str, str] = {}

    # `python temporal_agent.py bank|customer|admin ...` sends the answer in with this.
    @workflow.signal
    def answer(self, who: str, value: str) -> None:
        if self._waiting and self._waiting["waiting_for"] == who:  # a late or unasked-for answer is dropped
            self._answers[who] = value

    # ...and asks "are you waiting for somebody?" with this.
    @workflow.query
    def waiting(self) -> dict | None:
        return self._waiting

    async def wait_for(self, who: str, timeout: timedelta | None = None, **details) -> str | None:
        """Pause until `who` answers. Returns the answer, or None if `timeout` ran out first.

        Temporal saves the wait (and the timer) on its server: no worker has to stay up for it.
        """
        self._waiting = {"waiting_for": who, **details}
        try:
            await workflow.wait_condition(lambda: who in self._answers, timeout=timeout)
            return self._answers.pop(who)
        except asyncio.TimeoutError:
            return None
        finally:
            self._waiting = None

    @workflow.run
    async def run(self, job: dict) -> dict:
        order_id = workflow.info().workflow_id
        step = workflow.execute_activity

        order = await step(read_order, job["text"], **STEP)
        phone, qty = order["phone"], order["qty"]
        amount = qty * PRICE
        # The key is built from the order id, so every retry of this step sends the same one.
        receipt = await step(charge_upi, args=[order_id, phone, amount, f"{order_id}:charge"], **STEP)

        # Payment pending? Not "retry" (a new payment) and not "failed" (the money may still land). Wait.
        payment = await step(check_payment, receipt, **STEP)
        if payment == "pending":
            await self.wait_for("bank", receipt=receipt)
            payment = await step(check_payment, receipt, **STEP)
        if payment == "reversed":
            await step(tell_customer, args=[order_id, phone], **STEP)
            return {"payment": payment, "receipt": receipt}

        # Sold out? Ask the customer. No reply in time counts as "refund".
        item = "chai"
        while not await step(check_stock, qty, **STEP):
            await step(ask_customer, args=[order_id, phone], **STEP)
            choice = await self.wait_for("customer", timeout=timedelta(seconds=job["customer_timeout"]), options=["wait", "coffee", "refund"])
            if choice == "wait":
                continue  # look at the stock again
            if choice == "coffee":
                item = "coffee"
                break
            # refund, no-reply, or the timer ran out. Big refunds need an admin to say yes.
            if amount > job["refund_auto_limit"] and await self.wait_for("admin", refund=amount) != "approve":
                return {"payment": payment, "receipt": receipt, "refund": "rejected"}
            refunded = await step(refund, args=[order_id, phone, amount, receipt], **STEP)
            return {"payment": payment, "receipt": receipt, "refund": refunded}

        await step(send_receipt, args=[order_id, phone, amount, receipt], **STEP)
        kitchen = "coffee" if item == "coffee" else await step(send_to_kitchen, args=[order_id, qty], **STEP)
        return {"payment": payment, "receipt": receipt, "kitchen": kitchen}


ACTIVITIES = [read_order, charge_upi, check_payment, tell_customer, check_stock, ask_customer, send_receipt, send_to_kitchen, refund]

# Temporal has no graph object to draw (the workflow is plain Python), so the picture is written by hand.
# Keep it in step with ChaiOrder.run above.
WORKFLOW_GRAPH = """graph TD;
    start([start]) --> read_order(read_order)
    read_order --> charge_upi(charge_upi)
    charge_upi --> check_payment(check_payment)
    check_payment -. "pending: wait for the bank" .-> check_payment
    check_payment -. "reversed" .-> tell_customer(tell_customer)
    check_payment -. "success" .-> check_stock(check_stock)
    check_stock -. "in stock" .-> send_receipt(send_receipt)
    check_stock -. "sold out" .-> ask_customer("ask_customer<br/>wait for the customer")
    ask_customer -. "wait" .-> check_stock
    ask_customer -. "coffee" .-> send_receipt
    ask_customer -. "refund / no reply" .-> refund("refund<br/>big ones wait for an admin")
    send_receipt --> send_to_kitchen(send_to_kitchen)
    send_to_kitchen --> finish([end])
    tell_customer --> finish
    refund --> finish
"""

HINTS = {"bank": "bank success|reversed", "customer": "customer wait|coffee|refund|no-reply", "admin": "admin approve|reject"}


# --- entry points ----------------------------------------------------------------
async def connect() -> Client:
    try:
        return await Client.connect(TEMPORAL)
    except RuntimeError as e:
        sys.exit(f"can't reach the Temporal server at {TEMPORAL}. Is it running? (docker compose --profile temporal up -d temporal)\n  {e}")


async def worker(name: str):
    client = await connect()
    os.environ["WORKER_NAME"] = name  # so the shop dashboard shows which worker charged
    say(f"{name} polling task queue '{QUEUE}' on {TEMPORAL}")
    w = Worker(client, task_queue=QUEUE, workflows=[ChaiOrder], activities=ACTIVITIES)
    try:  # `docker stop` -> finish cleanly. (Windows' event loop has no signal handlers; skip it there.)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, lambda: asyncio.ensure_future(w.shutdown()))
    except NotImplementedError:
        pass
    await w.run()


async def report(handle: WorkflowHandle):
    """Wait until the order is finished or is waiting for somebody, then say which."""
    no_worker_since, hinted = None, False
    while True:
        if (await handle.describe()).status != WorkflowExecutionStatus.RUNNING:
            v = await handle.result()
            return say(f"done · payment {v.get('payment')} · kitchen {v.get('kitchen', '-')} · refund {v.get('refund', '-')} · payments made {shop('/stats')['payments']}")
        try:
            waiting = await handle.query(ChaiOrder.waiting, rpc_timeout=timedelta(seconds=2))
            no_worker_since = None
        except RPCError:
            waiting = None  # no worker is up to answer right now; the order is safe on the server
            no_worker_since = no_worker_since or asyncio.get_running_loop().time()
            if not hinted and asyncio.get_running_loop().time() - no_worker_since > 5:
                hinted = True
                say(f"no worker is answering. The order is safe on the server; start one: python temporal_agent.py worker worker-1  (queue '{QUEUE}')")
        if waiting:
            who = waiting["waiting_for"]
            return say(f"⏸ paused · waiting for the {who} · saved on the Temporal server · next: python temporal_agent.py {HINTS[who]} {handle.id}")
        await asyncio.sleep(0.5)


async def start(order_id: str):
    client = await connect()
    say(f"placing {order_id}: {ORDER!r}")
    job = {"text": ORDER, "refund_auto_limit": REFUND_AUTO_LIMIT, "customer_timeout": CUSTOMER_TIMEOUT}
    try:
        handle = await client.start_workflow(ChaiOrder.run, job, id=order_id, task_queue=QUEUE)
    except WorkflowAlreadyStartedError:
        sys.exit(f"{order_id} is already running. Watch it at http://localhost:8233, or start a new one: start order-2")
    await report(handle)


async def answer(who: str, value: str, order_id: str):
    """The bank, the customer or an admin answers a waiting order."""
    handle = (await connect()).get_workflow_handle(order_id)
    try:
        running = (await handle.describe()).status == WorkflowExecutionStatus.RUNNING
        waiting = await handle.query(ChaiOrder.waiting, rpc_timeout=timedelta(seconds=5)) if running else None
    except RPCError as e:
        sys.exit(f"can't ask {order_id} who it is waiting for ({e.message}). Is there such an order, and is a worker running?")
    if not waiting or waiting["waiting_for"] != who:
        return say(f"nobody is waiting for the {who} right now")
    if who == "bank":
        shop("/settle", {"receipt": waiting["receipt"], "outcome": value})
    await handle.signal(ChaiOrder.answer, args=[who, value])
    await report(handle)


async def audit(order_id: str):
    """Every step this order took, read back from Temporal's history."""
    handle = (await connect()).get_workflow_handle(order_id)
    # A step's result is stored as JSON; a step that returns nothing is stored empty.
    text = lambda payloads: ", ".join(json.dumps(json.loads(p.data), ensure_ascii=False) for p in payloads.payloads if p.data)
    names = {}  # event id of "step scheduled" -> step name
    try:
        async for e in handle.fetch_history_events():
            when = e.event_time.ToDatetime(tzinfo=timezone.utc).astimezone().strftime("%a %H:%M:%S")
            if e.HasField("activity_task_scheduled_event_attributes"):
                names[e.event_id] = e.activity_task_scheduled_event_attributes.activity_type.name
            elif e.HasField("activity_task_completed_event_attributes"):
                done = e.activity_task_completed_event_attributes
                print(f"{when}  {names[done.scheduled_event_id]:<16} {text(done.result)}")
            elif e.HasField("workflow_execution_signaled_event_attributes"):
                who, value = json.loads(f"[{text(e.workflow_execution_signaled_event_attributes.input)}]")
                print(f"{when}  {'⏸ ' + who:<16} answered {value}")
            elif e.HasField("timer_fired_event_attributes"):
                print(f"{when}  {'⏸ customer':<16} no reply in time")
    except RPCError as e:
        sys.exit(f"no saved steps for {order_id} ({e.message})")


if __name__ == "__main__":
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "start"
    arg = lambda i, default: argv[i] if len(argv) > i else default
    order_id = os.environ.get("ORDER_ID", "order-1")

    if cmd == "graph":
        show_graph("temporal_agent_graph", WORKFLOW_GRAPH)
    elif cmd == "worker":
        asyncio.run(worker(arg(1, os.environ.get("WORKER_NAME", f"worker-{os.getpid()}"))))
    elif cmd == "stock":
        shop("/stock", {"chai": int(argv[1])})
        say(f"stock set to {argv[1]}")
    elif cmd in HINTS:
        if len(argv) < 2:
            sys.exit(f"usage: python temporal_agent.py {HINTS[cmd]} [order-id]")
        asyncio.run(answer(cmd, argv[1], arg(2, order_id)))
    elif cmd == "audit":
        asyncio.run(audit(arg(1, order_id)))
    else:
        asyncio.run(start(arg(1, order_id)))
