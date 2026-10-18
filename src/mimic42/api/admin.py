from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from mimic42.api.auth import CurrentUser, require_user
from mimic42.core.admin import AdminIdentity, AdminRepository, AdminUnavailableError

logger = logging.getLogger(__name__)


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
    except AdminUnavailableError as exc:
        logger.warning("Administrator role lookup unavailable (%s)", type(exc).__name__)
        raise _admin_unavailable() from None
    except Exception as exc:
        logger.error(
            "Unexpected administrator role lookup error (%s)",
            type(exc).__name__,
        )
        raise _admin_unavailable() from None


async def require_admin(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(require_user)],
) -> CurrentUser:
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
