"""Load test (spec phase 8 f): 10 clients upload 30 documents within 10 seconds.

1. python -m tests.load.setup_load          # creates load0..load9 clients with 3 credits each
2. locust -f tests/load/locustfile.py --headless -u 10 -r 10 -t 20s --host http://127.0.0.1:8001
3. python -m tests.load.verify_load         # waits for all checks, then checks charges and balances
"""

from __future__ import annotations

import io
import itertools
import threading
import uuid

from locust import HttpUser, between, task
from locust.exception import StopUser

from tests.load.setup_load import LOAD_PASSWORD, N_CLIENTS, PER_CLIENT, load_email

_ids = itertools.count()
_lock = threading.Lock()


def _essay(n: int) -> bytes:
    import docx

    d = docx.Document()
    d.add_paragraph(
        f"Load test essay number {n}. Rising temperatures reduce wheat yields across Punjab and Sindh every "
        f"year, and many villages now depend on groundwater because canal water arrives late. Sample {uuid.uuid4()}."
    )
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class ClientUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        with _lock:
            self.index = next(_ids)
        if self.index >= N_CLIENTS:
            raise StopUser()
        r = self.client.post("/api/auth/login", json={"email": load_email(self.index), "password": LOAD_PASSWORD})
        self.csrf = r.json()["csrf_token"]
        self.sent = 0

    @task
    def upload(self) -> None:
        if self.sent >= PER_CLIENT:
            raise StopUser()
        self.sent += 1
        files = {"file": (f"essay-{self.index}-{self.sent}.docx", _essay(self.index * 10 + self.sent),
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
        with self.client.post("/api/submissions", files=files, data={"idempotency_key": uuid.uuid4().hex},
                              headers={"X-CSRF-Token": self.csrf}, name="POST /api/submissions",
                              catch_response=True) as r:
            if r.status_code != 202:
                r.failure(f"status {r.status_code}: {r.text[:200]}")
