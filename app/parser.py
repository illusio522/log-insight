import os
import re
from typing import Optional
from drain3 import TemplateMiner
from drain3.file_persistence import FilePersistence
from drain3.template_miner_config import TemplateMinerConfig

from app.models import LogEntry, ParsedError

DRAIN3_STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DRAIN3_STATE_FILE = os.path.join(DRAIN3_STATE_DIR, "drain3_state.bin")


class ErrorParser:
    """Parse and analyze stack traces using Drain3 for pattern mining."""

    def __init__(self):
        # Ensure data directory exists
        os.makedirs(DRAIN3_STATE_DIR, exist_ok=True)

        # Configure Drain3 with file persistence
        config = TemplateMinerConfig()
        config.drain_sim_th = 0.4  # Similarity threshold
        config.drain_depth = 4
        config.drain_max_children = 100
        persistence = FilePersistence(DRAIN3_STATE_FILE)
        self.miner = TemplateMiner(persistence_handler=persistence, config=config)

        # Regex patterns for Java exceptions
        self.java_exception_pattern = re.compile(
            r"^([\w.$]+(?:Exception|Error|Throwable)):\s*(.*)$", re.MULTILINE
        )
        self.java_caused_by_pattern = re.compile(
            r"Caused by:\s*([\w.$]+(?:Exception|Error|Throwable)):\s*(.*?)(?:\n|\r|$)"
        )
        self.java_at_pattern = re.compile(r"^\s+at\s+([\w.$]+)\(([\w.$]+):(\d+)\)", re.MULTILINE)

        # Regex patterns for Python tracebacks
        self.python_traceback_marker = re.compile(r"^Traceback \(most recent call last\):", re.MULTILINE)
        self.python_exception_pattern = re.compile(
            r"^(\w+(?:Error|Exception|Warning|Exit|Interrupt|Failure))\s*(?::\s*(.*))?$", re.MULTILINE
        )
        self.python_file_pattern = re.compile(
            r'^\s+File "(.+?)", line (\d+), in (.+)$', re.MULTILINE
        )

    def parse(self, log: LogEntry) -> ParsedError:
        """Parse a log entry and extract error information."""
        parsed = ParsedError(
            timestamp=log.timestamp,
            application=log.application,
            hostname=log.hostname,
            instance=log.instance,
            domain=log.domain,
            api=log.api,
            traceId=log.traceId,
            userId=log.userId,
            level=log.level,
            message=log.message,
            logger_name=log.logger_name,
            stack_trace=log.stack_trace,
        )

        # Parse stack trace if present
        if log.stack_trace:
            if self.python_traceback_marker.search(log.stack_trace):
                self._parse_python_traceback(log.stack_trace, parsed)
                parsed.language = "python"
            else:
                self._parse_java_stack_trace(log.stack_trace, parsed)
                parsed.language = "java"
        elif log.level == "ERROR":
            # Try to extract exception from message
            self._parse_message(log.message, parsed)

        # Template mining for pattern grouping
        text_for_mining = self._get_mining_text(parsed)
        result = self.miner.add_log_message(text_for_mining)
        parsed.template_id = result["cluster_id"]
        parsed.template = result["template_mined"]

        return parsed

    def _parse_java_stack_trace(self, stack_trace: str, parsed: ParsedError) -> None:
        """Extract exception class and root cause from Java stack trace."""
        match = self.java_exception_pattern.search(stack_trace)
        if match:
            parsed.exception_class = match.group(1)
            parsed.exception_message = match.group(2).strip()

        caused_by_matches = self.java_caused_by_pattern.findall(stack_trace)
        if caused_by_matches:
            last_cause = caused_by_matches[-1]
            parsed.root_cause_class = last_cause[0]
            parsed.root_cause_message = last_cause[1].strip()
        else:
            parsed.root_cause_class = parsed.exception_class
            parsed.root_cause_message = parsed.exception_message

    def _parse_python_traceback(self, stack_trace: str, parsed: ParsedError) -> None:
        """Extract exception class and message from Python traceback."""
        matches = self.python_exception_pattern.findall(stack_trace)
        if matches:
            last_match = matches[-1]
            parsed.exception_class = last_match[0]
            parsed.exception_message = last_match[1].strip() if last_match[1] else ""
            parsed.root_cause_class = parsed.exception_class
            parsed.root_cause_message = parsed.exception_message

        if len(matches) > 1:
            first_match = matches[0]
            parsed.root_cause_class = first_match[0]
            parsed.root_cause_message = first_match[1].strip() if first_match[1] else ""

    def _parse_message(self, message: str, parsed: ParsedError) -> None:
        """Try to extract exception info from log message."""
        match = self.java_exception_pattern.search(message)
        if match:
            parsed.language = "java"
        else:
            match = self.python_exception_pattern.search(message)
            if match:
                parsed.language = "python"
        if match:
            parsed.exception_class = match.group(1)
            parsed.exception_message = match.group(2).strip()
            parsed.root_cause_class = parsed.exception_class
            parsed.root_cause_message = parsed.exception_message

    def _get_mining_text(self, parsed: ParsedError) -> str:
        """Generate text for template mining."""
        parts = []

        if parsed.exception_class:
            parts.append(parsed.exception_class)
        if parsed.exception_message:
            normalized = self._normalize_message(parsed.exception_message)
            parts.append(normalized)
        elif parsed.message:
            normalized = self._normalize_message(parsed.message)
            parts.append(normalized)

        return ": ".join(parts) if parts else parsed.message

    def _normalize_message(self, message: str) -> str:
        """Normalize message for better pattern matching."""
        normalized = message

        # IPs
        normalized = re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "<IP>", normalized)
        # UUIDs
        normalized = re.sub(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            "<UUID>",
            normalized,
        )
        # Numbers
        normalized = re.sub(r"\b\d+\b", "<NUM>", normalized)
        # Quoted strings
        normalized = re.sub(r"'[^']*'", "'<STR>'", normalized)
        normalized = re.sub(r'"[^"]*"', '"<STR>"', normalized)

        return normalized

    def get_clusters(self) -> list[dict]:
        """Get all discovered clusters/patterns."""
        clusters = []
        for cluster in self.miner.drain.clusters:
            clusters.append(
                {
                    "cluster_id": cluster.cluster_id,
                    "template": cluster.get_template(),
                    "count": cluster.size,
                }
            )
        return sorted(clusters, key=lambda x: x["count"], reverse=True)


# Global parser instance
error_parser = ErrorParser()
