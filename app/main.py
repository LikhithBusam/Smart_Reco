from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, auth, events, products
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="SmartReco", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(products.router)
app.include_router(events.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
