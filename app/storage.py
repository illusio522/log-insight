import duckdb
import pandas as pd
from datetime import datetime
from typing import Optional
from pathlib import Path

from app.models import ParsedError, LogStats


class LogStorage:
    """DuckDB-based storage for parsed logs."""

    def __init__(self, db_path: str = "logs/log_insight.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        """Initialize database tables."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP,
                application VARCHAR,
                hostname VARCHAR,
                instance VARCHAR,
                domain VARCHAR,
                api VARCHAR,
                trace_id VARCHAR,
                user_id VARCHAR,
                level VARCHAR,
                message VARCHAR,
                logger_name VARCHAR,
                exception_class VARCHAR,
                exception_message VARCHAR,
                root_cause_class VARCHAR,
                root_cause_message VARCHAR,
                template_id INTEGER,
                template VARCHAR,
                stack_trace VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS logs_id_seq START 1
        """)

        # Indexes for common query patterns
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs (timestamp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_level ON logs (level)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_application ON logs (application)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_exception_class ON logs (exception_class)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_template_id ON logs (template_id)")

    def insert(self, error: ParsedError) -> None:
        """Insert a parsed error into storage."""
        self.conn.execute(
            """
            INSERT INTO logs (
                id, timestamp, application, hostname, instance, domain, api,
                trace_id, user_id, level, message, logger_name,
                exception_class, exception_message, root_cause_class, root_cause_message,
                template_id, template, stack_trace
            ) VALUES (
                nextval('logs_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """,
            [
                error.timestamp,
                error.application,
                error.hostname,
                error.instance,
                error.domain,
                error.api,
                error.traceId,
                error.userId,
                error.level,
                error.message,
                error.logger_name,
                error.exception_class,
                error.exception_message,
                error.root_cause_class,
                error.root_cause_message,
                error.template_id,
                error.template,
                error.stack_trace,
            ],
        )

    def insert_batch(self, errors: list[ParsedError]) -> None:
        """Insert multiple parsed errors."""
        if not errors:
            return
        self.conn.executemany(
            """
            INSERT INTO logs (
                id, timestamp, application, hostname, instance, domain, api,
                trace_id, user_id, level, message, logger_name,
                exception_class, exception_message, root_cause_class, root_cause_message,
                template_id, template, stack_trace
            ) VALUES (
                nextval('logs_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """,
            [
                [
                    error.timestamp,
                    error.application,
                    error.hostname,
                    error.instance,
                    error.domain,
                    error.api,
                    error.traceId,
                    error.userId,
                    error.level,
                    error.message,
                    error.logger_name,
                    error.exception_class,
                    error.exception_message,
                    error.root_cause_class,
                    error.root_cause_message,
                    error.template_id,
                    error.template,
                    error.stack_trace,
                ]
                for error in errors
            ],
        )

    def get_all_logs(self, limit: int = 1000) -> pd.DataFrame:
        """Get all logs as DataFrame."""
        limit = int(limit)
        return self.conn.execute(
            "SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", [limit]
        ).fetchdf()

    def get_errors(self, limit: int = 1000) -> pd.DataFrame:
        """Get only error logs."""
        limit = int(limit)
        return self.conn.execute(
            "SELECT * FROM logs WHERE level = 'ERROR' ORDER BY timestamp DESC LIMIT ?", [limit]
        ).fetchdf()

    def get_stats(self) -> LogStats:
        """Get statistics for dashboard."""
        stats = LogStats()

        # Total counts
        stats.total_logs = self.conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        stats.total_errors = self.conn.execute(
            "SELECT COUNT(*) FROM logs WHERE level = 'ERROR'"
        ).fetchone()[0]
        stats.unique_patterns = self.conn.execute(
            "SELECT COUNT(DISTINCT template_id) FROM logs WHERE level = 'ERROR'"
        ).fetchone()[0]

        # Top exceptions
        top_exceptions = self.conn.execute("""
            SELECT
                COALESCE(root_cause_class, exception_class, 'Unknown') as exception,
                COUNT(*) as count
            FROM logs
            WHERE level = 'ERROR'
            GROUP BY 1
            ORDER BY count DESC
            LIMIT 10
        """).fetchdf()
        stats.top_exceptions = top_exceptions.to_dict("records")

        # Top applications
        top_apps = self.conn.execute("""
            SELECT
                COALESCE(application, 'Unknown') as application,
                COUNT(*) as count
            FROM logs
            WHERE level = 'ERROR'
            GROUP BY 1
            ORDER BY count DESC
            LIMIT 10
        """).fetchdf()
        stats.top_applications = top_apps.to_dict("records")

        # Errors by hour
        errors_by_hour = self.conn.execute("""
            SELECT
                DATE_TRUNC('hour', timestamp) as hour,
                COUNT(*) as count
            FROM logs
            WHERE level = 'ERROR' AND timestamp IS NOT NULL
            GROUP BY 1
            ORDER BY hour DESC
            LIMIT 24
        """).fetchdf()
        stats.errors_by_hour = errors_by_hour.to_dict("records")

        return stats

    def get_error_patterns(self) -> pd.DataFrame:
        """Get error patterns with counts."""
        return self.conn.execute("""
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
        """).fetchdf()

    def get_errors_by_application(self) -> pd.DataFrame:
        """Get error counts by application."""
        return self.conn.execute("""
            SELECT
                COALESCE(application, 'Unknown') as application,
                COALESCE(domain, 'Unknown') as domain,
                COUNT(*) as error_count,
                COUNT(DISTINCT template_id) as unique_patterns
            FROM logs
            WHERE level = 'ERROR'
            GROUP BY application, domain
            ORDER BY error_count DESC
        """).fetchdf()

    _ALLOWED_INTERVALS = {"second", "minute", "hour", "day", "week", "month", "year"}

    def get_errors_by_time(self, interval: str = "hour") -> pd.DataFrame:
        """Get error counts by time interval."""
        if interval not in self._ALLOWED_INTERVALS:
            raise ValueError(f"Invalid interval: {interval}. Must be one of {self._ALLOWED_INTERVALS}")
        return self.conn.execute(f"""
            SELECT
                DATE_TRUNC('{interval}', timestamp) as time_bucket,
                COALESCE(application, 'Unknown') as application,
                COUNT(*) as count
            FROM logs
            WHERE level = 'ERROR' AND timestamp IS NOT NULL
            GROUP BY 1, 2
            ORDER BY time_bucket
        """).fetchdf()

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
    ) -> tuple[list[str], list]:
        """Build WHERE conditions and params for error queries."""
        conditions = ["level = 'ERROR'"]
        params = []

        if application:
            conditions.append("application = ?")
            params.append(application)
        if domain:
            conditions.append("domain = ?")
            params.append(domain)
        if api:
            conditions.append("api LIKE ?")
            params.append(api.replace("*", "%"))
        if exception_class:
            conditions.append("(exception_class LIKE ? OR root_cause_class LIKE ?)")
            params.extend([f"%{exception_class}%", f"%{exception_class}%"])
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        return conditions, params

    def search_errors(
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
        conditions, params = self._build_error_filter(
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
            LIMIT ? OFFSET ?
        """
        return self.conn.execute(query, params).fetchdf()

    def count_errors(
        self,
        application: Optional[str] = None,
        domain: Optional[str] = None,
        exception_class: Optional[str] = None,
        api: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """Count errors matching filters."""
        conditions, params = self._build_error_filter(
            application=application, domain=domain, exception_class=exception_class,
            api=api, start_time=start_time, end_time=end_time,
        )

        query = f"SELECT COUNT(*) FROM logs WHERE {' AND '.join(conditions)}"
        return self.conn.execute(query, params).fetchone()[0]

    def clear(self):
        """Clear all logs."""
        self.conn.execute("DELETE FROM logs")
        self.conn.execute("DROP SEQUENCE IF EXISTS logs_id_seq")
        self.conn.execute("CREATE SEQUENCE logs_id_seq START 1")


# Global storage instance
storage = LogStorage()
