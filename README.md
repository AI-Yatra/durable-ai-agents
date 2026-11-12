# durable-ai-agents

A chai ordering agent that we kill on purpose. Code for the "Durable AI Agents" talk at AI Yatra (14 Nov 2026) and its three blog posts. One order goes through four steps:

```
read_order -> charge_upi(₹80) -> send_receipt -> send_to_kitchen
```

| File | What it is |
|---|---|
| `normal_agent.py` | the agent, everything in memory. Kill it after the charge: it starts over and **charges twice** |
| `durable_agent.py` | the same agent with the four fixes. Kill it anywhere: it carries on and **charges once** |
| `temporal_agent.py` | the same agent on Temporal, with two workers: kill one, the other finishes it, nobody restarts anything |
| `shop_mock.py` | the outside world: a UPI bank, an SMS gateway, a kitchen. Dashboard at http://localhost:8099 |
| `common.py` | the LLM call and small helpers |

The four fixes in `durable_agent.py`:

1. **Resume from the exact step**: `SqliteSaver` + `durability="sync"`.
2. **Side effects happen once**: the payment key is made once in `read_order` and saved.
3. **Wait for a person**: payment pending → wait for the bank; sold out → ask the customer; big refund → ask an admin. Each wait is saved.
4. **Write every step down**: `python durable_agent.py audit`.

The LLM is mocked with `MOCK_LLM=1`. For a real one, set `LLM_API_KEY` (any OpenAI-compatible endpoint; the default is NVIDIA's free one).

## Run it on your machine

```bash
uv sync
uv run python shop_mock.py                                   # terminal 1 · dashboard: http://localhost:8099
```

**The normal agent pays twice.**

```bash
MOCK_LLM=1 DEMO_PAUSE=8 uv run python normal_agent.py        # terminal 2
pkill -9 -f normal_agent.py                                  # terminal 3, during "charged ₹80 · 8s to kill me…"
MOCK_LLM=1 DEMO_PAUSE=8 uv run python normal_agent.py        # terminal 2 again → payments made 2
```

**The durable agent pays once.** Click reset on the dashboard first.

```bash
MOCK_LLM=1 DEMO_PAUSE=8 uv run python durable_agent.py
pkill -9 -f durable_agent.py                                 # during the countdown
MOCK_LLM=1 DEMO_PAUSE=8 uv run python durable_agent.py       # resumes at charge_upi · same key · payments made 1
```

The saved progress lives in `durable.db`. A new `ORDER_ID=order-2` is a new order; `rm durable.db` forgets them all.

**Waiting for the bank, the customer and an admin.**

```bash
curl -XPOST localhost:8099/mode -d '{"pending": true}'      # the bank leaves payments pending
MOCK_LLM=1 uv run python durable_agent.py                    # ⏸ waiting for the bank (it exits; the wait is saved)
MOCK_LLM=1 uv run python durable_agent.py                    # restart: still waiting, no new charge
uv run python durable_agent.py stock 0                       # chai runs out meanwhile
uv run python durable_agent.py bank success                  # → sold out → ⏸ waiting for the customer
uv run python durable_agent.py customer refund               # or wait / coffee / no-reply → refund once
uv run python durable_agent.py audit                         # every step, with how long each wait took
```

`bank reversed` instead: no money was taken, so the agent just tells the customer.
`ORDER="200 chai for 98765 43210"` makes a ₹4,000 order: its refund waits for `admin approve`.

**The trap.** `KEY_FROM=node` makes the payment key inside the charge step instead. Kill after the charge and it pays twice again.

## Run it in Docker

```bash
docker compose build
docker compose up -d shop                                    # dashboard: http://localhost:8099

docker compose up chai-agent                                 # the normal agent
docker kill chai-agent                                       # terminal 2, during the countdown
docker start -a chai-agent                                   # → payments made 2

AGENT=durable_agent docker compose up chai-agent             # click reset first
docker kill chai-agent
docker start -a chai-agent                                   # → payments made 1
docker compose run --rm chai-agent python durable_agent.py audit
```

The durable agent's checkpoints live on the `checkpoints` volume, so they survive the container. To forget them: `docker compose run --rm chai-agent rm -f /data/durable.db`.

## Temporal

Free and local, no account:

```bash
docker compose --profile temporal up -d temporal worker-1 worker-2   # UI: http://localhost:8233
docker compose run --rm chai-agent python temporal_agent.py start order-1
docker kill worker-1        # whichever worker printed "charged ₹80 · 8s to kill me…"
```

The other worker picks the order up within about 3 seconds and finishes it. Without Docker: `temporal server start-dev`, then `uv run python temporal_agent.py worker` in two terminals and `uv run python temporal_agent.py start`.

## Tests

```bash
uv run pytest -q          # every kill is a real SIGKILL; the Temporal test needs a server on localhost:7233
```
