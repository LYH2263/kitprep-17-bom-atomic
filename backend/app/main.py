from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


def _ensure_schema() -> None:
    """轻量迁移：老库补齐新增列并把已有备料单钉为当前有效。"""
    inspector = inspect(engine)
    if "prep_runs" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("prep_runs")}
        if "status" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE prep_runs ADD COLUMN status VARCHAR(16) DEFAULT 'active'"))
                conn.execute(text("UPDATE prep_runs SET status = 'active' WHERE status IS NULL"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_schema()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="KitPrep", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
