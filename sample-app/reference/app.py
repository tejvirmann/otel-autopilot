# shop-api: instrumented with otel-kit (reference solution)
import os, random, sqlite3, time
import httpx
from fastapi import FastAPI, Request
from opentelemetry.trace import Status, StatusCode
import otelkit

app = FastAPI()
otelkit.init("shop-api", app=app, version="1.0.0")
DB = os.path.join(os.path.dirname(__file__), "shop.db")
PAYMENTS = os.getenv("PAYMENTS_URL", "http://127.0.0.1:8001")


def db():
    return sqlite3.connect(DB)


def seed():
    if os.path.exists(DB):
        os.remove(DB)
    c = db()
    c.executescript("""
      create table categories(id integer primary key, name text);
      create table products(id integer primary key, name text, category_id int, price real);
      create table stock(product_id int, qty int);
      create table users(id integer primary key, email text, name text);
    """)
    for i in range(1, 6):
        c.execute("insert into categories values (?,?)", (i, f"cat-{i}"))
    for i in range(1, 41):
        c.execute("insert into products values (?,?,?,?)", (i, f"item-{i}", i % 5 + 1, 5.0 + i))
        c.execute("insert into stock values (?,?)", (i, random.randint(0, 50)))
    c.execute("insert into users values (1,'alice@example.com','Alice')")
    c.commit(); c.close()


seed()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/products")
def products():
    c = db()
    out = []
    for pid, name, cat_id, price in c.cursor().execute("select id,name,category_id,price from products").fetchall():
        cat = c.cursor().execute("select name from categories where id=%d" % cat_id).fetchone()[0]   # N+1
        qty = c.cursor().execute("select qty from stock where product_id=%d" % pid).fetchone()[0]     # N+1
        out.append({"id": pid, "name": name, "category": cat, "price": price, "in_stock": qty > 0})
    return out


@app.get("/orders/{order_id}")
def order(order_id: int):
    time.sleep(0.01)
    return {"order_id": order_id, "status": "shipped"}


@app.get("/users/lookup")
def lookup(email: str):
    c = db()
    row = c.cursor().execute("select id,name from users where email='%s'" % email).fetchone()  # raw SQL
    return {"found": row is not None}


@app.post("/checkout")
async def checkout(request: Request):
    body = await request.json()
    with otelkit.business_span("checkout.charge", **{"checkout.amount": body.get("amount", 0)}) as span:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(f"{PAYMENTS}/charge", json=body)
                r.raise_for_status()
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, "payment failed"))
            return {"status": "payment_failed"}
    return {"status": "ok"}


@app.get("/ask")
def ask(q: str):
    with otelkit.genai_call("example-llm", "demo-model-1") as call:
        time.sleep(0.05)              # pretend LLM call
        tokens_in, tokens_out = len(q.split()) + 12, 24
        call.record(tokens_in, tokens_out)
    return {"answer": f"echo: {q}", "tokens_in": tokens_in, "tokens_out": tokens_out}
