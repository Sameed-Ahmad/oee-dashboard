"""FastAPI app: mounts the frontend static files and the /api routes on one port."""
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .api.routes import rebuild_all_products_in_background
from .api.routes import router as api_router
from .config import FRONTEND_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Re-parse every raw workbook fresh on launch, rather than trusting
    # whatever JSON cache is left over from a previous run -- but on a
    # background thread, NOT awaited here, so the server starts answering
    # requests immediately instead of blocking for however long a full
    # sweep takes (tens of seconds; the largest single workbook alone can
    # take ~18s). See rebuild_all_products_in_background's docstring for
    # how each product's fresh data becomes visible the moment its own
    # parse finishes.
    threading.Thread(target=rebuild_all_products_in_background, daemon=True).start()
    yield


app = FastAPI(title="Shahi Enterprises OEE Dashboard", lifespan=lifespan)

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
