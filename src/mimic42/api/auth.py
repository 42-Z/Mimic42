from __future__ import annotations

import asyncio
from typing import Any, Protocol
from uuid import UUID

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWKClient
from pydantic import BaseModel

ACCESS_TOKEN_COOKIE_NAMES = (
    "mimic42_access_token",
    "access_token",
    "sb-access-token",
)


class CurrentUser(BaseModel):
    user_id: UUID


class AuthVerifier(Protocol):
    async def verify(self, token: str) -> CurrentUser: ...


class SupabaseJWTVerifier:
    def __init__(self, *, supabase_url: str) -> None:
        self._supabase_url = supabase_url.rstrip("/")
        self._jwks_client = PyJWKClient(
            f"{self._supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )

    async def verify(self, token: str) -> CurrentUser:
        try:
            signing_key = await asyncio.to_thread(
                self._jwks_client.get_signing_key_from_jwt,
                token,
            )
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                issuer=f"{self._supabase_url}/auth/v1",
                options={"verify_aud": False},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Недействительный токен аутентификации",
            ) from exc

        user_id = _extract_user_id(payload)
        return CurrentUser(user_id=user_id)


class DisabledAuthVerifier:
    async def verify(self, token: str) -> CurrentUser:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Аутентификация не настроена",
        )


async def require_user(request: Request) -> CurrentUser:
    verifier = _get_verifier(request)
    token = _extract_access_token(request)
    return await verifier.verify(token)


def _get_verifier(request: Request) -> AuthVerifier:
    verifier = getattr(request.app.state, "auth_verifier", None)
    if verifier is None:
        return DisabledAuthVerifier()
    return verifier


def _extract_access_token(request: Request) -> str:
    authorization = request.headers.get("authorization")
    if authorization is not None:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Некорректный заголовок Authorization",
            )
        return token

    for cookie_name in ACCESS_TOKEN_COOKIE_NAMES:
        token = request.cookies.get(cookie_name)
        if token:
            return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Отсутствует токен доступа",
    )


def _extract_user_id(payload: dict[str, Any]) -> UUID:
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен аутентификации не содержит идентификатор пользователя",
        )
    try:
        return UUID(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Токен аутентификации содержит некорректный идентификатор пользователя",
        ) from exc
