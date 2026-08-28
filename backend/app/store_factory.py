from .config import Settings
from .storage import Store


def create_store(settings: Settings):
    if settings.database_backend == "supabase":
        if not settings.database_url:
            raise ValueError(
                "SUPABASE_DATABASE_URL is required when PRATIN_DATABASE_BACKEND=supabase"
            )
        from .postgres_storage import PostgresStore

        return PostgresStore(settings.database_url)
    return Store(settings.db_path)
