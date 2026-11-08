import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Callable
from typing import Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.security import AuthError, AuthUnavailable, TokenVerifier
from tests.conftest import AUDIENCE, ISSUER, FakeJwks

MakeToken = Callable[..., str]


def test_valid_token(verifier: TokenVerifier, make_token: MakeToken) -> None:
    uid = uuid.uuid4()
    claims = verifier.verify(
        make_token(
            uid,
            "Dev@Example.com",
            extra={"user_metadata": {"full_name": "Dev Eloper"}},
        )
    )
    assert claims.user_id == uid
    assert claims.email == "dev@example.com"
    assert claims.display_name == "Dev Eloper"


def test_expired_token(verifier: TokenVerifier, make_token: MakeToken) -> None:
    with pytest.raises(AuthError):
        verifier.verify(make_token(expires_in=-10))


def test_wrong_audience(verifier: TokenVerifier, make_token: MakeToken) -> None:
    with pytest.raises(AuthError):
        verifier.verify(make_token(audience="somebody-else"))


def test_wrong_issuer(verifier: TokenVerifier, make_token: MakeToken) -> None:
    with pytest.raises(AuthError):
        verifier.verify(make_token(issuer="https://evil.example.com/auth/v1"))


def test_signed_by_other_key(verifier: TokenVerifier, make_token: MakeToken) -> None:
    other = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(AuthError):
        verifier.verify(make_token(key=other))


def test_alg_none_rejected(verifier: TokenVerifier) -> None:
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": AUDIENCE,
            "iss": ISSUER,
            "exp": 9999999999,
            "email": "a@b.co",
        },
        key=cast(Any, None),
        algorithm="none",
    )
    with pytest.raises(AuthError):
        verifier.verify(token)


def test_garbage_token(verifier: TokenVerifier) -> None:
    with pytest.raises(AuthError):
        verifier.verify("not-a-jwt")


def test_missing_email_rejected(verifier: TokenVerifier, make_token: MakeToken) -> None:
    with pytest.raises(AuthError):
        verifier.verify(make_token(email=None))


def test_non_uuid_subject_rejected(verifier: TokenVerifier, make_token: MakeToken) -> None:
    with pytest.raises(AuthError):
        verifier.verify(make_token(user_id="not-a-uuid"))


def test_hs256_rejected_without_secret(verifier: TokenVerifier, make_token: MakeToken) -> None:
    with pytest.raises(AuthError):
        verifier.verify(make_token(key="x" * 40, alg="HS256"))


def test_hs256_accepted_with_secret(private_key: ec.EllipticCurvePrivateKey) -> None:
    secret = "legacy-secret-" + "x" * 32
    v = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, hs256_secret=secret)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": AUDIENCE,
            "iss": ISSUER,
            "exp": 9999999999,
            "email": "legacy@example.com",
        },
        secret,
        algorithm="HS256",
    )
    assert v.verify(token).email == "legacy@example.com"


def test_hs256_wrong_secret_rejected() -> None:
    v = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, hs256_secret="right-" + "x" * 32)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "aud": AUDIENCE,
            "iss": ISSUER,
            "exp": 9999999999,
            "email": "a@b.co",
        },
        "wrong-" + "x" * 32,
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        v.verify(token)


def test_algorithm_confusion_rejected(private_key: ec.EllipticCurvePrivateKey) -> None:
    """An HS256 token HMAC-signed with the public key must not verify (classic downgrade attack).

    PyJWT refuses to create such a token, so it is forged by hand, like an attacker would.
    """
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> bytes:
        return base64.urlsafe_b64encode(data).rstrip(b"=")

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(
        json.dumps(
            {
                "sub": str(uuid.uuid4()),
                "aud": AUDIENCE,
                "iss": ISSUER,
                "exp": 9999999999,
                "email": "attacker@example.com",
            }
        ).encode()
    )
    signing_input = header + b"." + body
    signature = b64(hmac.new(public_pem, signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + signature).decode()

    v = TokenVerifier(
        issuer=ISSUER, audience=AUDIENCE, jwks_client=FakeJwks(private_key.public_key())
    )
    with pytest.raises(AuthError):
        v.verify(forged)


def test_unconfigured_is_unavailable_not_unauthorized(make_token: MakeToken) -> None:
    v = TokenVerifier(issuer=None, audience=AUDIENCE)
    with pytest.raises(AuthUnavailable):
        v.verify(make_token())


def test_asymmetric_without_jwks_is_unavailable(make_token: MakeToken) -> None:
    v = TokenVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_client=None)
    with pytest.raises(AuthUnavailable):
        v.verify(make_token())
