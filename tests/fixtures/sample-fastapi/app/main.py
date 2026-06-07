import httpx
from fastapi import FastAPI

app = FastAPI()

INVENTORY = "http://inventory.apps.internal"


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    resp = httpx.get(f"{INVENTORY}/stock/{order_id}")
    return {"order": order_id, "stock": resp.json()}


@app.post("/orders")
async def create_order(body: dict):
    httpx.post(f"{INVENTORY}/reserve", json=body)
    return {"created": True}


@app.get("/health")
def health():
    return {"status": "ok"}
