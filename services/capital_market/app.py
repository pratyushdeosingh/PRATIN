from fastapi import FastAPI
from contracts.models import MarketRequest, MarketResponse
from .engine import generate_market

app = FastAPI(title="PRATIN Capital Market Agents", version="1.0.0")

@app.get("/health")
def health(): return {"status": "ok", "service": "capital-market", "version": "1.0.0"}

@app.post("/offers", response_model=MarketResponse)
def offers(request: MarketRequest): return generate_market(request)

