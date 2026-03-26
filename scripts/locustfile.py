"""
Locust performance test for log-insight.

Usage:
    # Web UI mode (http://localhost:8089)
    locust -f scripts/locustfile.py --host http://localhost:8080

    # Headless mode (CLI only)
    locust -f scripts/locustfile.py --host http://localhost:8080 \
        --headless -u 50 -r 10 --run-time 60s

Custom payload:
    Locust Web UI (http://localhost:8089) 의 "Custom Payload" 탭에서
    JSON을 직접 입력하면 해당 payload로 부하 테스트를 수행합니다.
    비워두면 내장 랜덤 로그 생성기를 사용합니다.
"""

import json
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request
from locust import HttpUser, between, events, task

# ---------------------------------------------------------------------------
# Custom payload store
# ---------------------------------------------------------------------------

custom_payloads = []

custom_ui = Blueprint("custom_ui", __name__)


@custom_ui.route("/custom-payload", methods=["GET"])
def custom_payload_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Custom Payload</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; }
            h2 { color: #333; }
            textarea {
                width: 100%; height: 300px; padding: 12px;
                font-family: monospace; font-size: 14px;
                border: 1px solid #ccc; border-radius: 4px;
                resize: vertical;
            }
            .btn {
                padding: 10px 24px; margin: 8px 4px; border: none;
                border-radius: 4px; cursor: pointer; font-size: 14px;
            }
            .btn-primary { background: #4CAF50; color: white; }
            .btn-danger { background: #f44336; color: white; }
            .btn-secondary { background: #888; color: white; }
            .btn:hover { opacity: 0.85; }
            .status {
                margin-top: 16px; padding: 12px;
                border-radius: 4px; display: none;
            }
            .success { background: #dff0d8; color: #3c763d; display: block; }
            .error { background: #f2dede; color: #a94442; display: block; }
            .info { background: #d9edf7; color: #31708f; }
            .current { margin-top: 16px; padding: 12px; background: #fff; border: 1px solid #ddd; border-radius: 4px; }
            .current pre { white-space: pre-wrap; word-wrap: break-word; max-height: 200px; overflow-y: auto; }
            .hint { color: #888; font-size: 13px; margin-bottom: 8px; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/" style="color:#7ece4e; font-size:13px;">&larr; Back to Locust</a>
            <h2>Custom Payload</h2>
            <p class="hint">
                JSON 객체 또는 배열을 입력하세요. 배열이면 랜덤으로 하나씩 선택하여 전송합니다.<br>
                비워두고 Clear 하면 내장 랜덤 로그 생성기를 사용합니다.
            </p>
            <textarea id="payload" placeholder='{
  "level": "ERROR",
  "message": "something failed",
  "application": "my-service",
  "stack_trace": "java.lang.NullPointerException: ..."
}

or array:

[
  {"level": "ERROR", "message": "error 1", "application": "svc-a"},
  {"level": "INFO", "message": "ok", "application": "svc-b"}
]

* @timestamp is auto-generated'></textarea>
            <div>
                <button class="btn btn-primary" onclick="setPayload()">Set Payload</button>
                <button class="btn btn-danger" onclick="clearPayload()">Clear</button>
                <button class="btn btn-secondary" onclick="loadCurrent()">Refresh Status</button>
            </div>
            <div id="status" class="status"></div>
            <div class="current">
                <strong>Current:</strong>
                <div id="current-info" class="info" style="margin-top:8px; padding:8px; border-radius:4px;">Loading...</div>
                <pre id="current-payload"></pre>
            </div>
        </div>
        <script>
            function setPayload() {
                const text = document.getElementById('payload').value.trim();
                if (!text) { showStatus('JSON을 입력하세요.', 'error'); return; }
                fetch('/custom-payload/api', {
                    method: 'POST',
                    headers: {'Content-Type': 'text/plain'},
                    body: text
                })
                .then(r => r.json())
                .then(d => { showStatus(d.message, 'success'); loadCurrent(); })
                .catch(e => showStatus('Error: ' + e, 'error'));
            }
            function clearPayload() {
                fetch('/custom-payload/api', {method: 'DELETE'})
                .then(r => r.json())
                .then(d => { showStatus(d.message, 'success'); loadCurrent(); document.getElementById('payload').value = ''; })
                .catch(e => showStatus('Error: ' + e, 'error'));
            }
            function loadCurrent() {
                fetch('/custom-payload/api')
                .then(r => r.json())
                .then(d => {
                    const info = document.getElementById('current-info');
                    const pre = document.getElementById('current-payload');
                    if (d.count > 0) {
                        info.textContent = d.count + ' payload(s) registered';
                        info.style.background = '#dff0d8';
                        pre.textContent = JSON.stringify(d.payloads, null, 2);
                    } else {
                        info.textContent = 'No custom payload. Using built-in random generator.';
                        info.style.background = '#d9edf7';
                        pre.textContent = '';
                    }
                });
            }
            function showStatus(msg, type) {
                const el = document.getElementById('status');
                el.textContent = msg;
                el.className = 'status ' + type;
            }
            loadCurrent();
        </script>
    </body>
    </html>
    """


@custom_ui.route("/custom-payload/api", methods=["GET"])
def get_payload():
    return jsonify({"count": len(custom_payloads), "payloads": custom_payloads})


@custom_ui.route("/custom-payload/api", methods=["POST"])
def set_payload():
    global custom_payloads
    raw = request.get_data(as_text=True)
    # Fix control characters inside JSON string values:
    # Real tab (0x09) -> \t, real newline -> \n (only inside strings)
    import re
    fixed = re.sub(r'(?<=")([^"]*?)(?=")', lambda m: m.group(0).replace('\t', '\\t').replace('\n', '\\n').replace('\r', ''), raw)
    try:
        data = json.loads(fixed)
    except json.JSONDecodeError as e:
        return jsonify({"message": f"Invalid JSON: {e}"}), 400
    if isinstance(data, list):
        custom_payloads = data
    else:
        custom_payloads = [data]
    return jsonify({"message": f"{len(custom_payloads)} payload(s) registered", "count": len(custom_payloads)})


@custom_ui.route("/custom-payload/api", methods=["DELETE"])
def clear_payload():
    global custom_payloads
    custom_payloads = []
    return jsonify({"message": "Cleared. Using built-in random generator.", "count": 0})


start_page_inject = Blueprint("start_page_inject", __name__)


@start_page_inject.after_app_request
def inject_payload_link(response):
    if response.content_type and "text/html" in response.content_type:
        snippet = """
<script>
(function() {
    function injectLink() {
        var forms = document.querySelectorAll('form');
        forms.forEach(function(form) {
            if (form.dataset.payloadLinked) return;
            form.dataset.payloadLinked = 'true';
            var div = document.createElement('div');
            div.style.cssText = 'text-align:center; margin-top:12px;';
            div.innerHTML = '<a href="/custom-payload" style="color:#7ece4e; font-size:14px;">Custom Payload Settings</a>';
            form.parentNode.insertBefore(div, form.nextSibling);
        });
    }
    var observer = new MutationObserver(function() { setTimeout(injectLink, 100); });
    observer.observe(document.body, {childList: true, subtree: true});
    injectLink();
})();
</script>
"""
        data = response.get_data(as_text=True)
        data = data.replace("</body>", snippet + "</body>")
        response.set_data(data)
    return response


@events.init.add_listener
def on_init(environment, **kwargs):
    environment.web_ui.app.register_blueprint(custom_ui)
    environment.web_ui.app.register_blueprint(start_page_inject)


# ---------------------------------------------------------------------------
# Built-in random log generator
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


def _get_payload() -> dict:
    """Get a payload to send: custom if set, otherwise random generated."""
    if custom_payloads:
        payload = dict(random.choice(custom_payloads))
        payload["@timestamp"] = datetime.now(KST).isoformat(timespec="milliseconds")
        return payload
    return _generate_log()


def _get_batch(size: int) -> list[dict]:
    return [_get_payload() for _ in range(size)]


# ---------------------------------------------------------------------------
# Locust user classes
# ---------------------------------------------------------------------------


class LogIngestUser(HttpUser):
    """Simulates log producers sending logs to the parser."""
    wait_time = between(0.1, 0.5)
    weight = 3

    @task(3)
    def send_single_log(self):
        self.client.post("/logs", json=_get_payload(), name="/logs [single]")

    @task(1)
    def send_batch_logs(self):
        batch = _get_batch(random.choice([10, 20, 50]))
        self.client.post("/logs", json=batch, name="/logs [batch]")


PARSER_URL = os.getenv("PARSER_URL", "http://localhost:8002")


class DashboardUser(HttpUser):
    """Simulates dashboard users querying the Parser API."""
    wait_time = between(1, 3)
    weight = 1

    def on_start(self):
        self.client.base_url = PARSER_URL

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
