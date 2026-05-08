from translator_service.config import Settings


def health_payload(settings: Settings | None = None) -> dict[str, str]:
    active_settings = settings or Settings()
    return {
        "service": active_settings.service_name,
        "status": "ok",
    }


def create_app(settings: Settings | None = None):
    from fastapi import FastAPI

    from translator_service.admin.routes import create_admin_router

    active_settings = settings or Settings()
    app = FastAPI(title=active_settings.service_name)

    @app.get("/health")
    def health() -> dict[str, str]:
        return health_payload(active_settings)

    app.include_router(create_admin_router(active_settings))
    return app
