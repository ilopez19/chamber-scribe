from fastapi import FastAPI
from api.routes import jobs, transcripts
from shared.db.database import ping

app = FastAPI(
    title="Chamber Scribe API",
    description="Query Michigan legislative video transcripts",
    version="1.0.0",
)

app.include_router(jobs.router)
app.include_router(transcripts.router)


@app.on_event("startup")
async def startup():
    await ping()


@app.get("/")
async def root():
    return {"status": "ok", "service": "chamber-scribe"}


@app.get("/health")
async def health():
    return {"status": "ok"}