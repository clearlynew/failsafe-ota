"""Real AWS IoT transport: Jobs + Shadow over MQTT (mutual TLS), firmware over HTTPS.

Implements the same five methods as cloud/fake_jobs.FakeJobs, so the updater is unchanged.
"""
import json
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import faults
from .transport import FetchError, JobRejected, NetworkError


class AwsIotTransport:
    def __init__(self, thing, endpoint=None, cert=None, key=None, ca=None,
                 connection=None, timeout=10.0):
        self.thing, self.timeout = thing, timeout
        self._args = (endpoint, cert, key, ca)
        self._conn = connection            # injectable for tests
        self._pending, self._lock, self._subscribed = {}, threading.Lock(), False

    # ---------- plumbing ----------
    def _net(self):
        if faults.net_blackholed():        # lets the S6 network faults work against real AWS
            raise NetworkError("blackholed")

    def _connection(self):
        if self._conn is None:
            from awsiot import mqtt_connection_builder
            endpoint, cert, key, ca = self._args
            conn = mqtt_connection_builder.mtls_from_path(
                endpoint=endpoint, cert_filepath=cert, pri_key_filepath=key,
                ca_filepath=ca, client_id=self.thing, clean_session=True, keep_alive_secs=30)
            try:
                conn.connect().result(self.timeout)
            except Exception as e:
                raise NetworkError(f"connect failed: {e}") from e
            self._conn = conn
        return self._conn

    def _publish(self, topic, body):
        from awscrt.mqtt import QoS
        self._net()
        try:
            fut, _ = self._connection().publish(
                topic=topic, payload=json.dumps(body), qos=QoS.AT_LEAST_ONCE)
            fut.result(self.timeout)       # waits for the broker's PUBACK
        except NetworkError:
            raise
        except Exception as e:
            raise NetworkError(str(e)) from e

    def _on_message(self, topic, payload, **kwargs):
        try:
            body = json.loads(payload)
        except ValueError:
            return
        with self._lock:
            slot = self._pending.get(body.get("clientToken"))
        if slot is not None:
            slot["topic"], slot["body"] = topic, body
            slot["event"].set()

    def _ensure_subscribed(self):
        if self._subscribed:
            return
        from awscrt.mqtt import QoS
        base = f"$aws/things/{self.thing}/jobs"
        try:
            for suffix in ("start-next/accepted", "start-next/rejected",
                           "+/update/accepted", "+/update/rejected"):
                fut, _ = self._connection().subscribe(
                    topic=f"{base}/{suffix}", qos=QoS.AT_LEAST_ONCE, callback=self._on_message)
                fut.result(self.timeout)
        except NetworkError:
            raise
        except Exception as e:
            raise NetworkError(f"subscribe failed: {e}") from e
        self._subscribed = True

    def _request(self, topic, body):
        """Publish a request and wait for the accepted/rejected reply with our clientToken."""
        self._net()
        self._ensure_subscribed()
        token, slot = uuid.uuid4().hex, {"event": threading.Event()}
        with self._lock:
            self._pending[token] = slot
        try:
            self._publish(topic, dict(body, clientToken=token))
            if not slot["event"].wait(self.timeout):
                raise NetworkError("no reply from AWS IoT")
        finally:
            with self._lock:
                self._pending.pop(token, None)
        return slot["topic"], slot["body"]

    # ---------- the five transport methods ----------
    def start_next(self, thing):
        topic, body = self._request(f"$aws/things/{self.thing}/jobs/start-next", {})
        if topic.endswith("/accepted"):
            ex = body.get("execution")
            return {"job_id": ex["jobId"], "document": ex["jobDocument"]} if ex else None
        if body.get("code") == "ResourceNotFound":
            return None
        raise RuntimeError(f"start-next rejected: {body}")

    def update_job(self, thing, job_id, status, details):
        topic, body = self._request(
            f"$aws/things/{self.thing}/jobs/{job_id}/update",
            {"status": status, "statusDetails": {k: str(v) for k, v in details.items()}})
        if topic.endswith("/rejected"):
            raise JobRejected(f"{body.get('code')}: {body.get('message')}")

    def fetch(self, url, offset, length):
        self._net()
        req = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = r.read()
                return data[offset:offset + length] if r.status == 200 else data  # 200 = Range ignored
        except urllib.error.HTTPError as e:
            if e.code == 416:              # offset at/after end of object
                return b""
            raise FetchError(f"HTTP {e.code} fetching {url.split('?')[0]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise NetworkError(str(e)) from e

    def heartbeat(self, thing):
        self._publish(f"$aws/things/{self.thing}/shadow/update",
                      {"state": {"reported": {"last_heartbeat": int(time.time())}}})

    def update_shadow(self, thing, reported):
        self._publish(f"$aws/things/{self.thing}/shadow/update",
                      {"state": {"reported": reported}})
