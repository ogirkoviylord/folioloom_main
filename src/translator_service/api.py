from pathlib import Path

from translator_service.config import Settings
from translator_service.job_store_factory import create_translation_job_store


def health_payload(settings: Settings | None = None) -> dict[str, str]:
    active_settings = settings or Settings()
    return {
        "service": active_settings.service_name,
        "status": "ok",
    }


def readiness_payload(settings: Settings | None = None) -> dict[str, str]:
    active_settings = settings or Settings()
    storage_root = Path(active_settings.object_storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)
    probe_path = storage_root / ".ready"
    probe_path.write_text("ok", encoding="utf-8")
    probe_path.unlink(missing_ok=True)

    store = create_translation_job_store(active_settings)
    store.close()

    return {
        "service": active_settings.service_name,
        "status": "ready",
        "object_storage": "ok",
        "job_store": "ok",
    }


def create_app():
    from fastapi import FastAPI

    app = FastAPI(title=Settings().service_name)

    @app.get("/health")
    def health() -> dict[str, str]:
        return health_payload()

    @app.get("/ready")
    def ready() -> dict[str, str]:
        return readiness_payload()

    return app
