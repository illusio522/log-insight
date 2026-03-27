# log-insight

Spring Boot Logback 및 Python 애플리케이션의 로그를 수집, 분석, 시각화하는 파이프라인입니다.

## Architecture

```
[Application Servers]          [Vector]              [Python Parser]         [Dashboard]
 Logback TCP (5001)  ────>  수집 / 변환  ────>  파싱 / 쓰기 큐 / API  <───  Streamlit
 HTTP (8080)         ────>  VRL Enrichment     Drain3 패턴 마이닝          Plotly 차트
                                                      │
                                                      ▼
                                               [PostgreSQL 16]
```

| 컴포넌트 | 기술 | 설명 |
|----------|------|------|
| **Vector** | Vector 0.34.1 | TCP/HTTP 소스로 로그 수집, VRL 변환, HTTP sink으로 배치 전송 |
| **Parser** | FastAPI + Drain3 + asyncpg | 스택 트레이스 파싱 (Java/Python), 에러 패턴 마이닝, 비동기 쓰기 큐 |
| **PostgreSQL** | PostgreSQL 16 | 로그 저장 (asyncpg 커넥션 풀, 배치 INSERT) |
| **Dashboard** | Streamlit + Plotly | 메트릭, 차트, 에러 테이블 (필터, 페이지네이션, 스택 트레이스 뷰) |

상세 아키텍처 다이어그램은 [docs/architecture.md](docs/architecture.md)를 참고하세요.

## Requirements

- Python 3.11+
- Docker & Docker Compose

## Quick Start

### 1. 가상환경 설정

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Docker Compose로 전체 스택 실행

```bash
docker compose up -d
```

PostgreSQL + Vector + Parser + Dashboard 컨테이너가 함께 실행됩니다.

### 3. 대시보드 접속

http://localhost:8501 에서 대시보드를 확인할 수 있습니다.

### 4. 테스트 로그 생성

```bash
# Vector HTTP endpoint로 200건 전송
python scripts/generate_logs.py --count 200 --endpoint http://localhost:8080

# 7일간의 로그 500건 전송
python scripts/generate_logs.py --count 500 --endpoint http://localhost:8080 --days-ago 7

# Parser에 직접 전송 (Vector 우회)
python scripts/generate_logs.py --count 200 --endpoint http://localhost:8002
```

## Local Development (Docker 없이)

PostgreSQL이 별도로 실행 중이어야 합니다.

```bash
# 환경변수 설정
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/loginsight

# Parser 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Dashboard 실행 (별도 터미널)
streamlit run dashboard.py --server.headless true
```

## Environment Variables

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/loginsight` | PostgreSQL 연결 URL |
| `API_URL` | `http://localhost:8000` | Dashboard에서 Parser API에 접근하는 URL |
| `CORS_ORIGINS` | `http://localhost:8501` | CORS 허용 origin (쉼표 구분) |

`.env.example`을 `.env`로 복사하여 사용합니다.

## Port Map

| Service | Host Port | Description |
|---------|-----------|-------------|
| PostgreSQL | 5432 | Database |
| Parser | 8002 | REST API |
| Vector | 5001 | Logback TCP |
| Vector | 8080 | HTTP (test) |
| Vector | 8686 | Vector API |
| Dashboard | 8501 | Web UI |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/logs` | 로그 수신 (단건 또는 배치) → 쓰기 큐에 넣고 즉시 응답 |
| `GET` | `/health` | 헬스 체크 |
| `GET` | `/stats` | 로그 통계 (전체/에러 건수, Top 예외, Top 앱) |
| `GET` | `/errors` | 에러 로그 조회 (필터, 페이지네이션, 정렬) |
| `GET` | `/errors/by-application` | 앱별 에러 건수 |
| `GET` | `/errors/by-time` | 시간대별 에러 건수 (interval: minute/hour/day) |
| `GET` | `/patterns` | Drain3 에러 패턴 목록 |
| `DELETE` | `/logs` | 전체 로그 삭제 |

## Stack Trace Parsing

Java와 Python 스택 트레이스를 자동으로 판별하여 파싱하고, `language` 필드에 언어를 기록합니다.

**Java:**
```
java.lang.NullPointerException: Cannot invoke method on null
    at com.example.Service.process(Service.java:42)
Caused by: java.lang.IllegalStateException: invalid state
    at com.example.Service.validate(Service.java:80)
```
- `exception_class`: `NullPointerException`
- `root_cause_class`: `IllegalStateException` (마지막 Caused by)
- `language`: `java`

**Python:**
```
Traceback (most recent call last):
  File "app.py", line 42, in process
    result = int(value)
ValueError: invalid literal for int() with base 10: 'abc'
```
- `exception_class`: `ValueError`
- `root_cause_class`: `ValueError`
- `language`: `python`

## Logback JSON Format

Spring Boot 애플리케이션에서 `logstash-logback-encoder`를 사용하여 아래 형식의 JSON을 전송합니다.

```json
{
  "@timestamp": "2026-01-22T13:45:30.123+09:00",
  "level": "ERROR",
  "message": "processed successfully",
  "logger_name": "com.example.domain.DomainService",
  "application": "domain-service",
  "hostname": "server-01",
  "instance": "instance1",
  "domain": "domain",
  "api": "/api/domain/process",
  "traceId": "6a3e8b2c1d4f5a6b",
  "userId": "user-001",
  "stack_trace": "..."
}
```

필드 상세 정보는 [CLAUDE.md](CLAUDE.md)를 참고하세요.

## Performance Testing

[Locust](https://locust.io/)를 사용하여 부하 테스트를 수행할 수 있습니다.

```bash
# 의존성 설치
pip install -r requirements-test.txt

# Web UI 모드 (http://localhost:8089)
locust -f scripts/locustfile.py --host http://localhost:8080

# Headless 모드
locust -f scripts/locustfile.py --host http://localhost:8080 \
    --headless -u 50 -r 10 --run-time 60s
```

- Custom Payload: http://localhost:8089/custom-payload 에서 JSON을 직접 입력하여 테스트 가능
- `@timestamp`는 자동 생성됨

## Project Structure

```
log-insight/
├── app/
│   ├── main.py          # FastAPI 엔드포인트 + lifespan (DB 초기화)
│   ├── models.py         # Pydantic 모델 (LogEntry, ParsedError, LogStats)
│   ├── parser.py         # 스택 트레이스 파서 (Java/Python) + Drain3 패턴 마이닝
│   └── storage.py        # PostgreSQL 스토리지 (asyncpg + 쓰기 큐)
├── scripts/
│   ├── generate_logs.py  # 테스트 로그 생성기
│   └── locustfile.py     # 성능 테스트 + Custom Payload UI
├── docs/
│   └── architecture.md   # 아키텍처 다이어그램 (Mermaid)
├── examples/
│   ├── logback-spring.xml       # Logback 설정 예시
│   └── postman_collection.json  # Postman 컬렉션
├── dashboard.py          # Streamlit 대시보드
├── vector.toml           # Vector 설정
├── docker-compose.yml    # PostgreSQL + Vector + Parser + Dashboard
├── Dockerfile
├── requirements.txt
└── requirements-test.txt # locust (테스트용)
```
