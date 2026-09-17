from uuid import UUID

from mimic42.testing.real_tg.checker import Checker, SyncChecker

# Фиксированный UUID владельца тестового аккаунта сайта; создаётся
# scripts/real_tg_setup.py через Admin API. Фиксированный id нужен, чтобы
# тесты находили агентов-мимиков по owner_id без Admin-ключа в рантайме.
REAL_TG_USER_ID = UUID("7e2f1a3c-9d4e-4f5b-8a6c-1b2d3e4f5a6b")

__all__ = ["Checker", "REAL_TG_USER_ID", "SyncChecker"]
