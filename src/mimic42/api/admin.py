from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from mimic42.api.auth import CurrentUser, require_user
from mimic42.core.admin import AdminIdentity, AdminRepository, AdminUnavailableError


def _admin_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Администрирование временно недоступно",
    )


async def _check_admin_role(request: Request, user_id: UUID) -> bool:
    repository: AdminRepository | None = getattr(request.app.state, "admin_repository", None)
    if repository is None:
        raise _admin_unavailable()

    try:
        return await repository.is_admin(user_id)
    except AdminUnavailableError:
        raise _admin_unavailable() from None
    except Exception:
        raise _admin_unavailable() from None


async def require_admin(request: Request) -> CurrentUser:
    current_user = await require_user(request)
    if not await _check_admin_role(request, current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ разрешён только администраторам",
        )
    return current_user


async def get_admin_identity(request: Request, current_user: CurrentUser) -> AdminIdentity:
    return AdminIdentity(
        user_id=current_user.user_id,
        is_admin=await _check_admin_role(request, current_user.user_id),
    )


router = APIRouter(
    prefix="/api/v1/admin",
    dependencies=[Depends(require_admin)],
)
