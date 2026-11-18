from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Elective Capstone", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}