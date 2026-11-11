"""L1: AwsIotTransport logic against a fake MQTT connection and a local HTTP server."""
import json
import threading
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("awscrt")

from device.aws_transport import AwsIotTransport
from device.transport import FetchError, JobRejected, NetworkError


def _done(v=None):
    f = Future(); f.set_result(v); return f


class FakeConn:
    """Answers jobs requests the way AWS IoT would."""
    def __init__(self, replies): self.replies, self.cbs, self.published = replies, {}, []

    def subscribe(self, topic, qos, callback):
        self.cbs[topic] = callback
        return _done(), 1

    def publish(self, topic, payload, qos):
        body = json.loads(payload)
        self.published.append((topic, body))
        key = next((k for k in self.replies if topic.endswith(k)), None)
        if key:
            suffix, reply = self.replies[key]
            reply = dict(reply, clientToken=body["clientToken"])
            base = topic.rsplit("/", 1)[0] if key == "update" else topic
            cb = next(c for t, c in self.cbs.items()
                      if t.endswith(suffix) and (key != "start-next" or "start-next" in t)
                      and (key != "update" or "+/update" in t))
            cb(f"{base}/{suffix}", json.dumps(reply).encode())
        return _done(), 2


def _t(replies): return AwsIotTransport("device-001", connection=FakeConn(replies), timeout=1)


def test_start_next_returns_job():
    ex = {"jobId": "j1", "jobDocument": {"operation": "firmware-update", "version": "1.1.0"}}
    t = _t({"start-next": ("start-next/accepted", {"execution": ex})})
    assert t.start_next("device-001") == {"job_id": "j1", "document": ex["jobDocument"]}


def test_start_next_no_job():
    assert _t({"start-next": ("start-next/accepted", {})}).start_next("device-001") is None


def test_update_job_sends_string_details():
    t = _t({"update": ("update/accepted", {})})
    t.update_job("device-001", "j1", "FAILED", {"reason": "HASH_MISMATCH", "n": 3})
    topic, body = t._conn.published[-1]
    assert topic == "$aws/things/device-001/jobs/j1/update"
    assert body["status"] == "FAILED" and body["statusDetails"] == {"reason": "HASH_MISMATCH", "n": "3"}


def test_update_job_rejected_raises():
    t = _t({"update": ("update/rejected", {"code": "TerminalStateReached", "message": "x"})})
    with pytest.raises(JobRejected):
        t.update_job("device-001", "j1", "FAILED", {})


def test_no_reply_is_network_error():
    with pytest.raises(NetworkError):
        _t({}).start_next("device-001")


def test_heartbeat_and_shadow_topics():
    t = _t({})
    t.heartbeat("device-001"); t.update_shadow("device-001", {"version": "1.0.0"})
    assert [p[0] for p in t._conn.published] == ["$aws/things/device-001/shadow/update"] * 2
    assert t._conn.published[1][1] == {"state": {"reported": {"version": "1.0.0"}}}


DATA = bytes(range(256)) * 4   # 1024 bytes


class RangeHandler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.startswith("/missing"):
            self.send_response(403); self.end_headers(); return
        rng = self.headers.get("Range")
        start, end = (int(x) for x in rng.split("=")[1].split("-"))
        if start >= len(DATA):
            self.send_response(416); self.end_headers(); return
        chunk = DATA[start:end + 1]
        self.send_response(206); self.send_header("Content-Length", str(len(chunk)))
        self.end_headers(); self.wfile.write(chunk)


@pytest.fixture
def server():
    s = HTTPServer(("127.0.0.1", 0), RangeHandler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_fetch_ranges_and_end_of_file(server):
    t = _t({})
    assert t.fetch(f"{server}/fw", 0, 512) == DATA[:512]
    assert t.fetch(f"{server}/fw", 512, 512) == DATA[512:]
    assert t.fetch(f"{server}/fw", 1024, 512) == b""


def test_fetch_errors(server):
    t = _t({})
    with pytest.raises(FetchError):
        t.fetch(f"{server}/missing?X-Amz-Signature=secret", 0, 512)
    with pytest.raises(NetworkError):
        t.fetch("http://127.0.0.1:1/x", 0, 512)
