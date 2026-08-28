import pytest

from backend.app.config import Settings
from backend.app.storage import Store
from backend.app.store_factory import create_store


def test_factory_uses_sqlite_for_offline_and_test_mode(tmp_path):
    settings = Settings(database_backend="sqlite", db_path=str(tmp_path / "fallback.db"))
    store = create_store(settings)
    assert isinstance(store, Store)
    assert store.backend == "sqlite"


def test_supabase_backend_requires_server_only_database_url():
    with pytest.raises(ValueError, match="SUPABASE_DATABASE_URL"):
        Settings(database_backend="supabase", database_url=None)


def test_committed_supabase_schema_is_private_and_lock_ready():
    migration = open(
        "supabase/migrations/20260828091405_create_pratin_marketplace.sql",
        encoding="utf-8",
    ).read().lower()
    postgres_store = open("backend/app/postgres_storage.py", encoding="utf-8").read().lower()
    assert "revoke all on schema pratin from public, anon, authenticated" in migration
    assert migration.count("enable row level security") == 4
    assert "opportunity_id text not null unique" in migration
    assert postgres_store.count("for update") >= 2
    assert "db.transaction()" in postgres_store
