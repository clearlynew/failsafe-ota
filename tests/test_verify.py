"""L1: verification logic, no network."""
import json

import pytest

from cloud.release import build_release
from cloud.signing import LocalSigner
from device import verify


@pytest.fixture
def signer(): return LocalSigner()


def _check(art, signer, sv=2):
    pub = verify.load_public_key(signer.public_pem())
    m = verify.verify_manifest(art["manifest.json"], art["manifest.sig"], pub, sv)
    verify.verify_image(m, art["fw.bin"])
    return m


def test_good_release(signer):
    assert _check(build_release("good", "1.1.0", 3, signer), signer)["version"] == "1.1.0"


@pytest.mark.parametrize("tamper,reason", [
    ("wrong_key", "SIGNATURE_INVALID"), ("missing_sig", "SIGNATURE_INVALID"),
    ("garble_sig", "SIGNATURE_INVALID"), ("edit_sv", "SIGNATURE_INVALID"),
    ("edit_sha", "SIGNATURE_INVALID"), ("flip_image", "HASH_MISMATCH"),
    ("truncate_image", "SIZE_MISMATCH")])
def test_tamper_rejected(signer, tamper, reason):
    with pytest.raises(verify.VerifyError) as e:
        _check(build_release("good", "1.1.0", 3, signer, tamper=tamper), signer)
    assert e.value.reason == reason


def test_downgrade_rejected(signer):
    with pytest.raises(verify.VerifyError) as e:
        _check(build_release("good", "0.9.0", 1, signer), signer, sv=2)
    assert e.value.reason == "DOWNGRADE_REJECTED"


def test_equal_security_version_allowed(signer):
    _check(build_release("good", "1.0.5", 2, signer), signer, sv=2)


def test_canonical_json_ignores_whitespace_and_key_order(signer):
    a = build_release("good", "1.1.0", 3, signer)
    reordered = json.dumps(json.loads(a["manifest.json"]), separators=(",", ":")).encode()
    pub = verify.load_public_key(signer.public_pem())
    verify.verify_manifest(reordered, a["manifest.sig"], pub, 2)
