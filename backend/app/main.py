from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db, sessions
from .config import CORS_ORIGINS
from .routers import geo, recommend, schools, sessions as sessions_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.con = db.connect()
    app.state.sessions = sessions.connect()
    yield
    app.state.sessions.close()
    app.state.con.close()


app = FastAPI(title="SchoolMatch Miami API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(schools.router)
app.include_router(geo.router)
app.include_router(recommend.router)
app.include_router(sessions_router.router)


@app.get("/api/health")
def health():
    con = app.state.con
    n = con.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
    return {"ok": True, "schools": n}
