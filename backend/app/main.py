"""TraceScholar API and local frontend entry point."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.papers import router as papers_router


app = FastAPI(
    title="TraceScholar API",
    description="可信科研助手 Agent API",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return a lightweight process health response."""

    return {"status": "ok", "service": "tracescholar-api"}


app.include_router(papers_router)


FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"

if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="frontend-assets")


@app.get("/", include_in_schema=False)
def frontend_home() -> FileResponse:
    """Serve the local Chinese research workspace."""

    return FileResponse(FRONTEND_DIR / "index.html")
