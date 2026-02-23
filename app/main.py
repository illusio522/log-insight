import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Union

from app.models import LogEntry, LogStats
from app.parser import error_parser
from app.storage import storage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Log Insight Parser",
    description="Python log parser service for error analysis",
    version="0.1.0",
)

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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
            parsed = error_parser.parse(log)

            # Store all logs (for now, storing everything for analysis)
            storage.insert(parsed)

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
    return storage.get_stats()


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
    limit: int = 100,
    offset: int = 0,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
):
    """Get error logs with optional filters."""
    df = storage.search_errors(
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
    total = storage.count_errors(
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
    df = storage.get_errors_by_application()
    return {"data": df.to_dict("records")}


@app.get("/errors/by-time")
async def get_errors_by_time(interval: str = "hour"):
    """Get error counts over time."""
    if interval not in ["minute", "hour", "day"]:
        raise HTTPException(status_code=400, detail="Invalid interval")
    df = storage.get_errors_by_time(interval)
    return {"data": df.to_dict("records")}


@app.delete("/logs")
async def clear_logs():
    """Clear all stored logs."""
    storage.clear()
    return {"status": "cleared"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
