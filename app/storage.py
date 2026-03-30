import asyncio
import asyncpg
import logging
import os
import pandas as pd
from datetime import datetime
from typing import Optional

from app.models import ParsedError, LogStats

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/loginsight",
)

QUEUE_BATCH_SIZE = 50
QUEUE_FLUSH_INTERVAL = 0.5  # seconds
FLUSH_MAX_RETRIES = 3
FLUSH_RETRY_BASE_DELAY = 1.0  # seconds


class LogStorage:
    """PostgreSQL-based storage for parsed logs with async write queue."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self._queue: asyncio.Queue[ParsedError] = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None

    async def start(self):
        """Initialize tables and start background writer."""
        await self._init_tables()
        self._writer_task = asyncio.create_task(self._background_writer())

    async def stop(self):
        """Flush remaining queue items and stop."""
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        await self._flush_queue()

    async def _init_tables(self):
        """Initialize database tables."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ,
                    application VARCHAR,
                    hostname VARCHAR,
                    instance VARCHAR,
                    domain VARCHAR,
                    api VARCHAR,
                    trace_id VARCHAR,
                    user_id VARCHAR,
                    level VARCHAR,
                    message TEXT,
                    logger_name VARCHAR,
                    exception_class VARCHAR,
                    exception_message TEXT,
                    root_cause_class VARCHAR,
                    root_cause_message TEXT,
                    template_id INTEGER,
                    template TEXT,
                    language VARCHAR DEFAULT 'unknown',
                    stack_trace TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs (timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs (level)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_application ON logs (application)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_exception_class ON logs (exception_class)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_template_id ON logs (template_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_language ON logs (language)")
            # Composite indexes for common dashboard queries
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level_timestamp ON logs (level, timestamp DESC)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level_application ON logs (level, application)")

    # ------------------------------------------------------------------
    # Background writer
    # ------------------------------------------------------------------

    async def _background_writer(self):
        """Drains the queue in batches."""
        while True:
            batch = []
            try:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=QUEUE_FLUSH_INTERVAL
                )
                batch.append(item)
                while len(batch) < QUEUE_BATCH_SIZE:
                    try:
                        item = self._queue.get_nowait()
                        batch.append(item)
                    except asyncio.QueueEmpty:
                        break
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise

            if batch:
                await self._flush_batch(batch)

    async def _flush_batch(self, batch: list[ParsedError]):
        """Write a batch to PostgreSQL with retry."""
        for attempt in range(FLUSH_MAX_RETRIES):
            try:
                async with self.pool.acquire() as conn:
                    await conn.executemany(
                        """INSERT INTO logs (
                            timestamp, application, hostname, instance, domain, api,
                            trace_id, user_id, level, message, logger_name,
                            exception_class, exception_message, root_cause_class,
                            root_cause_message, template_id, template, language, stack_trace
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                            $12, $13, $14, $15, $16, $17, $18, $19
                        )""",
                        [self._error_to_tuple(e) for e in batch],
                    )
                return
            except Exception as e:
                delay = FLUSH_RETRY_BASE_DELAY * (2 ** attempt)
                if attempt < FLUSH_MAX_RETRIES - 1:
                    logger.warning(
                        f"Failed to write batch ({len(batch)} items), "
                        f"retry {attempt + 1}/{FLUSH_MAX_RETRIES} in {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Failed to write batch ({len(batch)} items) "
                        f"after {FLUSH_MAX_RETRIES} retries, dropping: {e}"
                    )

    async def _flush_queue(self):
        """Flush all remaining items in the queue."""
        batch = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._flush_batch(batch)

    @staticmethod
    def _error_to_tuple(error: ParsedError) -> tuple:
        return (
            error.timestamp, error.application, error.hostname,
            error.instance, error.domain, error.api, error.traceId,
            error.userId, error.level, error.message, error.logger_name,
            error.exception_class, error.exception_message,
            error.root_cause_class, error.root_cause_message,
            error.template_id, error.template, error.language, error.stack_trace,
        )

    # ------------------------------------------------------------------
    # Write methods
    # ------------------------------------------------------------------

    async def insert(self, error: ParsedError) -> None:
        """Enqueue for background writing. Returns immediately."""
        await self._queue.put(error)

    async def insert_batch(self, errors: list[ParsedError]) -> None:
        """Enqueue multiple items."""
        for error in errors:
            await self._queue.put(error)

    # ------------------------------------------------------------------
    # Read methods
    # ------------------------------------------------------------------

    async def get_all_logs(self, limit: int = 1000) -> pd.DataFrame:
        """Get all logs as DataFrame."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM logs ORDER BY timestamp DESC LIMIT $1", limit
            )
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    async def get_errors(self, limit: int = 1000) -> pd.DataFrame:
        """Get only error logs."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM logs WHERE level = 'ERROR' ORDER BY timestamp DESC LIMIT $1",
                limit,
            )
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    async def get_stats(self) -> LogStats:
        """Get statistics for dashboard."""
        stats = LogStats()

        async with self.pool.acquire() as conn:
            stats.total_logs = await conn.fetchval("SELECT COUNT(*) FROM logs")
            stats.total_errors = await conn.fetchval(
                "SELECT COUNT(*) FROM logs WHERE level = 'ERROR'"
            )
            stats.unique_patterns = await conn.fetchval(
                "SELECT COUNT(DISTINCT template_id) FROM logs WHERE level = 'ERROR'"
            )

            rows = await conn.fetch("""
                SELECT
                    COALESCE(root_cause_class, exception_class, 'Unknown') as exception,
                    COUNT(*) as count
                FROM logs
                WHERE level = 'ERROR'
                GROUP BY 1
                ORDER BY count DESC
                LIMIT 10
            """)
            stats.top_exceptions = [dict(r) for r in rows]

            rows = await conn.fetch("""
                SELECT
                    COALESCE(application, 'Unknown') as application,
                    COUNT(*) as count
                FROM logs
                WHERE level = 'ERROR'
                GROUP BY 1
                ORDER BY count DESC
                LIMIT 10
            """)
            stats.top_applications = [dict(r) for r in rows]

            rows = await conn.fetch("""
                SELECT
                    DATE_TRUNC('hour', timestamp) as hour,
                    COUNT(*) as count
                FROM logs
                WHERE level = 'ERROR' AND timestamp IS NOT NULL
                GROUP BY 1
                ORDER BY hour DESC
                LIMIT 24
            """)
            stats.errors_by_hour = [dict(r) for r in rows]

        return stats

    async def get_error_patterns(self) -> pd.DataFrame:
        """Get error patterns with counts."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    template_id,
                    template,
                    COALESCE(root_cause_class, exception_class) as exception_class,
                    COUNT(*) as count,
                    MAX(timestamp) as last_seen,
                    MIN(timestamp) as first_seen
                FROM logs
                WHERE level = 'ERROR'
                GROUP BY template_id, template, COALESCE(root_cause_class, exception_class)
                ORDER BY count DESC
            """)
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    async def get_errors_by_application(self) -> pd.DataFrame:
        """Get error counts by application."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    COALESCE(application, 'Unknown') as application,
                    COALESCE(domain, 'Unknown') as domain,
                    COUNT(*) as error_count,
                    COUNT(DISTINCT template_id) as unique_patterns
                FROM logs
                WHERE level = 'ERROR'
                GROUP BY application, domain
                ORDER BY error_count DESC
            """)
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    _ALLOWED_INTERVALS = {"second", "minute", "hour", "day", "week", "month", "year"}

    async def get_errors_by_time(self, interval: str = "hour") -> pd.DataFrame:
        """Get error counts by time interval."""
        if interval not in self._ALLOWED_INTERVALS:
            raise ValueError(f"Invalid interval: {interval}. Must be one of {self._ALLOWED_INTERVALS}")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT
                    DATE_TRUNC('{interval}', timestamp) as time_bucket,
                    COALESCE(application, 'Unknown') as application,
                    COUNT(*) as count
                FROM logs
                WHERE level = 'ERROR' AND timestamp IS NOT NULL
                GROUP BY 1, 2
                ORDER BY time_bucket
            """)
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    # ------------------------------------------------------------------
    # Filtered queries
    # ------------------------------------------------------------------

    _ALLOWED_SORT_COLUMNS = {"timestamp", "application", "exception_class", "level"}
    _ALLOWED_SORT_ORDERS = {"asc", "desc"}

    def _build_error_filter(
        self,
        application: Optional[str] = None,
        domain: Optional[str] = None,
        exception_class: Optional[str] = None,
        api: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        start_idx: int = 1,
    ) -> tuple[list[str], list, int]:
        """Build WHERE conditions and params for error queries."""
        conditions = ["level = 'ERROR'"]
        params = []
        idx = start_idx

        if application:
            conditions.append(f"application = ${idx}")
            params.append(application)
            idx += 1
        if domain:
            conditions.append(f"domain = ${idx}")
            params.append(domain)
            idx += 1
        if api:
            conditions.append(f"api LIKE ${idx}")
            params.append(api.replace("*", "%"))
            idx += 1
        if exception_class:
            conditions.append(f"(exception_class LIKE ${idx} OR root_cause_class LIKE ${idx + 1})")
            params.extend([f"%{exception_class}%", f"%{exception_class}%"])
            idx += 2
        if start_time:
            conditions.append(f"timestamp >= ${idx}")
            params.append(start_time)
            idx += 1
        if end_time:
            conditions.append(f"timestamp <= ${idx}")
            params.append(end_time)
            idx += 1

        return conditions, params, idx

    async def search_errors(
        self,
        application: Optional[str] = None,
        domain: Optional[str] = None,
        exception_class: Optional[str] = None,
        api: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
        sort_by: str = "timestamp",
        sort_order: str = "desc",
    ) -> pd.DataFrame:
        """Search errors with filters."""
        conditions, params, idx = self._build_error_filter(
            application=application, domain=domain, exception_class=exception_class,
            api=api, start_time=start_time, end_time=end_time,
        )

        if sort_by not in self._ALLOWED_SORT_COLUMNS:
            sort_by = "timestamp"
        if sort_order.lower() not in self._ALLOWED_SORT_ORDERS:
            sort_order = "desc"

        limit = int(limit)
        offset = int(offset)
        params.extend([limit, offset])
        query = f"""
            SELECT * FROM logs
            WHERE {' AND '.join(conditions)}
            ORDER BY {sort_by} {sort_order.upper()}
            LIMIT ${idx} OFFSET ${idx + 1}
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            if not rows:
                return pd.DataFrame()
            return pd.DataFrame([dict(r) for r in rows])

    async def count_errors(
        self,
        application: Optional[str] = None,
        domain: Optional[str] = None,
        exception_class: Optional[str] = None,
        api: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """Count errors matching filters."""
        conditions, params, _ = self._build_error_filter(
            application=application, domain=domain, exception_class=exception_class,
            api=api, start_time=start_time, end_time=end_time,
        )

        query = f"SELECT COUNT(*) FROM logs WHERE {' AND '.join(conditions)}"
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *params)

    async def clear(self):
        """Clear all logs."""
        async with self.pool.acquire() as conn:
            await conn.execute("TRUNCATE logs RESTART IDENTITY")


# ------------------------------------------------------------------
# Module-level initialization
# ------------------------------------------------------------------

storage: Optional[LogStorage] = None


async def init_storage() -> LogStorage:
    global storage
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    storage = LogStorage(pool)
    await storage.start()
    return storage


async def close_storage():
    global storage
    if storage:
        await storage.stop()
        await storage.pool.close()
        storage = None
