import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shop_mock import make_server  # noqa: E402


@pytest.fixture
def shop(tmp_path):
    srv = make_server(0, str(tmp_path / "shop.db"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())

    call.url = url
    yield call
    srv.shutdown()


@pytest.fixture
def run(shop, tmp_path):
    """Run an agent script as its own process (so SIGKILL is real). Returns (returncode, output)."""

    def _run(script, *args, **env):
        e = {**os.environ, "SHOP_URL": shop.url, "MOCK_LLM": "1", "CHECKPOINT_DIR": str(tmp_path), "DEMO_PAUSE": "0"}
        e.pop("CRASH_AT", None)
        e.update({k: str(v) for k, v in env.items()})
        p = subprocess.run([sys.executable, script, *args], cwd=ROOT, env=e, capture_output=True, text=True, encoding="utf-8", timeout=60)
        return p.returncode, p.stdout + p.stderr

    return _run
