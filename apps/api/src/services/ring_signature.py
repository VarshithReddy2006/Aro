"""Ring HMAC-SHA256 signature verification service.

Strictly verifies webhook authenticity against untrusted input:
- Computes HMAC-SHA256 over exact raw request body bytes.
- Uses constant-time comparison to prevent timing side-channel attacks.
- Never logs webhook secrets, signatures, or raw credentials.
"""

import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class SignatureVerificationResult:
    """Explicit result of an HMAC signature verification attempt."""

    is_valid: bool
    reason: str | None = None


class RingSignatureVerifier:
    """Cryptographic signature verifier for incoming Ring webhooks."""

    def __init__(self, default_secret: str | None = None) -> None:
        self._default_secret = default_secret

    def verify(
        self,
        raw_body: bytes | str,
        signature_header: str | None,
        secret: str | None = None,
    ) -> SignatureVerificationResult:
        """Verify the HMAC-SHA256 signature against the raw body.

        Args:
            raw_body: Raw request body as bytes or exact raw wire string.
            signature_header: Content of X-Signature (or equivalent) header.
            secret: Shared HMAC key. Falls back to default_secret if omitted.

        Returns:
            SignatureVerificationResult with boolean flag and failure reason if invalid.
        """
        active_secret = secret if secret is not None else self._default_secret
        if not active_secret:
            return SignatureVerificationResult(
                is_valid=False,
                reason="Webhook signing secret is not configured",
            )

        if not signature_header or not signature_header.strip():
            return SignatureVerificationResult(
                is_valid=False,
                reason="Missing signature header",
            )

        # Handle header formats: raw hex or prefix like "sha256=" or "v1="
        sig_str = signature_header.strip()
        if sig_str.startswith("sha256="):
            sig_str = sig_str[7:].strip()
        elif sig_str.startswith("v1="):
            sig_str = sig_str[3:].strip()

        # Ensure raw body is bytes
        if isinstance(raw_body, str):
            raw_bytes = raw_body.encode("utf-8")
        else:
            raw_bytes = raw_body

        expected_sig = hmac.new(
            active_secret.encode("utf-8"),
            raw_bytes,
            hashlib.sha256,
        ).hexdigest()

        # Constant-time comparison
        is_match = hmac.compare_digest(expected_sig.lower(), sig_str.lower())
        if is_match:
            return SignatureVerificationResult(is_valid=True)

        return SignatureVerificationResult(
            is_valid=False,
            reason="Invalid HMAC signature",
        )
