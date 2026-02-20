#!/usr/bin/env python3
"""Generate realistic test logs and send to Vector HTTP endpoint."""

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------------------
# Application topology
# ---------------------------------------------------------------------------

APPS = [
    {
        "application": "domain1-service",
        "domains": ["domain1"],
        "apis": [
            "/api/domain1/process",
            "/api/domain1/search",
            "/api/domain1/detail",
        ],
        "loggers": [
            "com.example.domain1.Domain1Service",
            "com.example.domain1.Domain1Controller",
            "com.example.domain1.Domain1Repository",
        ],
    },
    {
        "application": "domain2-service",
        "domains": ["domain2"],
        "apis": [
            "/api/domain2/execute",
            "/api/domain2/list",
            "/api/domain2/update",
        ],
        "loggers": [
            "com.example.domain2.Domain2Service",
            "com.example.domain2.Domain2Controller",
            "com.example.domain2.Domain2Repository",
        ],
    },
    {
        "application": "user-service",
        "domains": ["user"],
        "apis": [
            "/api/users/profile",
            "/api/users/login",
            "/api/users/register",
            "/api/users/settings",
        ],
        "loggers": [
            "com.example.user.UserService",
            "com.example.user.UserController",
            "com.example.user.AuthService",
            "com.example.user.UserRepository",
        ],
    },
]

HOSTNAMES = ["server-01", "server-02", "server-03", "server-04"]
INSTANCES_PER_HOST = ["instance1", "instance2"]
VERSIONS = ["v1", "v2"]

# ---------------------------------------------------------------------------
# Log-level distribution  (INFO 60%, WARN 25%, ERROR 15%)
# ---------------------------------------------------------------------------

LEVEL_WEIGHTS = [
    ("INFO", 20000, 60),
    ("WARN", 30000, 25),
    ("ERROR", 40000, 15),
]
LEVELS = [l for l, _, _ in LEVEL_WEIGHTS]
LEVEL_VALUES = {l: v for l, v, _ in LEVEL_WEIGHTS}
LEVEL_PROBS = [w for _, _, w in LEVEL_WEIGHTS]

# ---------------------------------------------------------------------------
# Messages per level
# ---------------------------------------------------------------------------

INFO_MESSAGES = [
    "Request processed successfully",
    "User authenticated",
    "Cache hit for key",
    "Database query completed in {ms}ms",
    "Scheduled task executed",
    "Configuration reloaded",
    "Health check passed",
    "Connection pool initialized",
    "Batch job completed: {n} records processed",
    "Session created for user",
]

WARN_MESSAGES = [
    "Slow query detected: {ms}ms",
    "Connection pool near capacity: {n}/{max}",
    "Retry attempt {n} for external service call",
    "Deprecated API version used: v1",
    "High memory usage detected: {pct}%",
    "Request rate approaching threshold",
    "Fallback method invoked for circuit breaker",
    "Session expiring soon for user",
    "Cache eviction triggered, size exceeded limit",
    "Response time exceeded SLA: {ms}ms",
]

# ---------------------------------------------------------------------------
# Error definitions with stack traces
# ---------------------------------------------------------------------------

ERROR_DEFS = [
    {
        "exception": "java.lang.NullPointerException",
        "messages": [
            "Cannot invoke method on null object",
            "null reference in parameter 'userId'",
            "Cannot read field 'id' because 'entity' is null",
        ],
        "trace": (
            "java.lang.NullPointerException: {msg}\n"
            "\tat com.example.{pkg}.{svc}.process({svc}.java:{line})\n"
            "\tat com.example.{pkg}.{ctrl}.execute({ctrl}.java:{line2})\n"
            "\tat sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)\n"
            "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)"
        ),
    },
    {
        "exception": "java.lang.RuntimeException",
        "messages": [
            "Unexpected error during processing",
            "Failed to complete transaction",
            "Internal server error",
        ],
        "caused_by": "java.lang.IllegalStateException",
        "caused_msg": "Service not in valid state",
        "trace": (
            "java.lang.RuntimeException: {msg}\n"
            "\tat com.example.{pkg}.{svc}.execute({svc}.java:{line})\n"
            "\tat com.example.{pkg}.{ctrl}.handle({ctrl}.java:{line2})\n"
            "Caused by: java.lang.IllegalStateException: Service not in valid state\n"
            "\tat com.example.{pkg}.{svc}.validate({svc}.java:{line3})"
        ),
    },
    {
        "exception": "java.net.SocketTimeoutException",
        "messages": [
            "Read timed out",
            "Connect timed out",
            "Connection refused",
        ],
        "caused_by": "java.net.SocketTimeoutException",
        "caused_msg": "Read timed out",
        "trace": (
            "java.lang.RuntimeException: Connection timeout\n"
            "\tat com.example.{pkg}.{svc}.callExternal({svc}.java:{line})\n"
            "\tat com.example.{pkg}.{ctrl}.process({ctrl}.java:{line2})\n"
            "Caused by: java.net.SocketTimeoutException: {msg}\n"
            "\tat java.net.SocketInputStream.read(SocketInputStream.java:150)\n"
            "\tat org.apache.http.impl.io.SessionInputBufferImpl.read(SessionInputBufferImpl.java:137)"
        ),
    },
    {
        "exception": "java.lang.IllegalArgumentException",
        "messages": [
            "Invalid parameter: 'status' must not be empty",
            "Argument 'amount' is out of range",
            "Invalid date format: expected ISO-8601",
        ],
        "trace": (
            "java.lang.IllegalArgumentException: {msg}\n"
            "\tat com.example.{pkg}.{svc}.validate({svc}.java:{line})\n"
            "\tat com.example.{pkg}.{ctrl}.create({ctrl}.java:{line2})\n"
            "\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)"
        ),
    },
    {
        "exception": "java.io.IOException",
        "messages": [
            "Failed to read file: /data/config.json",
            "Broken pipe",
            "Stream closed unexpectedly",
        ],
        "trace": (
            "java.io.IOException: {msg}\n"
            "\tat com.example.{pkg}.{svc}.readData({svc}.java:{line})\n"
            "\tat com.example.{pkg}.{ctrl}.upload({ctrl}.java:{line2})\n"
            "\tat java.io.FileInputStream.read(FileInputStream.java:255)"
        ),
    },
    {
        "exception": "java.lang.OutOfMemoryError",
        "messages": [
            "Java heap space",
            "GC overhead limit exceeded",
            "Direct buffer memory",
        ],
        "trace": (
            "java.lang.OutOfMemoryError: {msg}\n"
            "\tat java.util.Arrays.copyOf(Arrays.java:3210)\n"
            "\tat com.example.{pkg}.{svc}.loadBatch({svc}.java:{line})\n"
            "\tat com.example.{pkg}.{ctrl}.process({ctrl}.java:{line2})"
        ),
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

KST = timezone(timedelta(hours=9))


def _rand_hex(n: int) -> str:
    return uuid.uuid4().hex[:n]


def _fill_message(template: str) -> str:
    return (
        template.replace("{ms}", str(random.randint(100, 9000)))
        .replace("{n}", str(random.randint(1, 500)))
        .replace("{max}", str(random.randint(50, 200)))
        .replace("{pct}", str(random.randint(75, 98)))
    )


def _build_stack_trace(error_def: dict, app: dict) -> str:
    pkg = app["domains"][0]
    svc_class = app["loggers"][0].rsplit(".", 1)[-1]
    ctrl_class = app["loggers"][1].rsplit(".", 1)[-1]
    msg = random.choice(error_def["messages"])
    return error_def["trace"].format(
        msg=msg,
        pkg=pkg,
        svc=svc_class,
        ctrl=ctrl_class,
        line=random.randint(30, 200),
        line2=random.randint(20, 100),
        line3=random.randint(40, 150),
    )


def generate_log(base_time: datetime) -> dict:
    """Generate a single random log entry in Logback JSON format."""
    app = random.choice(APPS)
    level = random.choices(LEVELS, weights=LEVEL_PROBS, k=1)[0]
    hostname = random.choice(HOSTNAMES)
    instance = random.choice(INSTANCES_PER_HOST)
    thread_num = random.randint(1, 20)

    log = {
        "@timestamp": base_time.isoformat(timespec="milliseconds"),
        "@version": "1",
        "logger_name": random.choice(app["loggers"]),
        "thread_name": f"http-nio-8080-exec-{thread_num}",
        "level": level,
        "level_value": LEVEL_VALUES[level],
        "application": app["application"],
        "hostname": hostname,
        "instance": instance,
        "domain": random.choice(app["domains"]),
        "api": random.choice(app["apis"]),
        "version": random.choice(VERSIONS),
        "traceId": _rand_hex(16),
        "spanId": _rand_hex(8),
        "userId": f"user-{random.randint(1, 200):03d}",
    }

    if level == "INFO":
        log["message"] = _fill_message(random.choice(INFO_MESSAGES))
    elif level == "WARN":
        log["message"] = _fill_message(random.choice(WARN_MESSAGES))
    else:
        error_def = random.choice(ERROR_DEFS)
        log["message"] = random.choice(error_def["messages"])
        log["stack_trace"] = _build_stack_trace(error_def, app)

    return log


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate test logs for log-insight")
    parser.add_argument(
        "--count", type=int, default=100, help="Number of logs to generate (default: 100)"
    )
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8080",
        help="Vector HTTP endpoint (default: http://localhost:8080)",
    )
    args = parser.parse_args()

    url = f"{args.endpoint.rstrip('/')}/logs"
    total = args.count
    success = 0
    failed = 0

    now = datetime.now(KST)

    print(f"Sending {total} logs to {url}")

    for i in range(total):
        # Spread logs over the last hour
        offset = timedelta(seconds=random.uniform(0, 3600))
        log = generate_log(now - offset)

        try:
            resp = requests.post(url, json=log, timeout=5)
            if resp.status_code < 300:
                success += 1
            else:
                failed += 1
        except requests.RequestException:
            failed += 1

        # Progress bar
        done = i + 1
        pct = done * 100 // total
        bar = "=" * (pct // 2) + ">" + " " * (50 - pct // 2)
        sys.stdout.write(f"\r[{bar}] {pct}%  ({done}/{total})")
        sys.stdout.flush()

    print(f"\nDone: {success} sent, {failed} failed")


if __name__ == "__main__":
    main()
