import logging
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import os
from typing import Optional, Union

from app.models import LogEntry, LogStats
from app.parser import error_parser
import app.storage as storage_module

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await storage_module.init_storage()
    yield
    await storage_module.close_storage()


app = FastAPI(
    title="Log Insight Parser",
    description="Python log parser service for error analysis",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS for dashboard
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8501").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/logs")
async def receive_logs(logs: Union[list[LogEntry], LogEntry]):
    """
    Receive logs from Vector.
    Accepts both single log entry and batch of logs.
    """
    if isinstance(logs, LogEntry):
        logs = [logs]

    processed = 0
    errors_found = 0

    for log in logs:
        try:
            # Parse and analyze the log
            parsed = await error_parser.parse(log)

            # Enqueue for background writing
            await storage_module.storage.insert(parsed)

            processed += 1
            if log.level == "ERROR":
                errors_found += 1
                logger.info(
                    f"Error logged: {parsed.exception_class or 'Unknown'} "
                    f"from {log.application or 'Unknown'}"
                )
        except Exception as e:
            logger.error(f"Failed to process log: {e}")

    return {
        "status": "ok",
        "processed": processed,
        "errors_found": errors_found,
    }


@app.get("/stats", response_model=LogStats)
async def get_stats():
    """Get log statistics for dashboard."""
    return await storage_module.storage.get_stats()


@app.get("/patterns")
async def get_patterns():
    """Get discovered error patterns."""
    patterns = error_parser.get_clusters()
    return {"patterns": patterns}


@app.get("/errors")
async def get_errors(
    application: Optional[str] = None,
    domain: Optional[str] = None,
    exception_class: Optional[str] = None,
    api: Optional[str] = None,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    sort_by: str = "timestamp",
    sort_order: str = "desc",
):
    """Get error logs with optional filters."""
    df = await storage_module.storage.search_errors(
        application=application,
        domain=domain,
        exception_class=exception_class,
        api=api,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = await storage_module.storage.count_errors(
        application=application,
        domain=domain,
        exception_class=exception_class,
        api=api,
        start_time=start_time,
        end_time=end_time,
    )
    return {"errors": df.to_dict("records"), "total": total}


@app.get("/errors/by-application")
async def get_errors_by_application():
    """Get error counts grouped by application."""
    df = await storage_module.storage.get_errors_by_application()
    return {"data": df.to_dict("records")}


@app.get("/errors/by-time")
async def get_errors_by_time(interval: str = "hour"):
    """Get error counts over time."""
    if interval not in ["minute", "hour", "day"]:
        raise HTTPException(status_code=400, detail="Invalid interval")
    df = await storage_module.storage.get_errors_by_time(interval)
    return {"data": df.to_dict("records")}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
