"""
Locust performance test for log-insight.

Usage:
    # Web UI mode (http://localhost:8089)
    locust -f scripts/locustfile.py --host http://localhost:8000

    # Headless mode (CLI only)
    locust -f scripts/locustfile.py --host http://localhost:8000 \
        --headless -u 50 -r 10 --run-time 60s
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from locust import HttpUser, between, task

# ---------------------------------------------------------------------------
# Reuse log generation logic from generate_logs.py
# ---------------------------------------------------------------------------

APPS = [
    {
        "application": "domain1-service",
        "domains": ["domain1"],
        "apis": ["/api/domain1/process", "/api/domain1/search", "/api/domain1/detail"],
        "loggers": [
            "com.example.domain1.Domain1Service",
            "com.example.domain1.Domain1Controller",
        ],
    },
    {
        "application": "domain2-service",
        "domains": ["domain2"],
        "apis": ["/api/domain2/execute", "/api/domain2/list", "/api/domain2/update"],
        "loggers": [
            "com.example.domain2.Domain2Service",
            "com.example.domain2.Domain2Controller",
        ],
    },
    {
        "application": "user-service",
        "domains": ["user"],
        "apis": ["/api/users/profile", "/api/users/login", "/api/users/register"],
        "loggers": [
            "com.example.user.UserService",
            "com.example.user.UserController",
        ],
    },
]

HOSTNAMES = ["server-01", "server-02", "server-03", "server-04"]
VERSIONS = ["v1", "v2"]
KST = timezone(timedelta(hours=9))

ERROR_TRACES = [
    {
        "exception": "java.lang.NullPointerException",
        "message": "Cannot invoke method on null object",
        "trace": (
            "java.lang.NullPointerException: Cannot invoke method on null object\n"
            "\tat com.example.{pkg}.{svc}.process({svc}.java:{line})\n"
            "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)"
        ),
    },
    {
        "exception": "java.net.SocketTimeoutException",
        "message": "Read timed out",
        "trace": (
            "java.lang.RuntimeException: Connection timeout\n"
            "\tat com.example.{pkg}.{svc}.callExternal({svc}.java:{line})\n"
            "Caused by: java.net.SocketTimeoutException: Read timed out\n"
            "\tat java.net.SocketInputStream.read(SocketInputStream.java:150)"
        ),
    },
    {
        "exception": "java.lang.IllegalArgumentException",
        "message": "Invalid parameter: 'status' must not be empty",
        "trace": (
            "java.lang.IllegalArgumentException: Invalid parameter: 'status' must not be empty\n"
            "\tat com.example.{pkg}.{svc}.validate({svc}.java:{line})\n"
            "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)"
        ),
    },
]

PYTHON_ERROR_TRACES = [
    {
        "exception": "ValueError",
        "message": "invalid literal for int()",
        "trace": (
            "Traceback (most recent call last):\n"
            '  File "app.py", line {line}, in process\n'
            "    result = int(value)\n"
            "ValueError: invalid literal for int() with base 10: 'abc'"
        ),
    },
    {
        "exception": "KeyError",
        "message": "'user_id'",
        "trace": (
            "Traceback (most recent call last):\n"
            '  File "handler.py", line {line}, in handle\n'
            "    uid = data['user_id']\n"
            "KeyError: 'user_id'"
        ),
    },
]


def _generate_log() -> dict:
    app = random.choice(APPS)
    level = random.choices(["INFO", "WARN", "ERROR"], weights=[60, 25, 15], k=1)[0]
    now = datetime.now(KST)

    log = {
        "@timestamp": now.isoformat(timespec="milliseconds"),
        "@version": "1",
        "logger_name": random.choice(app["loggers"]),
        "thread_name": f"http-nio-8080-exec-{random.randint(1, 20)}",
        "level": level,
        "level_value": {"INFO": 20000, "WARN": 30000, "ERROR": 40000}[level],
        "application": app["application"],
        "hostname": random.choice(HOSTNAMES),
        "instance": f"instance{random.randint(1, 2)}",
        "domain": random.choice(app["domains"]),
        "api": random.choice(app["apis"]),
        "version": random.choice(VERSIONS),
        "traceId": uuid.uuid4().hex[:16],
        "spanId": uuid.uuid4().hex[:8],
        "userId": f"user-{random.randint(1, 200):03d}",
    }

    if level == "INFO":
        log["message"] = random.choice([
            "Request processed successfully",
            "Database query completed",
            "Cache hit for key",
            "Health check passed",
        ])
    elif level == "WARN":
        log["message"] = random.choice([
            "Slow query detected: 3200ms",
            "Retry attempt 2 for external service call",
            "High memory usage detected: 87%",
        ])
    else:
        error = random.choice(ERROR_TRACES + PYTHON_ERROR_TRACES)
        log["message"] = error["message"]
        pkg = app["domains"][0]
        svc = app["loggers"][0].rsplit(".", 1)[-1]
        log["stack_trace"] = error["trace"].format(
            pkg=pkg, svc=svc, line=random.randint(30, 200),
        )

    return log


def _generate_batch(size: int) -> list[dict]:
    return [_generate_log() for _ in range(size)]


# ---------------------------------------------------------------------------
# Locust user classes
# ---------------------------------------------------------------------------


class LogIngestUser(HttpUser):
    """Simulates log producers sending logs to the parser."""
    wait_time = between(0.1, 0.5)
    weight = 3

    @task(3)
    def send_single_log(self):
        self.client.post("/logs", json=_generate_log(), name="/logs [single]")

    @task(1)
    def send_batch_logs(self):
        batch = _generate_batch(random.choice([10, 20, 50]))
        self.client.post("/logs", json=batch, name=f"/logs [batch]")


class DashboardUser(HttpUser):
    """Simulates dashboard users querying the API."""
    wait_time = between(1, 3)
    weight = 1

    @task(3)
    def get_stats(self):
        self.client.get("/stats")

    @task(2)
    def get_errors(self):
        params = {
            "limit": 20,
            "offset": 0,
            "sort_by": "timestamp",
            "sort_order": "desc",
        }
        app = random.choice(APPS)
        if random.random() > 0.5:
            params["application"] = app["application"]
        self.client.get("/errors", params=params)

    @task(1)
    def get_errors_by_time(self):
        interval = random.choice(["hour", "day", "minute"])
        self.client.get("/errors/by-time", params={"interval": interval})

    @task(1)
    def get_errors_by_application(self):
        self.client.get("/errors/by-application")

    @task(1)
    def get_patterns(self):
        self.client.get("/patterns")
