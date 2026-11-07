from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from urllib.error import URLError
from urllib.request import Request
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import HTTPException
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from mimic42.api.auth import SupabaseJWTVerifier

SUPABASE_URL = "https://project.supabase.co"
USER_ID = UUID("795dfd60-4899-4ca4-beb6-f88a948f4d79")


@dataclass(frozen=True)
class SignedToken:
    token: str
    public_jwk: dict[str, Any]


@dataclass
class JWKSEndpoint:
    keys: list[dict[str, Any]]
    available: bool = True
    requests: int = 0

    def open(self, request: Request, **kwargs: Any) -> BytesIO:
        assert request.full_url == f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        self.requests += 1
        if not self.available:
            raise URLError("JWKS endpoint unavailable")
        return BytesIO(json.dumps({"keys": self.keys}).encode())


@pytest.fixture(params=["RS256", "ES256"])
def signed_tokens(request: pytest.FixtureRequest) -> tuple[SignedToken, SignedToken]:
    def create(kid: str) -> SignedToken:
        if request.param == "RS256":
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            public_jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
        else:
            key = ec.generate_private_key(ec.SECP256R1())
            public_jwk = json.loads(ECAlgorithm.to_jwk(key.public_key()))
        public_jwk.update(kid=kid, use="sig", alg=request.param)
        token = jwt.encode(
            {
                "sub": str(USER_ID),
                "iss": f"{SUPABASE_URL}/auth/v1",
                "exp": datetime.now(UTC) + timedelta(hours=1),
            },
            key,
            algorithm=request.param,
            headers={"kid": kid},
        )
        return SignedToken(token=token, public_jwk=public_jwk)

    return create("old-key"), create("new-key")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monotonic = Mock(return_value=1000.0)
    time = SimpleNamespace(monotonic=monotonic)
    monkeypatch.setattr("jwt.api_jwk.time", time)
    monkeypatch.setattr("jwt.jwk_set_cache.time", time)
    return monotonic


@pytest.fixture
def endpoint(
    monkeypatch: pytest.MonkeyPatch,
    signed_tokens: tuple[SignedToken, SignedToken],
) -> JWKSEndpoint:
    endpoint = JWKSEndpoint(keys=[signed_tokens[0].public_jwk])
    monkeypatch.setattr("jwt.jwks_client.urllib.request.urlopen", endpoint.open)
    return endpoint


@pytest.mark.asyncio
async def test_revoked_key_expires_and_rotated_key_works_without_restart(
    signed_tokens: tuple[SignedToken, SignedToken],
    endpoint: JWKSEndpoint,
    clock: Mock,
) -> None:
    old, new = signed_tokens
    verifier = SupabaseJWTVerifier(supabase_url=SUPABASE_URL)

    assert (await verifier.verify(old.token)).user_id == USER_ID
    endpoint.keys = [new.public_jwk]
    clock.return_value = 1299.0
    assert (await verifier.verify(old.token)).user_id == USER_ID
    assert endpoint.requests == 1

    clock.return_value = 1301.0
    with pytest.raises(HTTPException) as revoked:
        await verifier.verify(old.token)
    assert revoked.value.status_code == 401
    assert (await verifier.verify(new.token)).user_id == USER_ID
    with pytest.raises(HTTPException) as still_revoked:
        await verifier.verify(old.token)
    assert still_revoked.value.status_code == 401


@pytest.mark.asyncio
async def test_expired_jwks_cache_fails_closed_during_outage_and_recovers(
    signed_tokens: tuple[SignedToken, SignedToken],
    endpoint: JWKSEndpoint,
    clock: Mock,
) -> None:
    old, new = signed_tokens
    verifier = SupabaseJWTVerifier(supabase_url=SUPABASE_URL)

    assert (await verifier.verify(old.token)).user_id == USER_ID
    endpoint.available = False
    clock.return_value = 1299.0
    assert (await verifier.verify(old.token)).user_id == USER_ID
    assert endpoint.requests == 1

    clock.return_value = 1301.0
    for token in (old.token, new.token, old.token):
        with pytest.raises(HTTPException) as unavailable:
            await verifier.verify(token)
        assert unavailable.value.status_code == 401

    endpoint.available = True
    endpoint.keys = [new.public_jwk]
    assert (await verifier.verify(new.token)).user_id == USER_ID
    with pytest.raises(HTTPException) as revoked:
        await verifier.verify(old.token)
    assert revoked.value.status_code == 401
