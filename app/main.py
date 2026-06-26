from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import admin, health, people


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Terremoto Venezuela War Room API",
    description="API to search and manage records of people found after the June 24, 2026 Venezuela earthquake.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(people.router)
app.include_router(admin.router)
