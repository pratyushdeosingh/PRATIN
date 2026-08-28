import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    integration_mode: str = os.getenv("PRATIN_INTEGRATION_MODE", "auto")
    invoice_risk_url: str = os.getenv("INVOICE_RISK_URL", "http://127.0.0.1:8001")
    capital_market_url: str = os.getenv("CAPITAL_MARKET_URL", "http://127.0.0.1:8002")
    db_path: str = os.getenv("PRATIN_DB_PATH", "data/pratin.db")
    timeout: float = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "3"))

