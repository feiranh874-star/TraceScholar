"""TraceScholar API and local frontend entry point."""

from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.papers import router as papers_router
from app.research import router as research_router
from app.ocr import router as ocr_router
from app.reading import router as reading_router
from app.library_tools import router as library_router
from app.charts import router as charts_router
from app.discovery import router as discovery_router
from app.security import DemoGuardMiddleware


def health() -> dict[str, str]:
    """Return a lightweight process health response."""

    return {"status": "ok", "service": "tracescholar-api"}


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"


def frontend_home() -> FileResponse:
    """Serve the local Chinese research workspace."""

    return FileResponse(FRONTEND_DIR / "index.html")


def frontend_reader(paper_id: UUID) -> FileResponse:
    """Serve a dedicated, refreshable reading page rather than a drawer."""
    return FileResponse(FRONTEND_DIR / "reader.html")


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
    application.state.settings = settings
    application.add_middleware(DemoGuardMiddleware, settings=settings)
    application.add_api_route("/health", health, tags=["system"])
    application.include_router(papers_router)
    application.include_router(research_router)
    application.include_router(ocr_router)
    application.include_router(reading_router)
    application.include_router(library_router)
    application.include_router(charts_router)
    application.include_router(discovery_router)
    if ASSETS_DIR.exists():
        application.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="frontend-assets")
    application.add_api_route("/", frontend_home, include_in_schema=False)
    application.add_api_route("/reader/{paper_id}", frontend_reader, include_in_schema=False)
    return application


app = create_app()
