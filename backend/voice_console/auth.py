from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException, Request, WebSocket, status
from jwt import PyJWKClient

from .config import AuthConfig, AuthMode, ConfigError, secret_is_usable


class SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(frozen=True)
class AuthContext:
    principal_kind: str
    principal_subject: str
    owner_key: str
    expires_at: int | None = None

    @property
    def audit_subject(self) -> str:
        return f"{self.principal_kind}:{self.owner_key[:10]}"


@dataclass(frozen=True)
class AuthFailure(Exception):
    message: str
    forbidden: bool = False

    @property
    def http_status(self) -> int:
        return status.HTTP_403_FORBIDDEN if self.forbidden else status.HTTP_401_UNAUTHORIZED

    @property
    def ws_code(self) -> int:
        return 4403 if self.forbidden else 4401


class AuthGate:
    def __init__(
        self,
        config: AuthConfig,
        *,
        public_base_url: str,
        allowed_hosts: tuple[str, ...],
        signing_key_client: SigningKeyClient | None = None,
    ) -> None:
        self.config = config
        self.public_base_url = public_base_url.rstrip("/")
        self.public_url = urlsplit(self.public_base_url)
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts)
        self.allowed_origins = frozenset(
            config.allowed_origins
            or ((self.public_base_url,) if config.mode is AuthMode.DEVELOPMENT else ())
        )
        self._signing_key_client = signing_key_client
        self._validate_startup()

    @property
    def mode(self) -> AuthMode:
        return self.config.mode

    @property
    def scope_secret(self) -> str:
        return os.environ[self.config.scope_secret_env].strip()

    @property
    def service_token(self) -> str | None:
        value = os.environ.get(self.config.service_token_env, "").strip()
        return value or None

    def _validate_startup(self) -> None:
        if not secret_is_usable(os.environ.get(self.config.scope_secret_env)):
            raise ConfigError(
                f"{self.config.scope_secret_env} must be a distinct non-placeholder secret"
            )
        if self.mode is AuthMode.SERVICE and not secret_is_usable(self.service_token):
            raise ConfigError(
                f"{self.config.service_token_env} must be configured for service auth"
            )

    def public_config(self) -> dict[str, Any]:
        return {
            "auth_mode": self.mode.value,
            "clerk_publishable_key": (
                self.config.clerk_publishable_key if self.mode is AuthMode.CLERK else None
            ),
            "public_base_url": self.public_base_url,
        }

    def derive_owner_key(self, principal_kind: str, principal_subject: str) -> str:
        material = f"{principal_kind}\x00{principal_subject}".encode()
        return hmac.new(self.scope_secret.encode(), material, hashlib.sha256).hexdigest()[:32]

    def _context(
        self,
        kind: str,
        subject: str,
        *,
        expires_at: int | None = None,
    ) -> AuthContext:
        return AuthContext(
            principal_kind=kind,
            principal_subject=subject,
            owner_key=self.derive_owner_key(kind, subject),
            expires_at=expires_at,
        )

    def _bearer(self, authorization: str | None) -> str | None:
        value = authorization or ""
        if value.lower().startswith("bearer "):
            return value[7:].strip() or None
        return None

    def _clerk_client(self) -> SigningKeyClient:
        if self._signing_key_client is not None:
            return self._signing_key_client
        jwks_url = self.config.clerk_jwks_url or f"{self.config.clerk_issuer}/.well-known/jwks.json"
        self._signing_key_client = PyJWKClient(
            jwks_url,
            cache_keys=True,
            timeout=5,
        )
        return self._signing_key_client

    def authenticate_token(self, token: str | None) -> AuthContext:
        if self.mode is AuthMode.DEVELOPMENT:
            if token:
                raise AuthFailure("development auth does not accept credentials")
            return self._context("development", "loopback")
        if not token:
            raise AuthFailure("authentication required")
        if self.mode is AuthMode.SERVICE:
            expected = self.service_token
            if not expected or not hmac.compare_digest(token, expected):
                raise AuthFailure("invalid service credential")
            return self._context("service", "default")

        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise AuthFailure("invalid Clerk token algorithm")
            signing_key = self._clerk_client().get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=self.config.clerk_issuer,
                leeway=self.config.clock_skew_seconds,
                options={
                    "require": ["exp", "nbf", "iat", "sub"],
                    "verify_aud": False,
                },
            )
        except AuthFailure:
            raise
        except Exception as exc:
            raise AuthFailure("invalid Clerk authentication") from exc

        subject = str(payload.get("sub") or "")
        azp = str(payload.get("azp") or "").rstrip("/")
        if not subject or azp not in self.allowed_origins:
            raise AuthFailure("invalid Clerk authentication")
        if self.config.allowed_user_ids and subject not in self.config.allowed_user_ids:
            raise AuthFailure("Clerk user is not authorized", forbidden=True)
        return self._context("clerk", subject, expires_at=int(payload["exp"]))

    def authenticate_http(self, request: Request) -> AuthContext:
        try:
            return self.authenticate_token(self._bearer(request.headers.get("authorization")))
        except AuthFailure as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail=exc.message,
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    async def authenticate_ws(self, websocket: WebSocket) -> AuthContext | None:
        await websocket.accept()
        try:
            message = await asyncio.wait_for(
                websocket.receive(),
                timeout=self.config.auth_timeout_seconds,
            )
            raw = message.get("text")
            if not isinstance(raw, str):
                raise AuthFailure("text authentication frame required")
            if len(raw) > self.config.preauth_max_chars:
                raise AuthFailure("authentication frame is too large")
            frame = json.loads(raw)
            if not isinstance(frame, dict) or frame.get("type") != "auth":
                raise AuthFailure("authentication frame required")
            token = frame.get("token")
            if token is not None and not isinstance(token, str):
                raise AuthFailure("invalid authentication frame")
            context = self.authenticate_token(token)
            await websocket.send_json(
                {
                    "type": "auth.ok",
                    "principal_kind": context.principal_kind,
                    "expires_at": context.expires_at,
                }
            )
            return context
        except AuthFailure as exc:
            await websocket.close(code=exc.ws_code, reason=exc.message)
        except (TimeoutError, json.JSONDecodeError):
            await websocket.close(code=4401, reason="authentication frame required")
        return None

    def refresh(self, token: str | None, previous: AuthContext) -> AuthContext:
        if previous.principal_kind != "clerk":
            raise AuthFailure("this principal does not refresh")
        refreshed = self.authenticate_token(token)
        if (
            refreshed.principal_kind != previous.principal_kind
            or refreshed.principal_subject != previous.principal_subject
        ):
            raise AuthFailure("authentication principal changed")
        return refreshed

    def validate_host(self, host_header: str | None) -> bool:
        if not host_header:
            return False
        try:
            host = urlsplit(f"//{host_header}").hostname
        except ValueError:
            return False
        return bool(host) and host.lower() in self.allowed_hosts

    def validate_origin(self, origin: str | None, *, required: bool) -> bool:
        if not origin:
            return not required
        return origin.rstrip("/") in self.allowed_origins

    def validate_websocket_scheme(self, scheme: str) -> bool:
        public_host = self.public_url.hostname
        if public_host in {"localhost", "127.0.0.1", "::1"}:
            return scheme in {"ws", "wss"}
        return scheme == "wss"

    def token_expires_soon(self, context: AuthContext) -> bool:
        return bool(
            context.expires_at
            and context.expires_at - int(time.time()) <= self.config.refresh_notice_seconds
        )
