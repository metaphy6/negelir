"""AWS Signature Version 4 request signer for S3-compatible requests.

Pure stdlib implementation — no boto3, no requests, no third-party deps.
Uses only: hmac, hashlib, datetime, urllib.parse.

Reference:
  https://docs.aws.amazon.com/general/latest/gr/sigv4-create-canonical-request.html
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _derive_signing_key(
    secret_access_key: str,
    date_stamp: str,
    region: str,
    service: str,
) -> bytes:
    """Derive the per-request signing key (NEVER stored or logged)."""
    k_date = _hmac_sha256(("AWS4" + secret_access_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def sign_s3_headers(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload_sha256: str,
    access_key_id: str,
    secret_access_key: str,
    region: str,
    service: str = "s3",
    now: datetime | None = None,
) -> dict[str, str]:
    """Return a copy of ``headers`` augmented with SigV4 auth headers.

    Adds ``x-amz-date``, ``x-amz-content-sha256``, and ``Authorization``.
    The secret access key is consumed internally and NEVER returned or logged.

    Args:
        method: HTTP verb in uppercase (``"PUT"``, ``"POST"``, ``"DELETE"``).
        url: Full request URL including scheme and path.
        headers: Existing headers dict (not mutated). ``host`` is derived
            from the URL if absent.
        payload_sha256: Lowercase hex SHA-256 of the request body.
            Pass ``hashlib.sha256(b"").hexdigest()`` for empty-body requests.
        access_key_id: S3-compatible access key ID.
        secret_access_key: S3-compatible secret access key. NEVER logged.
        region: AWS region string (e.g. ``"us-east-1"``). For non-AWS
            S3-compatible services (MinIO, R2, B2) pass the region configured
            for the bucket (often ``"auto"`` or ``"us-east-1"``).
        service: Service name for the credential scope (default ``"s3"``).
        now: UTC datetime for signing. Override in tests to pin timestamps.

    Returns:
        New header dict with SigV4 authentication headers merged in.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    parsed = urlparse(url)
    host = parsed.netloc

    # Build the complete set of headers for signing (lowercase keys internally).
    signed: dict[str, str] = {}
    for k, v in headers.items():
        signed[k.lower()] = v
    signed["host"] = host
    signed["x-amz-date"] = amz_date
    signed["x-amz-content-sha256"] = payload_sha256

    # Canonical headers: sorted by lowercase name, each terminated by "\n".
    sorted_keys = sorted(signed.keys())
    canonical_headers_str = "".join(
        f"{k}:{signed[k].strip()}\n" for k in sorted_keys
    )
    signed_headers_str = ";".join(sorted_keys)

    # Canonical URI: percent-encode path components, preserve "/" separators.
    canonical_uri = quote(parsed.path or "/", safe="/")

    # Canonical query string: sort pairs by (key, value); percent-encode both.
    raw_qs = parsed.query
    qs_pairs: list[tuple[str, str]] = []
    if raw_qs:
        for k, vs in parse_qs(raw_qs, keep_blank_values=True).items():
            for v in vs:
                qs_pairs.append((quote(k, safe=""), quote(v, safe="")))
    qs_pairs.sort()
    canonical_qs = "&".join(f"{k}={v}" for k, v in qs_pairs)

    # Hash the canonical request.
    canonical_request = "\n".join([
        method.upper(),
        canonical_uri,
        canonical_qs,
        canonical_headers_str,
        signed_headers_str,
        payload_sha256,
    ])

    # String to sign.
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    # Derive signing key and compute signature (NEVER stored or returned).
    signing_key = _derive_signing_key(secret_access_key, date_stamp, region, service)
    signature = hmac.new(
        signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    # Build Authorization header.
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )

    # Return the original headers (preserving caller's casing) plus the new ones.
    result = dict(headers)
    result["x-amz-date"] = amz_date
    result["x-amz-content-sha256"] = payload_sha256
    result["Authorization"] = authorization
    return result
