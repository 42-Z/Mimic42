from __future__ import annotations

from uuid import UUID


class FakeAdminRepository:
    """Role-check-only repository double; later admin methods stay unimplemented."""

    def __init__(
        self,
        *,
        admin_ids: set[UUID] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.admin_ids = set(admin_ids or ())
        self.unavailable = unavailable
        self.calls: list[UUID] = []

    async def is_admin(self, user_id: UUID) -> bool:
        self.calls.append(user_id)
        if self.unavailable:
            raise RuntimeError("postgresql://private-dsn SELECT from private_table")
        return user_id in self.admin_ids
