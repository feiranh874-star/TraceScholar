"""Minimal API entry point for the TraceScholar scaffold."""

from fastapi import FastAPI


app = FastAPI(
    title="TraceScholar API",
    description="可信科研助手 Agent API",
    version="0.1.0",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return a lightweight process health response."""

    return {"status": "ok", "service": "tracescholar-api"}
