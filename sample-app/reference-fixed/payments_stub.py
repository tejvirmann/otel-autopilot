"""Downstream 'payments' service. Fails for large amounts, slow for medium ones."""
import asyncio
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()


@app.post("/charge")
async def charge(request: Request):
    body = await request.json()
    amount = body.get("amount", 0)
    if amount > 1000:
        raise HTTPException(status_code=500, detail="card processor unavailable")
    if amount > 100:
        await asyncio.sleep(0.15)
    return {"ok": True, "traceparent_seen": request.headers.get("traceparent")}
