from fastapi import FastAPI

from app.api import admin, auth

app = FastAPI(title="SmartReco")

app.include_router(auth.router)
app.include_router(admin.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
