"""FastAPI app: mounts the frontend static files and the /api routes on one port."""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import FRONTEND_DIR

app = FastAPI(title="Shahi Enterprises OEE Dashboard")

app.include_router(api_router)


class NoCacheStaticFiles(StaticFiles):
    """This app is actively edited during local development, and the
    frontend has no build step / versioned filenames -- browsers can end up
    with a stale index.html paired with fresh JS (or vice versa), which
    throws confusing "element not found" errors. Disable caching on the
    frontend entirely rather than rely on every future user remembering to
    hard-refresh."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount("/", NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
