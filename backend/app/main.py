"""TraceScholar API and local frontend entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.papers import router as papers_router
from app.security import DemoGuardMiddleware


def health() -> dict[str, str]:
    """Return a lightweight process health response."""

    return {"status": "ok", "service": "tracescholar-api"}


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"


def frontend_home() -> FileResponse:
    """Serve the local Chinese research workspace."""

    return FileResponse(FRONTEND_DIR / "index.html")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    application = FastAPI(
        title="TraceScholar API",
        description="可信科研助手 Agent API",
        version="0.1.0",
        docs_url="/docs" if settings.enable_api_docs else None,
        redoc_url="/redoc" if settings.enable_api_docs else None,
        openapi_url="/openapi.json" if settings.enable_api_docs else None,
    )
    application.add_middleware(DemoGuardMiddleware, settings=settings)
    application.add_api_route("/health", health, tags=["system"])
    application.include_router(papers_router)
    if ASSETS_DIR.exists():
        application.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="frontend-assets")
    application.add_api_route("/", frontend_home, include_in_schema=False)
    return application


app = create_app()
