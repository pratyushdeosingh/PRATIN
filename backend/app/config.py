import os
from dataclasses import dataclass
from typing import Literal

IntegrationMode = Literal["required", "auto", "fixture"]

def _flag(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    integration_mode: IntegrationMode = os.getenv("PRATIN_INTEGRATION_MODE", "auto")  # type: ignore[assignment]
    invoice_risk_url: str = os.getenv("INVOICE_RISK_URL", "http://127.0.0.1:8001")
    capital_market_url: str = os.getenv("CAPITAL_MARKET_URL", "http://127.0.0.1:8002")
    db_path: str = os.getenv("PRATIN_DB_PATH", "data/pratin.db")
    database_backend: Literal["sqlite", "supabase"] = os.getenv(
        "PRATIN_DATABASE_BACKEND",
        "supabase" if os.getenv("SUPABASE_DATABASE_URL") else "sqlite",
    )  # type: ignore[assignment]
    database_url: str | None = os.getenv("SUPABASE_DATABASE_URL")
    timeout: float = float(os.getenv("SERVICE_TIMEOUT_SECONDS", "3"))
    enable_digital_twin: bool = _flag("PRATIN_ENABLE_DIGITAL_TWIN")
    enable_stress_lab: bool = _flag("PRATIN_ENABLE_STRESS_LAB")

    def __post_init__(self):
        if self.integration_mode not in {"required", "auto", "fixture"}:
            raise ValueError(
                "PRATIN_INTEGRATION_MODE must be one of: required, auto, fixture"
            )
        if self.timeout <= 0:
            raise ValueError("SERVICE_TIMEOUT_SECONDS must be greater than zero")
        if self.database_backend not in {"sqlite", "supabase"}:
            raise ValueError("PRATIN_DATABASE_BACKEND must be one of: sqlite, supabase")
        if self.database_backend == "supabase" and not self.database_url:
            raise ValueError(
                "SUPABASE_DATABASE_URL is required when PRATIN_DATABASE_BACKEND=supabase"
            )
