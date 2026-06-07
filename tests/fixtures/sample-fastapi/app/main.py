import logging

import httpx
from fastapi import FastAPI

app = FastAPI()
logger = logging.getLogger(__name__)

INVENTORY = "http://inventory.apps.internal"


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    resp = httpx.get(f"{INVENTORY}/stock/{order_id}")
    return {"order": order_id, "stock": resp.json()}


@app.post("/orders")
async def create_order(body: dict):
    httpx.post(f"{INVENTORY}/reserve", json=body)
    return {"created": True}


@app.post("/sync")
async def sync_inventory(body: dict):
    # PLANTED SWALLOW: the inventory sync failure is logged and dropped (Python try/except).
    try:
        httpx.post(f"{INVENTORY}/sync", json=body)
    except Exception:
        logger.error("inventory sync failed")
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}
