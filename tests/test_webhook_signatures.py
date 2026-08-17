"""tests/test_webhook_signatures.py — Unit tests for GitHub and Linear webhook HMAC verification."""

import hmac
import hashlib
from swarmcurator.adapters import verify_github_signature, verify_linear_signature


def test_github_webhook_signature_verification() -> None:
    secret = "my-github-secret-key-123"
    body = b'{"action": "opened", "issue": {"number": 42, "title": "Test Issue"}}'

    # Compute valid signature
    valid_sig = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(body, valid_sig, secret) is True

    # Tampered body -> invalid
    assert verify_github_signature(b'{"action": "tampered"}', valid_sig, secret) is False

    # Invalid secret -> invalid
    assert verify_github_signature(body, valid_sig, "wrong-secret") is False

    # Empty signature -> invalid
    assert verify_github_signature(body, "", secret) is False


def test_linear_webhook_signature_verification() -> None:
    secret = "linear_webhook_secret_xyz"
    body = b'{"type": "Issue", "action": "create", "data": {"identifier": "GRO-88"}}'

    # Compute valid Linear signature (hex digest without sha256= prefix)
    valid_sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert verify_linear_signature(body, valid_sig, secret) is True

    # Tampered body -> invalid
    assert verify_linear_signature(b'{"type": "Tampered"}', valid_sig, secret) is False

    # Invalid secret -> invalid
    assert verify_linear_signature(body, valid_sig, "wrong-secret") is False
