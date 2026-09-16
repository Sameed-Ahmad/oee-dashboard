"""FastAPI app: mounts the frontend static files and the /api routes on one port."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import FRONTEND_DIR

app = FastAPI(title="Fry-O Packing OEE Dashboard")

app.include_router(api_router)

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
