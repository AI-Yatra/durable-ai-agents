"""Shared bits for every agent: talking to the shop, the LLM, and the demo helpers.

Env vars
  SHOP_URL     where shop_mock.py runs              (default http://localhost:8099)
  MOCK_LLM=1   scripted LLM answer, no network      (default: use the real LLM)
  LLM_BASE_URL / LLM_API_KEY / LLM_MODEL   any OpenAI-compatible endpoint
               (default: NVIDIA's free endpoint, https://integrate.api.nvidia.com/v1)
  DEMO_PAUSE   seconds to wait at each banner, so you can `docker kill` by hand (default 0)
  CRASH_AT     name of a crash point; the process SIGKILLs itself there (tests, async demo)
  ORDER        the customer's message (default "4 chai for 98765 43210")
"""

import json
import os
import re
import signal
import sys
import time
import urllib.error
import urllib.request

SHOP_URL = os.environ.get("SHOP_URL", "http://localhost:8099")
ORDER = os.environ.get("ORDER", "4 chai for 98765 43210")
PRICE = 20  # ₹ per chai


def say(msg: str) -> None:
    print(f"[pid {os.getpid()}] {msg}", flush=True)


# --- the outside world -------------------------------------------------------
def shop(path: str, body: dict | None = None) -> dict:
    """POST (or GET when body is None) to the shop. A 409 comes back as {'error': ...}."""
    data = None if body is None else json.dumps(body).encode()
    who = f"{os.environ.get('WORKER_NAME') or os.path.basename(sys.argv[0])} · pid {os.getpid()}"
    req = urllib.request.Request(SHOP_URL + path, data=data, headers={"Content-Type": "application/json", "X-Agent": who})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (404, 409):
            return json.loads(e.read())
        raise


# --- the LLM -------------------------------------------------------------------
def llm_read_order(text: str) -> dict:
    """Turn 'four chai for 98765 43210' into {'phone': '9876543210', 'qty': 4}."""
    say(f"LLM call: read_order({text!r})")
    if os.environ.get("MOCK_LLM") == "1":
        phone = re.sub(r"\D", "", re.search(r"[\d ]{10,}", text).group())
        qty = int(re.search(r"\b(\d{1,2})\b", text).group(1))
        return {"phone": phone, "qty": qty}

    base = os.environ.get("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    model = os.environ.get("LLM_MODEL", "meta/llama-3.1-8b-instruct")
    prompt = (
        "Extract the order. Reply with JSON only, like {\"phone\": \"9876543210\", \"qty\": 4}.\n"
        f"Order: {text}"
    )
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['LLM_API_KEY']}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        content = json.loads(r.read())["choices"][0]["message"]["content"]
    out = json.loads(re.search(r"\{.*\}", content, re.S).group())
    return {"phone": re.sub(r"\D", "", str(out["phone"])), "qty": int(out["qty"])}


# --- demo helpers ------------------------------------------------------------
def banner(msg: str) -> None:
    """Print a big line and wait DEMO_PAUSE seconds: the window for `docker kill`."""
    pause = float(os.environ.get("DEMO_PAUSE", "0"))
    say(f"▶ {msg}" + (f" · {pause:.0f}s to kill me…" if pause else ""))
    for left in range(int(pause), 0, -1):
        print(f"    {left}…", flush=True)
        time.sleep(1)


def crash_point(name: str) -> None:
    """SIGKILL ourselves at a named point. No cleanup, no finally: same as docker kill."""
    if os.environ.get("CRASH_AT") == name:
        say(f"💀 CRASH_AT={name}: SIGKILL")
        sys.stdout.flush()
        os.kill(os.getpid(), signal.SIGKILL)
