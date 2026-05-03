from translator_service.config import Settings


def health_payload(settings: Settings | None = None) -> dict[str, str]:
    active_settings = settings or Settings()
    return {
        "service": active_settings.service_name,
        "status": "ok",
    }


def create_app():
    from fastapi import FastAPI

    app = FastAPI(title=Settings().service_name)

    @app.get("/health")
    def health() -> dict[str, str]:
        return health_payload()

    return app

