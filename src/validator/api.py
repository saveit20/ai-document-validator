"""HTTP API."""

from fastapi import FastAPI

from validator import __version__


def create_app() -> FastAPI:
    app = FastAPI(title="AI Document Validator", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app
