"""Supabase access-token verification.

Asymmetric tokens (ES256/RS256) are verified against the project's JWKS endpoint.
Legacy HS256 tokens are only accepted when SUPABASE_JWT_SECRET is set. The algorithm
is always taken from an allow-list, never trusted from the token alone, so an attacker
cannot downgrade a token to `none` or confuse RS256 with HS256.
"""

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ASYMMETRIC_ALGS = ("ES256", "RS256")


class AuthError(Exception):
    """The token is missing, malformed, expired, or otherwise not acceptable (HTTP 401)."""


class AuthUnavailable(Exception):
    """Authentication can't be checked right now: not configured or keys unreachable (HTTP 503)."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    email: str
    display_name: str | None


class SigningKeyProvider(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class TokenVerifier:
    def __init__(
        self,
        *,
        issuer: str | None,
        audience: str,
        jwks_client: SigningKeyProvider | None = None,
        hs256_secret: str | None = None,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks = jwks_client
        self._hs256_secret = hs256_secret

    def verify(self, token: str) -> TokenClaims:
        if self._issuer is None:
            raise AuthUnavailable("Authentication is not configured (SUPABASE_URL is missing)")

        try:
            alg = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError as exc:
            raise AuthError("Malformed token") from exc

        key: Any
        if alg in ASYMMETRIC_ALGS:
            if self._jwks is None:
                raise AuthUnavailable("Asymmetric token verification is not configured")
            try:
                key = self._jwks.get_signing_key_from_jwt(token).key
            except jwt.PyJWKClientConnectionError as exc:
                logger.warning("JWKS endpoint unreachable: %s", exc)
                raise AuthUnavailable("Could not fetch signing keys") from exc
            except jwt.PyJWTError as exc:
                raise AuthError("Unknown signing key") from exc
        elif alg == "HS256":
            if not self._hs256_secret:
                raise AuthError("HS256 tokens are not accepted")
            key = self._hs256_secret
        else:
            raise AuthError("Unsupported token algorithm")

        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[str(alg)],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthError("Invalid or expired token") from exc

        return self._claims(payload)

    @staticmethod
    def _claims(payload: dict[str, Any]) -> TokenClaims:
        try:
            user_id = uuid.UUID(str(payload["sub"]))
        except ValueError as exc:
            raise AuthError("Invalid subject") from exc

        email = payload.get("email")
        if not isinstance(email, str) or not email.strip():
            raise AuthError("Account has no email address")

        meta = payload.get("user_metadata")
        name: str | None = None
        if isinstance(meta, dict):
            for field in ("full_name", "name", "user_name"):
                value = meta.get(field)
                if isinstance(value, str) and value.strip():
                    name = value.strip()[:200]
                    break

        return TokenClaims(user_id=user_id, email=email.strip().lower(), display_name=name)


@lru_cache
def get_token_verifier() -> TokenVerifier:
    settings = get_settings()
    jwks_url = settings.supabase_jwks_url
    secret = settings.supabase_jwt_secret
    return TokenVerifier(
        issuer=settings.supabase_issuer,
        audience=settings.supabase_jwt_audience,
        jwks_client=PyJWKClient(jwks_url, cache_keys=True, lifespan=600, timeout=5)
        if jwks_url
        else None,
        hs256_secret=secret.get_secret_value() if secret else None,
    )
