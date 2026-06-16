from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.dependencies import init_app_state
from .api.routes import instruments_router, visa_router, validate_router, sweep_router

logger = logging.getLogger("instr_core.api")

# Compatibility hook for tests and callers that monkeypatch
# ``instr_core.api_server.pyvisa``.  The runtime still imports PyVISA lazily in
# ``api.services.visa_service`` so the API server can start without PyVISA.
pyvisa: Any | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_app_state(app)
    yield
    logger.info("API server shutting down")


def create_api_app() -> FastAPI:
    app = FastAPI(
        title="instr-core API",
        description="HTTP API for instrument control and validation",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:1420", "tauri://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, object]:
        """Return API health information for the desktop UI."""
        registry = getattr(app.state, "registry", None)
        pyvisa_available = True
        try:
            from .api.services.visa_service import import_pyvisa

            import_pyvisa()
        except Exception:
            pyvisa_available = False

        return {
            "status": "ok",
            "registry_count": len(registry) if registry is not None else 0,
            "pyvisa_available": pyvisa_available,
        }

    app.include_router(instruments_router)
    app.include_router(visa_router)
    app.include_router(validate_router)
    app.include_router(sweep_router)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )
    app = create_api_app()
    port = int(os.environ.get("INSTR_CORE_API_PORT", "8765"))
    logger.info("Starting instr-core API server on http://localhost:%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
