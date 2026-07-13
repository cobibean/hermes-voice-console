from __future__ import annotations

import json
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from voice_console.auth import AuthFailure, AuthGate
from voice_console.config import AuthConfig, AuthMode, ConfigError


class StaticSigningKeyClient:
    def __init__(self, key) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, _token: str):
        return SimpleNamespace(key=self.key)


def service_gate(monkeypatch: pytest.MonkeyPatch) -> AuthGate:
    monkeypatch.setenv("VOICE_CONSOLE_SERVICE_TOKEN", "service-token-000000000000000")
    return AuthGate(
        AuthConfig(mode=AuthMode.SERVICE),
        public_base_url="http://localhost:8787",
        allowed_hosts=("localhost", "testserver"),
    )


def clerk_gate(monkeypatch: pytest.MonkeyPatch, *, allowed_users: tuple[str, ...] = ()):
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    config = AuthConfig(
        mode=AuthMode.CLERK,
        clerk_publishable_key="pk_test_public",
        clerk_issuer="https://clerk.example.test",
        allowed_origins=("https://console.example.test",),
        allowed_user_ids=allowed_users,
    )
    gate = AuthGate(
        config,
        public_base_url="https://console.example.test",
        allowed_hosts=("console.example.test",),
        signing_key_client=StaticSigningKeyClient(private_key.public_key()),
    )
    return gate, private_key


def clerk_token(
    private_key, *, subject: str = "user_123", azp: str = "https://console.example.test"
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "https://clerk.example.test",
            "sub": subject,
            "azp": azp,
            "iat": now,
            "nbf": now,
            "exp": now + 60,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_scope_secret_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE_CONSOLE_SCOPE_SECRET", raising=False)
    with pytest.raises(ConfigError):
        AuthGate(
            AuthConfig(mode=AuthMode.DEVELOPMENT),
            public_base_url="http://localhost:8787",
            allowed_hosts=("localhost",),
        )


def test_service_token_uses_bearer_and_stable_pseudonymous_owner(monkeypatch) -> None:
    gate = service_gate(monkeypatch)
    first = gate.authenticate_token("service-token-000000000000000")
    second = gate.authenticate_token("service-token-000000000000000")
    assert first.owner_key == second.owner_key
    assert first.principal_subject not in first.audit_subject
    with pytest.raises(AuthFailure):
        gate.authenticate_token("wrong-token")


def test_clerk_rs256_claims_origin_and_user_allowlist(monkeypatch) -> None:
    gate, private_key = clerk_gate(monkeypatch, allowed_users=("user_123",))
    context = gate.authenticate_token(clerk_token(private_key))
    assert context.principal_kind == "clerk"
    assert context.expires_at is not None

    with pytest.raises(AuthFailure) as disallowed_origin:
        gate.authenticate_token(clerk_token(private_key, azp="https://evil.example"))
    assert disallowed_origin.value.forbidden is False

    with pytest.raises(AuthFailure) as disallowed_user:
        gate.authenticate_token(clerk_token(private_key, subject="user_other"))
    assert disallowed_user.value.forbidden is True


def test_clerk_rejects_non_rs256(monkeypatch) -> None:
    gate, _private_key = clerk_gate(monkeypatch)
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://clerk.example.test",
            "sub": "user_123",
            "azp": "https://console.example.test",
            "iat": now,
            "nbf": now,
            "exp": now + 60,
        },
        "not-a-real-clerk-key-but-long-enough-for-hs256",
        algorithm="HS256",
    )
    with pytest.raises(AuthFailure):
        gate.authenticate_token(token)


def test_clerk_websocket_auth_and_refresh_preserve_principal(monkeypatch) -> None:
    gate, private_key = clerk_gate(monkeypatch, allowed_users=("user_123",))
    app = FastAPI()

    @app.get("/private")
    async def private(request: Request) -> dict[str, str]:
        context = gate.authenticate_http(request)
        return {"kind": context.principal_kind}

    @app.websocket("/ws")
    async def socket(websocket: WebSocket) -> None:
        context = await gate.authenticate_ws(websocket)
        if context:
            await websocket.send_json({"kind": context.principal_kind})

    token = clerk_token(private_key)
    with TestClient(app) as client:
        assert client.get("/private").status_code == 401
        assert client.get("/private", headers={"Authorization": f"Bearer {token}"}).json() == {
            "kind": "clerk"
        }
        assert (
            client.get(
                "/private",
                headers={
                    "Authorization": f"Bearer {clerk_token(private_key, subject='different_user')}"
                },
            ).status_code
            == 403
        )
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "auth", "token": token})
            assert websocket.receive_json()["type"] == "auth.ok"
            assert websocket.receive_json() == {"kind": "clerk"}
        with (
            pytest.raises(WebSocketDisconnect) as denied,
            client.websocket_connect("/ws") as websocket,
        ):
            websocket.send_json({"type": "auth", "token": "invalid"})
            websocket.receive_json()
        assert denied.value.code == 4401

    original = gate.authenticate_token(token)
    refreshed = gate.refresh(clerk_token(private_key), original)
    assert refreshed.principal_subject == original.principal_subject
    with pytest.raises(AuthFailure):
        gate.refresh(clerk_token(private_key, subject="different_user"), original)


def test_service_websocket_auth_frame_has_no_url_credential(monkeypatch) -> None:
    gate = service_gate(monkeypatch)
    app = FastAPI()

    @app.websocket("/ws")
    async def socket(websocket: WebSocket) -> None:
        context = await gate.authenticate_ws(websocket)
        if context:
            await websocket.send_json({"owner": context.owner_key[:10]})

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_text(
                json.dumps({"type": "auth", "token": "service-token-000000000000000"})
            )
            assert websocket.receive_json()["type"] == "auth.ok"
            assert len(websocket.receive_json()["owner"]) == 10

        with (
            pytest.raises(WebSocketDisconnect) as denied,
            client.websocket_connect("/ws") as websocket,
        ):
            websocket.send_json({"type": "auth", "token": "wrong"})
            websocket.receive_json()
        assert denied.value.code == 4401


def test_exact_host_and_origin_checks(monkeypatch) -> None:
    gate, _private_key = clerk_gate(monkeypatch)
    assert gate.validate_host("console.example.test")
    assert gate.validate_host("console.example.test:443")
    assert not gate.validate_host("evil.example.test")
    assert gate.validate_origin("https://console.example.test", required=True)
    assert not gate.validate_origin(None, required=True)
    assert not gate.validate_origin("https://evil.example.test", required=False)
    assert gate.validate_websocket_scheme("wss")
    assert not gate.validate_websocket_scheme("ws")
