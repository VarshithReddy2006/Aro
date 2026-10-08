"""Unit tests for RingSignatureVerifier."""

import hashlib
import hmac

from apps.api.src.services.ring_signature import RingSignatureVerifier


def test_signature_verifier_valid_raw_bytes():
    secret = "test_webhook_secret_key"
    body = b'{"event": "motion_detected"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    verifier = RingSignatureVerifier()
    res = verifier.verify(raw_body=body, signature_header=sig, secret=secret)
    assert res.is_valid is True
    assert res.reason is None


def test_signature_verifier_with_prefix():
    secret = "test_webhook_secret_key"
    body = b'{"event": "motion_detected"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    verifier = RingSignatureVerifier()
    # Test sha256= prefix
    res1 = verifier.verify(raw_body=body, signature_header=f"sha256={sig}", secret=secret)
    assert res1.is_valid is True

    # Test v1= prefix
    res2 = verifier.verify(raw_body=body, signature_header=f"v1={sig}", secret=secret)
    assert res2.is_valid is True


def test_signature_verifier_forged_signature():
    secret = "test_webhook_secret_key"
    body = b'{"event": "motion_detected"}'

    verifier = RingSignatureVerifier()
    res = verifier.verify(
        raw_body=body,
        signature_header="bad_signature_hex_value",
        secret=secret,
    )
    assert res.is_valid is False
    assert res.reason == "Invalid HMAC signature"


def test_signature_verifier_tampered_body():
    secret = "test_webhook_secret_key"
    original_body = b'{"event": "motion_detected"}'
    sig = hmac.new(secret.encode(), original_body, hashlib.sha256).hexdigest()

    tampered_body = b'{"event": "motion_detected", "tampered": true}'

    verifier = RingSignatureVerifier()
    res = verifier.verify(
        raw_body=tampered_body,
        signature_header=sig,
        secret=secret,
    )
    assert res.is_valid is False
    assert res.reason == "Invalid HMAC signature"


def test_signature_verifier_missing_signature():
    verifier = RingSignatureVerifier(default_secret="some_secret")
    res1 = verifier.verify(raw_body=b"{}", signature_header=None)
    assert res1.is_valid is False
    assert "Missing signature" in str(res1.reason)

    res2 = verifier.verify(raw_body=b"{}", signature_header="  ")
    assert res2.is_valid is False
    assert "Missing signature" in str(res2.reason)


def test_signature_verifier_missing_secret():
    verifier = RingSignatureVerifier(default_secret=None)
    res = verifier.verify(raw_body=b"{}", signature_header="abc123", secret=None)
    assert res.is_valid is False
    assert "secret is not configured" in str(res.reason)
