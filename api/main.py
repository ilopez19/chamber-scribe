# ═══════════════════════════════════════════════════════════════════════
# PIPELINE STAGE — API (reads what the other 3 stages produced)
#   Reads:        MongoDB "jobs", "transcripts", "tasks", "health" collections
#   Writes:       nothing — read-only over HTTP
#   Started by:   uvicorn api.main:app --reload  (separate process from
#                 main.py — never talks to the pipeline loops directly,
#                 only through MongoDB, including /health's heartbeat reads)
#   Diagram:      design.svg
# ═══════════════════════════════════════════════════════════════════════
# FastAPI app — see routes/ for one file per resource (jobs, transcripts, tasks, health).

from fastapi import FastAPI
from api.routes import jobs, transcripts, tasks, health
from shared.db.database import ping

app = FastAPI(
    title="Chamber Scribe API",
    description="Query Michigan legislative video transcripts",
    version="1.0.0",
)

app.include_router(jobs.router)
app.include_router(transcripts.router)
app.include_router(tasks.router)
app.include_router(health.router)


@app.on_event("startup")
async def startup():
    await ping()


# Bare liveness check for the API process itself — always 200 as long as
# the API is up, regardless of pipeline/Mongo state. See /health for the
# real check across the whole system. Returns e.g. {"status": "ok", "service": "chamber-scribe"}.
@app.get("/", summary="Service info")
async def root():
    return {"status": "ok", "service": "chamber-scribe"}
