"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Grebeshok Chat",
        description="Personal AI chat backend powered by the Fireworks API.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.get("/api")
    async def api_root() -> dict[str, str]:
        return {"name": "grebeshok-chat", "version": "0.1.0"}

    _mount_static(app)

    return app


def _mount_static(app: FastAPI) -> None:
    """Serve the built frontend from ``settings.static_dir`` if present.

    When the directory does not exist (e.g. backend-only dev), expose a small
    JSON landing instead so ``GET /`` does not 404.
    """

    static_dir = Path(settings.static_dir)
    if not static_dir.exists() or not (static_dir / "index.html").exists():

        @app.get("/")
        async def root() -> JSONResponse:
            return JSONResponse(
                {
                    "name": "grebeshok-chat",
                    "version": "0.1.0",
                    "frontend": "not built — run `npm run build` in /frontend",
                    "api": "/api",
                }
            )

        return

    app.mount(
        "/assets",
        StaticFiles(directory=str(static_dir / "assets")),
        name="assets",
    )

    @app.get("/")
    async def root_index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        # Never serve the SPA for API routes — return a proper 404.
        if path.startswith("api/") or path == "api":
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # Serve actual files in the static dir when present, otherwise fall
        # back to index.html so the SPA router handles unknown routes.
        candidate = static_dir / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html")


app = create_app()
