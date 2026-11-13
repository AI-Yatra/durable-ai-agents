"""Fake outside world for the chai agent: a UPI bank, an SMS gateway and a kitchen.

Everything the agent does that "touches the real world" goes through here, so the
dashboard (http://localhost:8099) can count it. Stdlib only.

Bank
  POST /pay      {order_id, amount, phone?, key?} -> {receipt, status, duplicate}
                 status is "success", or "pending" when pending mode is on.
                 Same key twice -> the original receipt, no new payment.
                 Same order for the same phone, paid again -> a double charge (red on the dashboard).
  GET  /payment?receipt=rcpt-1              -> {receipt, status, amount, order_id}
  POST /settle   {receipt, outcome}         outcome: success | reversed
  POST /refund   {receipt, key?}            -> {refund, duplicate}
  POST /mode     {pending: bool}
SMS
  POST /sms      {to, text, key?}           -> {sms, duplicate}
Kitchen
  POST /kitchen  {order_id, qty, key?}      -> {ticket, duplicate} or 409 {error: "sold out"}
  GET/POST /stock {chai: n}
Demo
  GET /stats, POST /reset, GET / (dashboard)
"""

import json
import os
import socket
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# One table per thing the shop keeps track of. The `key` column is how we spot a repeat of the same request.
SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (receipt TEXT PRIMARY KEY, order_id TEXT, amount INTEGER, key TEXT, status TEXT, ts TEXT, who TEXT, phone TEXT);
CREATE TABLE IF NOT EXISTS refunds  (refund TEXT PRIMARY KEY, receipt TEXT, key TEXT);
CREATE TABLE IF NOT EXISTS sms      (id TEXT PRIMARY KEY, phone TEXT, text TEXT, key TEXT);
CREATE TABLE IF NOT EXISTS kitchen  (ticket TEXT PRIMARY KEY, order_id TEXT, qty INTEGER, key TEXT);
CREATE TABLE IF NOT EXISTS events   (n INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, who TEXT, kind TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT);
"""
# How many chai the kitchen has when the shop starts (or is reset).
DEFAULT_STOCK = 20
BOOT = str(time.time())  # changes every time the shop starts; the dashboard reloads itself when it does


# The shop itself: the bank, the SMS gateway and the kitchen, all backed by one small SQLite file.
class Shop:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        # One request at a time. The HTTP server is threaded, the ledger is not.
        self.lock = threading.Lock()
        self.who = "?"  # set per request from the X-Agent header: which script and pid called us
        if self.setting("stock") is None:
            self.set("stock", DEFAULT_STOCK)

    # --- helpers -------------------------------------------------------------
    # Small named values we need to remember: the stock, and whether pending mode is on.
    def setting(self, name):
        row = self.db.execute("SELECT value FROM settings WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def set(self, name, value):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (name, str(value)))

    # Write a line to the dashboard timeline and to this terminal. `kind` only picks the colour.
    def log(self, text, kind=""):
        self.db.execute("INSERT INTO events (ts, who, kind, text) VALUES (?, ?, ?, ?)", (time.strftime("%H:%M:%S"), self.who, kind, text))
        print(f"[shop] {self.who}: {text}", flush=True)

    # Ids are just a counter: rcpt-1, rcpt-2, sms-1, kot-1 ...
    def next_id(self, table, col, prefix):
        n = self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] + 1
        return f"{prefix}-{n}"

    # Have we already handled a request with this key? If so, return what we gave back last time.
    def by_key(self, table, col, key):
        if not key:
            return None
        row = self.db.execute(f"SELECT {col} FROM {table} WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    # --- bank ----------------------------------------------------------------
    def pay(self, order_id, amount, key=None, phone=None):
        # Seen this key before: hand back the old receipt and take no money.
        if (receipt := self.by_key("payments", "receipt", key)):
            status = self.db.execute("SELECT status FROM payments WHERE receipt=?", (receipt,)).fetchone()[0]
            self.log(f"bank: same key {key} -> {receipt} · not charged again", "ok")
            return {"receipt": receipt, "status": status, "duplicate": True}
        # No key, or a new one: this is a real charge.
        receipt = self.next_id("payments", "receipt", "rcpt")
        status = "pending" if self.setting("pending") == "1" else "success"
        # Has this customer already paid for this order? That is the double charge the demo is about, so log it in red.
        # The same order id from a different phone is somebody else's order, not a duplicate.
        again = self.db.execute("SELECT COUNT(*) FROM payments WHERE order_id=? AND phone IS ?", (order_id, phone)).fetchone()[0]
        self.db.execute("INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (receipt, order_id, amount, key, status, time.strftime("%H:%M:%S"), self.who, phone))
        customer = f" ({phone})" if phone else ""
        self.log(f"bank: charged ₹{amount} for {order_id}{customer} -> {receipt} ({status})" + (f" · {order_id}{customer} is now paid {again + 1}×" if again else ""), "bad" if again else "pay")
        return {"receipt": receipt, "status": status, "duplicate": False}

    # Look a payment up by its receipt, so the agent can ask "did that one go through?"
    def payment(self, receipt):
        row = self.db.execute("SELECT receipt, order_id, amount, status FROM payments WHERE receipt=?", (receipt,)).fetchone()
        if not row:
            return None
        return dict(zip(["receipt", "order_id", "amount", "status"], row))

    # A pending payment finally lands: it either succeeds or is reversed.
    def settle(self, receipt, outcome):
        self.db.execute("UPDATE payments SET status=? WHERE receipt=?", (outcome, receipt))
        self.log(f"bank: {receipt} settled -> {outcome}")
        return self.payment(receipt)

    # Give the money back. Same rule as pay: the same key never refunds twice.
    def refund(self, receipt, key=None):
        if (rf := self.by_key("refunds", "refund", key)):
            self.log(f"bank: duplicate refund key {key} -> {rf}, not refunded again")
            return {"refund": rf, "duplicate": True}
        rf = self.next_id("refunds", "refund", "rf")
        self.db.execute("INSERT INTO refunds VALUES (?, ?, ?)", (rf, receipt, key))
        self.log(f"bank: refunded {receipt} -> {rf}", "pay")
        return {"refund": rf, "duplicate": False}

    # --- sms and kitchen -----------------------------------------------------
    # "Send" a text message. Nothing leaves the machine, we only record it.
    def sms(self, phone, text, key=None):
        if (sid := self.by_key("sms", "id", key)):
            return {"sms": sid, "duplicate": True}
        sid = self.next_id("sms", "id", "sms")
        self.db.execute("INSERT INTO sms VALUES (?, ?, ?, ?)", (sid, phone, text, key))
        self.log(f"sms to {phone}: {text}")
        return {"sms": sid, "duplicate": False}

    # Send an order to the kitchen. Returns None when there isn't enough chai left.
    def kitchen(self, order_id, qty, key=None):
        if (t := self.by_key("kitchen", "ticket", key)):
            return {"ticket": t, "duplicate": True}
        stock = int(self.setting("stock"))
        if qty > stock:
            self.log(f"kitchen: {order_id} wants {qty}, only {stock} left -> sold out")
            return None
        self.set("stock", stock - qty)
        t = self.next_id("kitchen", "ticket", "kot")
        self.db.execute("INSERT INTO kitchen VALUES (?, ?, ?, ?)", (t, order_id, qty, key))
        self.log(f"kitchen: {qty} chai for {order_id} -> {t}")
        return {"ticket": t, "duplicate": False}

    # --- demo ----------------------------------------------------------------
    # Everything the dashboard shows, in one go: the counters, the payments table and the last 60 timeline lines.
    def stats(self):
        q = lambda sql: self.db.execute(sql).fetchone()[0]
        return {
            "payments": q("SELECT COUNT(*) FROM payments"),
            "pending": q("SELECT COUNT(*) FROM payments WHERE status='pending'"),
            "refunds": q("SELECT COUNT(*) FROM refunds"),
            "sms": q("SELECT COUNT(*) FROM sms"),
            "kitchen": q("SELECT COUNT(*) FROM kitchen"),
            "stock": int(self.setting("stock")),
            "pending_mode": self.setting("pending") == "1",
            "boot": BOOT,
            "payments_list": [dict(zip(["receipt", "order_id", "amount", "key", "status", "ts", "who", "phone"], r))
                              for r in self.db.execute("SELECT receipt, order_id, amount, key, status, ts, who, phone FROM payments ORDER BY rowid")],
            "events": [dict(zip(["ts", "who", "kind", "text"], r))
                       for r in self.db.execute("SELECT ts, who, kind, text FROM (SELECT * FROM events ORDER BY n DESC LIMIT 60) ORDER BY n")],
        }

    # Wipe the ledger and refill the stock. The dashboard's reset button calls this.
    def reset(self):
        for t in ["payments", "refunds", "sms", "kitchen", "events"]:
            self.db.execute(f"DELETE FROM {t}")
        self.set("stock", DEFAULT_STOCK)
        self.set("pending", "0")
        self.log("reset · fresh start", "reset")


# The dashboard is a single page kept right here in the file. It asks /stats twice a second and redraws itself.
DASHBOARD = """<!doctype html><meta charset=utf-8><title>chai shop</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#000;color:#fff;font:16px ui-monospace,Menlo,monospace;padding:32px 24px}
main{max-width:820px;margin:0 auto}
h1{font-size:14px;letter-spacing:.14em;text-transform:uppercase;color:#8a8a8a;margin:0 0 18px;display:flex;justify-content:space-between;align-items:center}
button{background:#000;color:#fff;border:1.5px solid #fff;font:inherit;font-size:13px;letter-spacing:.1em;text-transform:uppercase;padding:8px 16px;cursor:pointer}
button:hover{background:#fff;color:#000}
.g{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:28px}
.c{border:1.5px solid #333;padding:16px}.n{font-size:48px;font-weight:800;line-height:1}.l{margin-top:8px;color:#8a8a8a;font-size:12px;letter-spacing:.12em;text-transform:uppercase}
.c.big{border-color:#fff}.bad .n{color:#ff3b3b}.ok .n{color:#6ee7a0}
.cols{display:flex;flex-direction:column;gap:28px}
.tw{overflow-x:auto}
h2{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#8a8a8a;margin:0 0 10px;font-weight:400}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:7px 8px;border-bottom:1px solid #1c1c1c;white-space:nowrap}
th{color:#666;font-weight:400;font-size:12px}tr.dup td{color:#ff3b3b}td.k{color:#888}
.run{margin:0 0 14px;border-left:2px solid #444;padding-left:12px}
.run .who{color:#ffc600;font-size:13px;margin-bottom:4px}
.ev{display:flex;gap:12px;font-size:14px;line-height:1.75;color:#ccc}.ev .t{color:#555}
.ev.bad{color:#ff3b3b}.ev.ok{color:#6ee7a0}.ev.pay{color:#fff}.ev.reset{color:#555}
.empty{color:#555;font-size:14px}
#live{color:#6ee7a0;margin-left:14px;letter-spacing:.08em}#live.down{color:#ff3b3b}
</style>
<main>
<h1><span>chai shop · the outside world <span id=live>● live</span></span><button onclick="reset()">reset</button></h1>
<div class=g id=g></div>
<div class=cols>
  <div><h2>payments · what the bank did</h2><div class=tw><table id=pay></table></div></div>
  <div><h2>timeline · grouped by the process that called</h2><div id=ev></div></div>
</div>
</main>
<script>
const esc=s=>String(s??'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function reset(){await fetch('/reset',{method:'POST',body:'{}'});tick()}
let boot=null;
async function tick(){let s;
try{s=await (await fetch('/stats',{cache:'no-store'})).json();live.textContent='● live';live.className=''}
catch(e){live.textContent='● shop is down · waiting for it';live.className='down';return}
if(boot&&s.boot!==boot)return location.reload();  // the shop restarted (maybe with new code): load the fresh page
boot=s.boot;
const card=(l,n,c='')=>`<div class="c ${c}"><div class=n>${n}</div><div class=l>${l}</div></div>`;
g.innerHTML=card('payments made',s.payments,'big '+(s.payments>1?'bad':s.payments==1?'ok':''))+card('pending',s.pending)+card('refunds',s.refunds)
+card('sms sent',s.sms)+card('kitchen orders',s.kitchen)+card('chai left',s.stock,s.stock==0?'bad':'');
const who=p=>p.order_id+'|'+(p.phone||'');const per={};s.payments_list.forEach(p=>per[who(p)]=(per[who(p)]||0)+1);
pay.innerHTML=s.payments_list.length?'<tr><th>time</th><th>receipt</th><th>order</th><th>customer</th><th>₹</th><th>key</th><th>status</th><th>charged by</th></tr>'+
 s.payments_list.map(p=>`<tr class="${per[who(p)]>1?'dup':''}"><td>${p.ts}</td><td>${p.receipt}</td><td>${esc(p.order_id)}</td><td class=k>${esc(p.phone||'unknown')}</td><td>${p.amount}</td><td class=k>${esc(p.key||'none')}</td><td>${p.status}</td><td class=k>${esc(p.who)}</td></tr>`).join('')
 :'<tr><td class=empty>no payments yet</td></tr>';
let html='',cur=null;for(const e of s.events){if(e.who!==cur){if(cur!==null)html+='</div>';html+=`<div class=run><div class=who>${esc(e.who)}</div>`;cur=e.who}
 html+=`<div class="ev ${e.kind}"><span class=t>${e.ts}</span><span>${esc(e.text)}</span></div>`}
ev.innerHTML=html?html+'</div>':'<div class=empty>nothing yet · start an agent</div>'}
tick();setInterval(tick,500)
</script>"""


# Wire the shop up to HTTP: each URL below calls one method on Shop.
def make_server(port: int, db_path: str) -> ThreadingHTTPServer:
    shop = Shop(db_path)

    class H(BaseHTTPRequestHandler):
        # Keep the terminal quiet: we print our own lines in Shop.log.
        def log_message(self, *a):
            pass

        # Send a reply. Dicts go out as JSON, strings as they are (the dashboard page).
        def send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        # GET only reads: the dashboard, the counters, the stock, one payment.
        def do_GET(self):
            u = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(u.query).items()}
            with shop.lock:
                # Agents say who they are in the X-Agent header (script name and pid), so the timeline can group by process.
                shop.who = self.headers.get("X-Agent") or "browser"
                if u.path == "/":
                    return self.send(200, DASHBOARD, "text/html; charset=utf-8")
                if u.path == "/stats":
                    return self.send(200, shop.stats())
                if u.path == "/stock":
                    return self.send(200, {"chai": int(shop.setting("stock"))})
                if u.path == "/payment":
                    p = shop.payment(qs.get("receipt", ""))
                    return self.send(200 if p else 404, p or {"error": "no such receipt"})
            self.send(404, {"error": "not found"})

        # POST changes something. `with shop.db` saves the change when the request finishes.
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            b = json.loads(self.rfile.read(n) or b"{}")
            with shop.lock, shop.db:
                shop.who = self.headers.get("X-Agent") or "you (curl / dashboard)"
                match self.path:
                    case "/pay":
                        return self.send(200, shop.pay(b["order_id"], int(b["amount"]), b.get("key"), b.get("phone")))
                    case "/settle":
                        return self.send(200, shop.settle(b["receipt"], b["outcome"]))
                    case "/refund":
                        return self.send(200, shop.refund(b["receipt"], b.get("key")))
                    case "/mode":
                        shop.set("pending", "1" if b.get("pending") else "0")
                        return self.send(200, {"pending": bool(b.get("pending"))})
                    case "/sms":
                        return self.send(200, shop.sms(b["to"], b["text"], b.get("key")))
                    case "/kitchen":
                        r = shop.kitchen(b["order_id"], int(b["qty"]), b.get("key"))
                        return self.send(200 if r else 409, r or {"error": "sold out"})
                    case "/stock":
                        shop.set("stock", int(b["chai"]))
                        shop.log(f"stock set to {b['chai']}")
                        return self.send(200, {"chai": int(b["chai"])})
                    case "/reset":
                        shop.reset()
                        return self.send(200, {"ok": True})
            self.send(404, {"error": "not found"})

    return ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), port), H)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # ₹ on a Windows console
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    # Where to listen and which file holds the ledger.
    port = int(os.environ.get("PORT", "8099"))
    db = os.environ.get("SHOP_DB", "shop.db")
    # Check the port before touching the ledger: a second shop must not wipe the running one's DB.
    try:
        with socket.socket() as probe:
            # Right after a shop is killed, its old browser connections linger for a minute and
            # would make this check fail. SO_REUSEADDR ignores those but still fails if a shop is
            # really listening. (Not on Windows: there it would let two shops share the port.)
            if os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((os.environ.get("HOST", "127.0.0.1"), port))
    except OSError as e:  # in use (98 / 48 / WinError 10048) or reserved by Windows (WinError 10013)
        sys.exit(f"[shop] can't use port {port}: {e}\n"
                 f"  Is another shop already running? Close it, or pick another port: PORT=8199 here, SHOP_URL=http://127.0.0.1:8199 for the agent.")
    if os.environ.get("KEEP_DB") != "1" and os.path.exists(db):
        try:
            os.remove(db)  # every shop start is a clean slate; KEEP_DB=1 keeps the old ledger
        except PermissionError:  # Windows: another process still has it open
            sys.exit(f"[shop] {db} is in use by another process. Close the other shop first.")
    srv = make_server(port, db)
    print(f"[shop] dashboard on http://localhost:{port}", flush=True)
    srv.serve_forever()
