# Architecture

## System Overview

```mermaid
flowchart LR
    subgraph App Servers
        A1[Spring Boot<br>App Server 1]
        A2[Spring Boot<br>App Server 2]
        AN[Spring Boot<br>App Server N]
    end

    subgraph Docker Compose
        subgraph Vector["Vector (수집/변환)"]
            V_TCP["TCP :5001"]
            V_HTTP["HTTP :8080"]
            V_VRL["VRL Transform"]
        end

        subgraph Parser["FastAPI Parser (분석)"]
            P_API["REST API :8002"]
            P_PARSE["Drain3 패턴 마이닝"]
            P_QUEUE["Write Queue<br>(asyncio.Queue)"]
            P_WRITER["Background Writer<br>(batch flush)"]
        end

        subgraph DB["PostgreSQL 16"]
            PG[("logs table<br>pgdata volume")]
        end

        subgraph Dashboard["Streamlit Dashboard"]
            D_UI["Web UI :8501"]
            D_CHART["Plotly Charts"]
        end
    end

    subgraph Testing
        L["Locust :8089"]
    end

    A1 -- "Logback TCP" --> V_TCP
    A2 -- "Logback TCP" --> V_TCP
    AN -- "Logback TCP" --> V_TCP
    L -- "HTTP POST /logs" --> V_HTTP

    V_TCP --> V_VRL
    V_HTTP --> V_VRL
    V_VRL -- "HTTP batch<br>(50 events / 5s)" --> P_API

    P_API --> P_PARSE
    P_PARSE --> P_QUEUE
    P_QUEUE --> P_WRITER
    P_WRITER -- "batch INSERT" --> PG

    D_UI -- "GET /stats<br>/errors<br>/patterns" --> P_API
    P_API -- "SELECT" --> PG
```

## VRL (Vector Remap Language)

Vector에서 로그 데이터를 변환/가공할 때 사용하는 스크립트 언어입니다. `vector.toml`의 `transforms` 섹션에서 사용됩니다.

```toml
[transforms.enrich_logback]
type = "remap"
source = '''
.source = "logback"        # 로그 출처 표시 필드 추가
.processed_at = now()       # Vector 처리 시점 타임스탬프 추가
'''
```

필드 추가, 삭제, 변환, 조건 분기 등을 지원하며, Vector 파이프라인 내에서 로그를 정제하는 역할을 합니다.

## Data Flow

```mermaid
sequenceDiagram
    participant App as App Server
    participant Vec as Vector
    participant API as Parser API
    participant Q as Write Queue
    participant W as Background Writer
    participant DB as PostgreSQL
    participant Dash as Dashboard

    App->>Vec: Logback TCP (JSON)
    Vec->>Vec: VRL Transform (enrich)
    Vec->>API: POST /logs (batch)
    API->>API: Drain3 parse (pattern mining)
    API->>Q: enqueue (async, non-blocking)
    API-->>Vec: 200 OK (immediate)

    loop Every 0.5s or 50 items
        Q->>W: drain batch
        W->>DB: INSERT batch
    end

    Dash->>API: GET /stats, /errors
    API->>DB: SELECT (async pool)
    DB-->>API: result rows
    API-->>Dash: JSON response
```

## Port Map

| Service | Container Port | Host Port | Purpose |
|---------|---------------|-----------|---------|
| PostgreSQL | 5432 | 5432 | Database |
| Parser | 8000 | 8002 | REST API |
| Vector | 5000 | 5001 | Logback TCP |
| Vector | 8080 | 8080 | HTTP (test) |
| Vector | 8686 | 8686 | Vector API |
| Dashboard | 8501 | 8501 | Web UI |
| Locust | 8089 | 8089 | Load test UI (local) |

## Write Queue Design

```
POST /logs → parse → queue.put() → return 200
                         │
                         ▼
              ┌─────────────────────┐
              │   asyncio.Queue     │
              │   (in-memory)       │
              └────────┬────────────┘
                       │
                       ▼  every 0.5s or 50 items
              ┌─────────────────────┐
              │  Background Writer  │
              │  executemany()      │
              └────────┬────────────┘
                       │
                       ▼
              ┌─────────────────────┐
              │    PostgreSQL       │
              │    (asyncpg pool)   │
              │    min=2, max=10    │
              └─────────────────────┘
```

- POST /logs는 큐에 넣고 즉시 응답 (non-blocking)
- Writer가 0.5초 간격 또는 50건 단위로 배치 INSERT
- 프로세스 크래시 시 큐 데이터 유실 가능 (로그 분석 도구이므로 허용)
