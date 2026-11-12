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
