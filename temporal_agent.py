"""The same chai agent on Temporal. Kill the worker; nobody restarts anything; it finishes.

The workflow is the agent loop. The LLM call and every tool are activities. Temporal keeps the
history of each run on its server, so when a worker dies mid-step, another worker picks the run
up and carries on from the last finished step. Finished steps (like the LLM call) come back from
history; the interrupted step is retried with the same idempotency key, so the bank says
"already paid".

Free, no account:  temporal server start-dev   (or the `temporal` service in compose.yaml)
UI: http://localhost:8233

    python temporal_agent.py worker worker-1   # run two of these, worker-1 and worker-2
    pkill -9 -f "worker worker-1"              # kill one of them
    python temporal_agent.py start       # place the order and wait for it to finish
"""

import asyncio
import os
import signal
import sys
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from common import ORDER, PRICE, crash_point, llm_read_order, say, shop

TEMPORAL = os.environ.get("TEMPORAL_ADDRESS", "127.0.0.1:7233")
QUEUE = os.environ.get("TASK_QUEUE", "chai")


# --- activities: the steps that touch the outside world -----------------------
@activity.defn
async def read_order(text: str) -> dict:
    return llm_read_order(text)


@activity.defn
async def charge_upi(order_id: str, amount: int, key: str) -> str:
    say(f"[{os.environ.get('WORKER_NAME', 'worker')}] about to charge ₹{amount} · key {key}")
    r = shop("/pay", {"order_id": order_id, "amount": amount, "key": key})
    say(f"charge_upi: ₹{amount} -> {r['receipt']}" + ("  · bank: same key, not charged again" if r["duplicate"] else ""))
    crash_point("after_pay")
    pause = int(os.environ.get("DEMO_PAUSE", "0"))
    if pause:
        say(f"▶ charged ₹{amount} · {pause}s to kill me…")
    for left in range(pause, 0, -1):
        activity.heartbeat(left)  # tells Temporal we're alive; stop heartbeating and it moves on
        await asyncio.sleep(1)
    return r["receipt"]


@activity.defn
async def send_receipt(phone: str, text: str, key: str) -> None:
    shop("/sms", {"to": phone, "text": text, "key": key})
    say("send_receipt: sms sent")


@activity.defn
async def send_to_kitchen(order_id: str, qty: int, key: str) -> str:
    r = shop("/kitchen", {"order_id": order_id, "qty": qty, "key": key})
    say(f"send_to_kitchen: {r.get('ticket') or r.get('error')}")
    return r.get("ticket", "sold out")


# --- the workflow: the agent loop ----------------------------------------------
STEP = dict(
    start_to_close_timeout=timedelta(seconds=60),
    heartbeat_timeout=timedelta(seconds=3),  # a dead worker is noticed within ~3s
    retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1)),
)


@workflow.defn
class ChaiOrder:
    @workflow.run
    async def run(self, text: str) -> dict:
        order_id = workflow.info().workflow_id
        order = await workflow.execute_activity(read_order, text, **STEP)
        amount = order["qty"] * PRICE
        receipt = await workflow.execute_activity(charge_upi, args=[order_id, amount, f"{order_id}:charge"], **STEP)
        await workflow.execute_activity(send_receipt, args=[order["phone"], f"Paid ₹{amount}, receipt {receipt}", f"{order_id}:sms"], **STEP)
        kitchen = await workflow.execute_activity(send_to_kitchen, args=[order_id, order["qty"], f"{order_id}:kot"], **STEP)
        return {"receipt": receipt, "kitchen": kitchen}


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
    w = Worker(client, task_queue=QUEUE, workflows=[ChaiOrder], activities=[read_order, charge_upi, send_receipt, send_to_kitchen])
    try:  # `docker stop` -> finish cleanly. (Windows' event loop has no signal handlers; skip it there.)
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, lambda: asyncio.ensure_future(w.shutdown()))
    except NotImplementedError:
        pass
    await w.run()


async def start(order_id: str):
    client = await connect()
    say(f"placing {order_id}: {ORDER!r}")
    try:
        result = await client.execute_workflow(ChaiOrder.run, ORDER, id=order_id, task_queue=QUEUE)
    except WorkflowAlreadyStartedError:
        sys.exit(f"{order_id} is already running. Watch it at http://localhost:8233, or start a new one: start order-2")
    say(f"done · {result} · payments made {shop('/stats')['payments']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "worker":
        asyncio.run(worker(sys.argv[2] if len(sys.argv) > 2 else os.environ.get("WORKER_NAME", f"worker-{os.getpid()}")))
    else:
        asyncio.run(start(sys.argv[2] if len(sys.argv) > 2 else "order-1"))
