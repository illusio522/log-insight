from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class LogEntry(BaseModel):
    """Logback JSON format from Spring Boot applications."""

    # Timestamp fields
    timestamp: Optional[datetime] = Field(None, alias="@timestamp")
    version: Optional[str] = Field(None, alias="@version")

    # Core log fields
    message: str = ""
    logger_name: Optional[str] = None
    thread_name: Optional[str] = None
    level: str = "INFO"
    level_value: Optional[int] = None

    # Static fields (per-instance)
    application: Optional[str] = None
    hostname: Optional[str] = None
    instance: Optional[str] = None

    # MDC fields (per-request)
    domain: Optional[str] = None
    api: Optional[str] = None
    traceId: Optional[str] = None
    spanId: Optional[str] = None
    userId: Optional[str] = None

    # Error fields
    stack_trace: Optional[str] = None

    # Vector enrichment fields
    source: Optional[str] = None
    processed_at: Optional[datetime] = None

    class Config:
        populate_by_name = True
        extra = "allow"


class ParsedError(BaseModel):
    """Parsed and analyzed error information."""

    # Original log info
    timestamp: Optional[datetime] = None
    application: Optional[str] = None
    hostname: Optional[str] = None
    instance: Optional[str] = None
    domain: Optional[str] = None
    api: Optional[str] = None
    traceId: Optional[str] = None
    userId: Optional[str] = None
    level: str = "ERROR"
    message: str = ""
    logger_name: Optional[str] = None

    # Parsed exception info
    exception_class: Optional[str] = None
    exception_message: Optional[str] = None
    root_cause_class: Optional[str] = None
    root_cause_message: Optional[str] = None

    # Pattern analysis
    template_id: int = 0
    template: str = ""

    # Full stack trace
    stack_trace: Optional[str] = None


class LogStats(BaseModel):
    """Statistics for dashboard."""

    total_logs: int = 0
    total_errors: int = 0
    unique_patterns: int = 0
    top_exceptions: list[dict] = []
    top_applications: list[dict] = []
    errors_by_hour: list[dict] = []
