from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import admin, auth, events, pages, products, recommendations
from app.logging_config import configure_logging
from app.services.scheduler import start_scheduler, stop_scheduler

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="SmartReco", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(products.router)
app.include_router(events.router)
app.include_router(recommendations.router)
app.include_router(pages.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
