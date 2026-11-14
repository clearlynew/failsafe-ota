"""L1: publish/KMS-signing logic against fake AWS clients (no network, no boto3 needed)."""
import io
import json
import re
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from cloud import publish as pub
from cloud.signing import KmsSigner
from device import verify

OUT = {"bucket_name": "bkt", "kms_key_id": "kid", "presign_role_arn": "arn:aws:iam::1:role/r"}


class FakeKms:
    def __init__(self): self.key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, KeyId, Message, MessageType, SigningAlgorithm):
        assert MessageType == "DIGEST" and SigningAlgorithm == "ECDSA_SHA_256" and len(Message) == 32
        return {"Signature": self.key.sign(Message, ec.ECDSA(Prehashed(hashes.SHA256())))}

    def get_public_key(self, KeyId):
        return {"PublicKey": self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)}


class FakeS3:
    def __init__(self): self.objs = {}
    def put_object(self, Bucket, Key, Body): self.objs[(Bucket, Key)] = Body
    def get_object(self, Bucket, Key): return {"Body": io.BytesIO(self.objs[(Bucket, Key)])}


class FakeIot:
    def __init__(self): self.jobs = []
    def describe_thing(self, thingName): return {"thingArn": f"arn:aws:iot:us-east-1:1:thing/{thingName}"}
    def describe_thing_group(self, thingGroupName): return {"thingGroupArn": f"arn:aws:iot:us-east-1:1:thinggroup/{thingGroupName}"}
    def create_job(self, **kw): self.jobs.append(kw)


@pytest.fixture
def aws():
    return FakeKms(), FakeS3(), FakeIot()


def _write(signer, aws):
    p = Path(tempfile.mkdtemp()) / "pub.pem"
    p.write_bytes(signer.public_pem())
    return p


def test_kms_signature_verifies_with_exported_public_key(aws):
    kms, s3, iot = aws
    signer = KmsSigner("kid", client=kms)
    pub.publish(OUT, "1.1.0", 3, s3=s3, iot=iot, signer=signer)
    m = pub.verify_remote(OUT, "1.1.0", pubkey_path=_write(signer, aws), s3=s3)
    assert m["version"] == "1.1.0" and m["security_version"] == 3


def test_job_shape(aws):
    kms, s3, iot = aws
    job_id = pub.publish(OUT, "1.1.0", 3, s3=s3, iot=iot, signer=KmsSigner("kid", client=kms),
                         timeout_min=2)
    assert {k for (_, k) in s3.objs} == {f"releases/1.1.0/{n}" for n in ("fw.bin", "manifest.json", "manifest.sig")}
    job = iot.jobs[0]
    assert job["jobId"] == job_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", job_id)
    assert job["targets"] == ["arn:aws:iot:us-east-1:1:thing/device-001"]
    assert job["presignedUrlConfig"]["roleArn"] == OUT["presign_role_arn"]
    assert job["timeoutConfig"] == {"inProgressTimeoutInMinutes": 2}
    doc = json.loads(job["document"])
    assert doc["manifest_url"] == "${aws:iot:s3-presigned-url:https://bkt.s3.amazonaws.com/releases/1.1.0/manifest.json}"
    assert doc["operation"] == "firmware-update" and doc["version"] == "1.1.0"


def test_group_target(aws):
    kms, s3, iot = aws
    pub.publish(OUT, "1.1.0", 3, group="fleet-a", s3=s3, iot=iot, signer=KmsSigner("kid", client=kms))
    assert iot.jobs[0]["targets"][0].endswith("thinggroup/fleet-a")


def test_wrong_key_tamper_fails_against_kms_key(aws):
    kms, s3, iot = aws
    signer = KmsSigner("kid", client=kms)
    pub.publish(OUT, "1.1.0", 3, tamper="wrong_key", s3=s3, iot=iot, signer=signer)
    with pytest.raises(verify.VerifyError) as e:
        pub.verify_remote(OUT, "1.1.0", pubkey_path=_write(signer, aws), s3=s3)
    assert e.value.reason == "SIGNATURE_INVALID"


def test_rejects_bad_version(aws):
    kms, s3, iot = aws
    with pytest.raises(ValueError):
        pub.publish(OUT, "1.1.0/../x", 3, s3=s3, iot=iot, signer=KmsSigner("kid", client=kms))
        
        
def test_rollout_and_abort_config(aws):
    kms, s3, iot = aws
    pub.publish(OUT, "2.0.0", 3, group="fleet-a", s3=s3, iot=iot,
                signer=KmsSigner("kid", client=kms), max_per_minute=4,
                abort_threshold=20, abort_min_executed=5)
    job = iot.jobs[0]
    assert job["jobExecutionsRolloutConfig"] == {"maximumPerMinute": 4}
    assert job["abortConfig"]["criteriaList"] == [{
        "failureType": "ALL", "action": "CANCEL",
        "thresholdPercentage": 20.0, "minNumberOfExecutedThings": 5}]


def test_no_rollout_or_abort_by_default(aws):
    kms, s3, iot = aws
    pub.publish(OUT, "1.1.0", 3, s3=s3, iot=iot, signer=KmsSigner("kid", client=kms))
    assert "abortConfig" not in iot.jobs[0] and "jobExecutionsRolloutConfig" not in iot.jobs[0]
