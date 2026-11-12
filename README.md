# durable-ai-agents

A chai ordering agent that we kill on purpose.

A customer sends *"4 chai for 98765 43210"*. The agent reads the order with an LLM, charges ₹80 over UPI, texts a receipt and sends the order to the kitchen. Then we `kill -9` it right after the charge and start it again.

- **The normal agent** starts over and charges the customer **twice**.
- **The durable agent** carries on from the step it died in and charges **once**.
- **The Temporal agent** doesn't even need restarting: a second worker notices and finishes the order.

Code for the **Durable AI Agents** talk at AI Yatra (14 Nov 2026) and its three blog posts:

1. Build the chai agent, then crash it *(link coming)*
2. Make it durable *(link coming)*
3. Run it on Temporal *(link coming)*

## What's inside

| File | What it is |
|---|---|
| [`normal_agent.py`](normal_agent.py) | The agent, built with LangGraph. Everything lives in memory. |
| [`durable_agent.py`](durable_agent.py) | The same agent with four fixes. Kill it anywhere and it finishes, paying once. |
| [`temporal_agent.py`](temporal_agent.py) | The same agent as a Temporal workflow, run by two workers. |
| [`shop_mock.py`](shop_mock.py) | The outside world: a UPI bank, an SMS gateway and a kitchen, with a live dashboard. |
| [`common.py`](common.py) | The LLM call and small helpers. |
| [`tests/`](tests) | Every crash is a real `SIGKILL`, checked by counting payments. |

```
read_order ──> charge_upi(₹80) ──> send_receipt ──> send_to_kitchen
   (LLM)          (bank)              (SMS)            (kitchen)
                     ▲
                     └── kill -9 here
```

### The four fixes in `durable_agent.py`

| Promise | How |
|---|---|
| **Resume from the exact step** | `SqliteSaver` + `durability="sync"`: each finished step is on disk before the next starts |
| **Side effects happen once** | the payment key is made once in `read_order` and saved; a re-run charge reuses it and the bank says "already paid" |
| **Wait for a person** | payment pending → wait for the bank · sold out → ask the customer · big refund → ask an admin. Each wait is saved with `interrupt()`, so a restart comes back still waiting |
| **Write every step down** | the checkpoint history is the audit log: `python durable_agent.py audit` |

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Docker, for the container runs and for the Temporal server. No Temporal account is needed.
- An LLM is optional. `MOCK_LLM=1` fakes it. For a real one, set `LLM_API_KEY`. Any OpenAI-compatible endpoint works; the default is [NVIDIA's free one](https://build.nvidia.com).

```bash
git clone https://github.com/been-there-done-that/durable-ai-agents
cd durable-ai-agents
uv sync
```

## 1 · The normal agent pays twice

```bash
uv run python shop_mock.py                                   # terminal 1 · open http://localhost:8099

MOCK_LLM=1 DEMO_PAUSE=8 uv run python normal_agent.py        # terminal 2
pkill -9 -f normal_agent.py                                  # terminal 3, during "charged ₹80 · 8s to kill me…"
MOCK_LLM=1 DEMO_PAUSE=8 uv run python normal_agent.py        # terminal 2 again
```

The dashboard shows **payments made 2**, both rows in red.

## 2 · The durable agent pays once

Click **reset** on the dashboard, then:

```bash
MOCK_LLM=1 DEMO_PAUSE=8 uv run python durable_agent.py
pkill -9 -f durable_agent.py                                 # during the countdown
MOCK_LLM=1 DEMO_PAUSE=8 uv run python durable_agent.py
```

```
found a saved run · resuming at ['charge_upi'] · done so far: ['pay_key', 'phone', 'qty']
charge_upi: ₹80 -> rcpt-1 (success)  · bank: same key, not charged again
```

The second run makes no LLM call, because `read_order` came back from disk. **Payments made: 1.**

Progress is saved in `durable.db`. `ORDER_ID=order-2` starts a new order; `rm durable.db` forgets them all.

**The trap.** `KEY_FROM=node` makes the payment key inside the charge step instead. Every re-run gets a new key, so it pays twice again.

### Waiting for the bank, the customer and an admin

```bash
curl -XPOST localhost:8099/mode -d '{"pending": true}'      # the bank leaves payments pending
MOCK_LLM=1 uv run python durable_agent.py                    # ⏸ waiting for the bank (exits; the wait is saved)
MOCK_LLM=1 uv run python durable_agent.py                    # restart: still waiting, no new charge
uv run python durable_agent.py stock 0                       # the chai runs out meanwhile
uv run python durable_agent.py bank success                  # → sold out → ⏸ waiting for the customer
uv run python durable_agent.py customer refund               # or wait / coffee / no-reply
uv run python durable_agent.py audit
```

```
Thu 19:30:01  read_order       phone=9876543210, qty=4
Thu 19:30:01  charge_upi       receipt=rcpt-1
Thu 19:31:40  check_payment    ⏸ waited for the bank (0:01:39) · payment=success
Thu 19:31:40  check_stock      in_stock=False
Thu 19:32:05  ask_customer     ⏸ waited for the customer (0:00:25) · choice=refund
Thu 19:32:05  refund           refund=rf-1
```

- `bank reversed`: no money was taken, so the agent only tells the customer.
- `ORDER="200 chai for 98765 43210"`: the ₹4,000 refund waits for `admin approve`.

## 3 · Temporal: nobody restarts it

```bash
docker compose --profile temporal up -d temporal                                  # UI: http://localhost:8233
MOCK_LLM=1 DEMO_PAUSE=8 uv run python temporal_agent.py worker worker-1           # terminal A
MOCK_LLM=1 DEMO_PAUSE=8 uv run python temporal_agent.py worker worker-2           # terminal B
MOCK_LLM=1 uv run python temporal_agent.py start order-1                          # terminal C
pkill -9 -f "worker worker-1"      # whichever worker printed "charged ₹80 · 8s to kill me…"
```

Within about 3 seconds the other worker picks the order up and finishes it, paying once. Without Docker, install the [Temporal CLI](https://docs.temporal.io/cli) and run `temporal server start-dev`.

## Everything in Docker

```bash
docker compose build
docker compose up -d shop                                    # http://localhost:8099

docker compose up chai-agent                                 # the normal agent
docker kill chai-agent                                       # from another terminal, during the countdown
docker start -a chai-agent                                   # → payments made 2

AGENT=durable_agent docker compose up chai-agent             # reset the dashboard first
docker kill chai-agent
docker start -a chai-agent                                   # → payments made 1

docker compose --profile temporal up -d temporal worker-1 worker-2
docker compose run --rm chai-agent python temporal_agent.py start order-1
docker kill worker-1                                         # or worker-2
```

The durable agent's checkpoints live on the `checkpoints` volume, so they outlive the container. To clear them: `docker compose run --rm chai-agent rm -f /data/durable.db`.

## Tests

```bash
uv run pytest -q
```

Each kill is a real `SIGKILL` (`CRASH_AT=after_pay`). The Temporal test runs when a server is up on `localhost:7233`, and is skipped otherwise.

## Settings

| Variable | Default | |
|---|---|---|
| `MOCK_LLM` | off | `1` = scripted LLM, no network |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | NVIDIA, `meta/llama-3.1-8b-instruct` | any OpenAI-compatible endpoint |
| `DEMO_PAUSE` | `0` | seconds to wait at each step: your window to kill it |
| `ORDER` | `4 chai for 98765 43210` | the customer's message |
| `ORDER_ID` | `order-1` | durable agent: which order (each has its own history) |
| `SHOP_URL` | `http://localhost:8099` | where the shop runs |
| `KEEP_DB` | off | `1` = the shop keeps its ledger across restarts |

## License

MIT
