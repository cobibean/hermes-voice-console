from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request, WebSocket, status

from .config import secret_is_usable


@dataclass(frozen=True)
class AuthGate:
    required: bool
    secret_env: str = "VOICE_CONSOLE_SESSION_SECRET"

    @property
    def secret(self) -> str | None:
        value = os.environ.get(self.secret_env, "").strip()
        return value or None

    def startup_warnings(self) -> list[str]:
        if not self.required:
            return []
        if not secret_is_usable(self.secret):
            return [
                f"{self.secret_env} is missing or placeholder; HTTP/WebSocket console auth will reject requests."
            ]
        return []

    def check_token(self, token: str | None) -> bool:
        if not self.required:
            return True
        secret = self.secret
        if not secret_is_usable(secret):
            return False
        return bool(token) and hmac.compare_digest(token.strip(), secret)  # type: ignore[arg-type]

    def token_from_request(self, request: Request) -> str | None:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return request.headers.get("x-voice-console-token") or request.query_params.get("token")

    def require_http(self, request: Request) -> None:
        if not self.check_token(self.token_from_request(request)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Voice console authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def token_from_ws(self, websocket: WebSocket) -> str | None:
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return websocket.headers.get("x-voice-console-token") or websocket.query_params.get("token")

    async def require_ws(self, websocket: WebSocket) -> bool:
        if self.check_token(self.token_from_ws(websocket)):
            return True
        await websocket.close(code=4401, reason="Voice console authentication required")
        return False
