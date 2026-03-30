# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Pre-Release Checklist

개발 완료 또는 운영 배포 요청 시, 아래 항목을 기준으로 점검을 수행한다.

### 보안
- [ ] 인증/인가: API 엔드포인트에 인증 적용 여부 (최소 API Key)
- [ ] 입력값 검증: 사용자 입력에 대한 범위/형식 제한
- [ ] SQL Injection: 동적 쿼리에 파라미터 바인딩 사용 여부
- [ ] CORS: 허용 origin, method, header가 최소 범위로 제한되어 있는지
- [ ] 비밀번호/키: 코드 및 설정 파일에 하드코딩된 credential 없는지
- [ ] 파괴적 API (DELETE 등): 보호 장치 (인증, 확인, 감사 로그) 적용 여부

### 안정성
- [ ] 에러 처리: 실패 시 재시도, 로깅, 알림이 적절한지
- [ ] 동시성: 공유 자원에 대한 race condition 보호 (Lock, 큐 등)
- [ ] Health Check: DB 등 의존 서비스 상태를 반영하는지
- [ ] Graceful Shutdown: 종료 시 진행 중 작업 완료 후 종료하는지
- [ ] 데이터 유실: 비동기 처리 시 실패한 데이터의 재처리 방안

### 성능
- [ ] DB 인덱스: 주요 쿼리 패턴에 맞는 인덱스 존재 여부
- [ ] 커넥션 풀: 적절한 크기 설정 및 환경변수화
- [ ] Rate Limiting: 과도한 요청에 대한 제한
- [ ] 부하 테스트: 예상 트래픽 기준 성능 검증 완료

### 운영
- [ ] 모니터링/알림: 메트릭 수집 및 이상 탐지 알림
- [ ] 로깅: 구조화된 로그, 요청 추적 가능 여부
- [ ] 백업/복구: DB 백업 절차 및 복구 테스트
- [ ] 설정 외부화: 하드코딩된 설정값 없이 환경변수로 관리
- [ ] DB 마이그레이션: 스키마 변경 도구 및 절차

### 코드 품질
- [ ] 문서 현행화: README, CLAUDE.md, 아키텍처 문서가 최신 상태인지
- [ ] 문서 정확성: 문서에 적힌 기술적 사실(설정값, 동작 방식, 정책명 등)이 실제 코드/설정 파일과 일치하는지 대조 검증
- [ ] 테스트: 핵심 로직에 대한 단위/통합 테스트 존재 여부
- [ ] 비정상 입력 처리: 비Java/Python 스택 트레이스 등 예외 케이스

## Project Overview

log-insight is a Python project (Python 3.11.13) for log collection, error analysis, and visualization.

## Development Environment

Activate the virtual environment before running commands:
```bash
source .venv/bin/activate
```

## Build and Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start full stack via Docker (PostgreSQL + Vector + Parser + Dashboard)
docker compose up -d

# Or start services individually (local development, requires PostgreSQL running)
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loginsight
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Start dashboard (in another terminal)
streamlit run dashboard.py --server.headless true

# Generate test logs (sends via Vector HTTP endpoint)
python scripts/generate_logs.py --count 200 --endpoint http://localhost:8080
python scripts/generate_logs.py --count 500 --endpoint http://localhost:8080 --days-ago 7

# Generate test logs (sends to parser directly, Vector bypass)
python scripts/generate_logs.py --count 200 --endpoint http://localhost:8002

# Performance testing (install locust first: pip install -r requirements-test.txt)
locust -f scripts/locustfile.py --host http://localhost:8080

# View Vector logs
docker compose logs -f vector

# Stop all services
docker compose down
```

## Architecture

- **PostgreSQL 16**: Log storage (asyncpg connection pool, batch INSERT via write queue)
  - Composite indexes on (level, timestamp) and (level, application) for dashboard query performance
- **Vector** (`vector.toml`): Log collection and transformation pipeline running in Docker
  - Sources:
    - Logback TCP socket on port 5001 (for remote logging from application servers)
    - HTTP endpoint on port 8080 (for testing via Postman/curl)
  - Transforms: Enrichment via VRL (Vector Remap Language)
  - Sinks: HTTP sink to Python parser (`python-parser:8000/logs`), console output for debugging
  - Batching: 50 events or 5 seconds, disk buffer (256MB), retry with exponential backoff
- **Python Parser** (`app/`): FastAPI service receiving logs from Vector (containerized via Dockerfile)
  - Error parsing with Drain3 for pattern mining (state persisted to `data/drain3_state.bin`)
  - Stack trace parsing: Java and Python auto-detection with language field
  - Async write queue (asyncio.Queue): POST /logs enqueues and returns immediately, background writer flushes in batches (50 items or 0.5s interval)
  - PostgreSQL storage via asyncpg (connection pool min=2, max=10)
  - REST API for dashboard queries (pagination, sorting, wildcard filtering)
  - FastAPI lifespan for async storage init/teardown
- **Dashboard** (`dashboard.py`): Streamlit dashboard for error visualization
  - Date range filter, pagination, server-side sorting
  - API path wildcard filter (`*` support)
  - Row selection for stack trace viewing
  - Language column (java/python/unknown)
  - Auto-refresh via st.fragment(run_every=60), cached API calls (60s TTL)
  - Configurable API URL via `API_URL` environment variable
- **Log Generator** (`scripts/generate_logs.py`): Test log generation script
  - Supports `--count`, `--endpoint`, `--days-ago` options
  - Generates realistic Logback JSON with diverse exceptions and stack traces
- **Locust** (`scripts/locustfile.py`): Performance testing
  - Custom Payload UI at /custom-payload for JSON input
  - Auto-generated @timestamp for custom payloads
- **Examples**: Sample configurations in `examples/` directory (e.g., `logback-spring.xml`, `postman_collection.json`)

## Docker Compose Services

| Service | Container Port | Host Port | Image |
|---------|---------------|-----------|-------|
| postgres | 5432 | 5432 | postgres:16-alpine |
| python-parser | 8000 | 8002 | Dockerfile (build) |
| vector | 5000, 8080, 8686 | 5001, 8080, 8686 | timberio/vector:0.34.1-alpine |
| dashboard | 8501 | 8501 | Dockerfile (build) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/loginsight` | PostgreSQL connection URL |
| `API_URL` | `http://localhost:8000` | Dashboard → Parser API URL |
| `CORS_ORIGINS` | `http://localhost:8501` | CORS allowed origins (comma-separated) |

## Logback JSON Format

Logs from Spring Boot applications using `logstash-logback-encoder` have this structure:

```json
{
  "@timestamp": "2026-01-22T13:45:30.123+09:00",
  "@version": "1",
  "message": "processed successfully",
  "logger_name": "com.example.domain.DomainService",
  "thread_name": "http-nio-8080-exec-1",
  "level": "INFO",
  "level_value": 20000,
  "application": "domain-service",
  "hostname": "server-01",
  "instance": "instance1",
  "domain": "domain",
  "api": "/api/domain/process",
  "version": "v1",
  "traceId": "6a3e8b2c1d4f5a6b",
  "spanId": "1a2b3c4d",
  "userId": "user-001",
  "stack_trace": "..."
}
```

**Static fields (per-instance, via JVM options):**

| Field | Description |
|-------|-------------|
| `application` | Application name (from `spring.application.name`) |
| `hostname` | Server hostname |
| `instance` | WAS instance name (e.g., instance1, instance2) |

**MDC fields (per-request, set in Filter/Interceptor):**

| Field | Description |
|-------|-------------|
| `domain` | Business domain (e.g., domain1, domain2) |
| `api` | API endpoint path |
| `version` | API version (e.g., v1, v2) |
| `traceId/spanId` | Distributed tracing context |
| `userId` | User identifier |

**Other fields:**

| Field | Description |
|-------|-------------|
| `@timestamp` | ISO 8601 timestamp with timezone |
| `level` | INFO, WARN, ERROR, DEBUG |
| `level_value` | Numeric (DEBUG=10000, INFO=20000, WARN=30000, ERROR=40000) |
| `logger_name` | Java class name |
| `thread_name` | Thread that produced the log |
| `message` | Log message |
| `stack_trace` | Exception stack trace (ERROR logs only) |

**JVM options:**
```bash
-Dinstance.name=instance1
```
