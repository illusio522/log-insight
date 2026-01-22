# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

log-insight is a Python project (Python 3.11.13). The project is currently in early development.

## Development Environment

Activate the virtual environment before running commands:
```bash
source .venv/bin/activate
```

## Build and Development Commands

```bash
# Start Vector pipeline
docker compose up -d

# View Vector logs
docker compose logs -f vector

# Stop Vector
docker compose down
```

## Architecture

- **Vector** (`vector.toml`): Log collection and transformation pipeline running in Docker
  - Sources:
    - Logback TCP socket on port 5001 (for remote logging from application servers)
    - HTTP endpoint on port 8080 (for testing via Postman/curl)
  - Transforms: Enrichment via VRL (Vector Remap Language)
  - Sinks: HTTP sink to Python parser at `localhost:8000/logs`, console output for debugging
- **Python Parser**: Custom log parser service (to be implemented) receiving logs from Vector
- **Examples**: Sample configurations in `examples/` directory (e.g., `logback-spring.xml`, `postman_collection.json`)

## Logback JSON Format

Logs from Spring Boot applications using `logstash-logback-encoder` have this structure:

```json
{
  "@timestamp": "2026-01-22T13:45:30.123+09:00",
  "@version": "1",
  "message": "User login successful",
  "logger_name": "com.example.service.UserService",
  "thread_name": "http-nio-8080-exec-1",
  "level": "INFO",
  "level_value": 20000,
  "application": "my-app",
  "environment": "local",
  "traceId": "6a3e8b2c1d4f5a6b",
  "spanId": "1a2b3c4d",
  "userId": "user-001",
  "stack_trace": "..."
}
```

| Field | Description |
|-------|-------------|
| `@timestamp` | ISO 8601 timestamp with timezone |
| `level` | INFO, WARN, ERROR, DEBUG |
| `level_value` | Numeric (DEBUG=10000, INFO=20000, WARN=30000, ERROR=40000) |
| `logger_name` | Java class name |
| `thread_name` | Thread that produced the log |
| `message` | Log message |
| `traceId/spanId` | MDC context for distributed tracing |
| `stack_trace` | Exception stack trace (ERROR logs only) |
