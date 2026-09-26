# Tracing (Braintrust) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Каждый ход мимика виден в Braintrust как trace (вход, LLM-вызовы, инструменты, токены, ошибки), а из дашборда в него ведёт ссылка `trace_url`.

**Architecture:** Новый модуль `src/mimic42/integrations/tracing.py` держит всю интеграцию с Braintrust: `setup_tracing` (init logger + глобальный LangChain-хендлер), `turn_span` (корневой спан хода) и no-op-поведение без `BRAINTRUST_API_KEY`. `_take_turn` в `agent_runtime` оборачивает ход в `turn_span` и пишет `trace_url` в события `turn.completed` (новый тип) и `turn.failed`. Фронтенд показывает ссылку «Трейс» в строках событий ленты активности.

**Tech Stack:** Python 3.13, uv, ruff, ty, pytest; braintrust (Python SDK), LangChain v1 / LangGraph; Next.js + TypeScript, bun, @testing-library/react.

**Спека:** `docs/superpowers/specs/2026-09-26-tracing-braintrust-design.md`

**Отклонения от спеки (осознанные):**
- Тесты лежат по конвенции репо: `tests/integrations/test_tracing.py` (модуль интеграции) и `tests/core/test_agent_runtime_tracing.py` (рантайм) — в спеке путь исправлен.
- `environment` в metadata спана модуль трейсинга читает из `Settings` сам — у `_take_turn` нет настроек приложения.
- `trace_url` кладётся только в события уровня хода (`turn.completed`, `turn.failed` с `turn_id`); catch-all `_record_incoming_failure` пишет `turn.failed` без `turn_id` и без спана — у него ссылки нет, ошибка всё равно видна на спане в Braintrust.

---

## File Structure

| Файл | Действие | Ответственность |
| --- | --- | --- |
| `pyproject.toml`, `uv.lock` | изменить | зависимость `braintrust` |
| `src/mimic42/config.py` | изменить | поля `braintrust_api_key`, `braintrust_project` |
| `.env.example` | изменить | документирование новых env |
| `src/mimic42/integrations/tracing.py` | создать | вся интеграция с Braintrust |
| `src/mimic42/api/app.py` | изменить | `setup_tracing` на старте, `flush_tracing` на остановке |
| `src/mimic42/core/agent_runtime.py` | изменить | корневой спан хода, `turn.completed`, `trace_url` |
| `frontend/src/lib/activity/eventCatalog.ts` | изменить | подпись события `turn.completed` |
| `frontend/src/lib/activity/normalize.ts` | изменить | `ActivityAction.traceUrl` из `payload.trace_url` |
| `frontend/src/components/activity/ActionRow.tsx` | изменить | ссылка «Трейс» в строке события |
| `README.md` | изменить | раздел «Трейсинг» |
| `tests/core/test_config_tracing.py` | создать | поля Settings |
| `tests/integrations/test_tracing.py` | создать | setup/flush/turn_span на фейковом SDK |
| `tests/api/test_app_tracing.py` | создать | вызовы в lifespan |
| `tests/core/test_agent_runtime_tracing.py` | создать | `turn.completed` / `trace_url` в событиях |
| `frontend/src/__tests__/activity-trace-link.test.ts(x)` | создать | `traceUrl` в ленте и ссылка в `ActionRow` |

---

### Task 1: Зависимость braintrust и поля Settings ✅ (4d33ceb + bfbc414; spec ✅, quality ✅)

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (через `uv add braintrust`)
- Modify: `src/mimic42/config.py`
- Modify: `.env.example`
- Test: `tests/core/test_config_tracing.py`

- [ ] **Step 1: Добавь зависимость**

Run:
```bash
uv add braintrust
```
Expected: `braintrust` появляется в `[project] dependencies` `pyproject.toml`, `uv.lock` обновлён.

- [ ] **Step 2: Напиши падающий тест**

Создай `tests/core/test_config_tracing.py`:

```python
from __future__ import annotations

import pytest

from mimic42.config import Settings


def test_braintrust_settings_default_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAINTRUST_API_KEY", raising=False)
    monkeypatch.delenv("BRAINTRUST_PROJECT", raising=False)
    settings = Settings(_env_file=None)

    assert settings.braintrust_api_key is None
    assert settings.braintrust_project == "Mimic42"


def test_braintrust_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAINTRUST_API_KEY", "bt-key")
    monkeypatch.setenv("BRAINTRUST_PROJECT", "Mimic42 Dev")
    settings = Settings(_env_file=None)

    assert settings.braintrust_api_key == "bt-key"
    assert settings.braintrust_project == "Mimic42 Dev"
```

`_env_file=None` отключает чтение `.env` разработчика: тесты детерминированы даже если в
`.env` уже лежит рабочий ключ Braintrust.

- [ ] **Step 3: Запусти тест — он должен упасть**

Run: `uv run pytest tests/core/test_config_tracing.py -q`
Expected: FAIL — `AttributeError`/`ValidationError`: полей `braintrust_api_key` нет.

- [ ] **Step 4: Добавь поля в Settings**

В `src/mimic42/config.py`, сразу после `telegram_api_hash` (строка 27):

```python
    braintrust_api_key: str | None = Field(default=None, validation_alias="BRAINTRUST_API_KEY")
    braintrust_project: str = Field(default="Mimic42", validation_alias="BRAINTRUST_PROJECT")
```

- [ ] **Step 5: Запусти тест — он должен пройти**

Run: `uv run pytest tests/core/test_config_tracing.py -q`
Expected: PASS (2 теста).

- [ ] **Step 6: Задокументируй env**

В `.env.example`, в блоке переменных бэкенда (после `MEM0_API_KEY` / `OPENROUTER_API_KEY`):

```bash
# Трейсинг в Braintrust (https://braintrust.dev). Выключен, пока ключ пуст.
BRAINTRUST_API_KEY=
BRAINTRUST_PROJECT=Mimic42
```

- [ ] **Step 7: Проверь линтеры и закоммить**

Run:
```bash
uv run ruff check .
uv run ty check
git add pyproject.toml uv.lock src/mimic42/config.py .env.example tests/core/test_config_tracing.py
git commit -m "feat: Braintrust settings and dependency (issue #92)"
```
Expected: `All checks passed!` дважды, коммит создан.

---

### Task 2: `tracing.py` — setup, flush, состояние

**Files:**
- Create: `src/mimic42/integrations/tracing.py`
- Test: `tests/integrations/test_tracing.py`

- [ ] **Step 1: Напиши падающий тест**

Создай `tests/integrations/test_tracing.py`:

```python
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from mimic42.config import Settings
from mimic42.integrations import tracing


@pytest.fixture(autouse=True)
def _clean_tracing_state() -> Iterator[None]:
    tracing.reset_tracing()
    yield
    tracing.reset_tracing()


class FakeBraintrust:
    def __init__(self) -> None:
        self.init_calls: list[dict[str, Any]] = []
        self.flush_calls = 0
        self.handlers: list[Any] = []

    def init_logger(self, **kwargs: Any) -> Any:
        self.init_calls.append(kwargs)
        return object()

    def flush(self) -> None:
        self.flush_calls += 1


def _patch_braintrust(monkeypatch: pytest.MonkeyPatch) -> FakeBraintrust:
    fake = FakeBraintrust()
    monkeypatch.setattr(tracing.braintrust, "init_logger", fake.init_logger)
    monkeypatch.setattr(tracing.braintrust, "flush", fake.flush)
    monkeypatch.setattr(tracing, "set_global_handler", fake.handlers.append)
    monkeypatch.setattr(tracing, "BraintrustCallbackHandler", lambda: "handler")
    return fake


def _settings(**kwargs: Any) -> Settings:
    return Settings(_env_file=None, **kwargs)


def test_setup_tracing_without_key_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)

    tracing.setup_tracing(_settings(braintrust_api_key=None))

    assert fake.init_calls == []
    assert fake.handlers == []
    assert tracing.tracing_enabled() is False


def test_setup_tracing_initializes_braintrust(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key", braintrust_project="Mimic42 Dev"))

    assert fake.init_calls == [{"project": "Mimic42 Dev", "api_key": "bt-key"}]
    assert fake.handlers == ["handler"]
    assert tracing.tracing_enabled() is True


def test_setup_tracing_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)
    settings = _settings(braintrust_api_key="bt-key")

    tracing.setup_tracing(settings)
    tracing.setup_tracing(settings)

    assert len(fake.init_calls) == 1
    assert fake.handlers == ["handler"]


def test_setup_tracing_init_failure_disables_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_braintrust(monkeypatch)

    def boom(**_: Any) -> Any:
        raise RuntimeError("bad key")

    monkeypatch.setattr(tracing.braintrust, "init_logger", boom)

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))

    assert tracing.tracing_enabled() is False


def test_flush_tracing_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _patch_braintrust(monkeypatch)

    tracing.flush_tracing()
    assert fake.flush_calls == 0

    tracing.setup_tracing(_settings(braintrust_api_key="bt-key"))
    tracing.flush_tracing()
    assert fake.flush_calls == 1
```

- [ ] **Step 2: Запусти тест — он должен упасть**

Run: `uv run pytest tests/integrations/test_tracing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'mimic42.integrations.tracing'`.

- [ ] **Step 3: Создай модуль**

Создай `src/mimic42/integrations/tracing.py`:

```python
"""Трейсинг ходов агента в Braintrust (issue #92).

Включается наличием BRAINTRUST_API_KEY: без ключа модуль — no-op, Braintrust
не вызывается ни разу. Сбои трейсинга никогда не роняют ход агента.
"""

from __future__ import annotations

import logging

import braintrust
from braintrust.integrations.langchain import BraintrustCallbackHandler, set_global_handler

from mimic42.config import Settings

logger = logging.getLogger("mimic42.tracing")

_enabled = False
_environment: str | None = None


def tracing_enabled() -> bool:
    """Трейсинг включён: Braintrust инициализирован и готов принимать спаны."""
    return _enabled


def setup_tracing(settings: Settings) -> None:
    """Инициализирует Braintrust и глобальный LangChain-хендлер. Идемпотентно."""
    global _enabled, _environment
    if _enabled or not settings.braintrust_api_key:
        return
    try:
        braintrust.init_logger(
            project=settings.braintrust_project,
            api_key=settings.braintrust_api_key,
        )
    except Exception:
        logger.warning("Braintrust tracing disabled: init failed", exc_info=True)
        return
    # Состояние фиксируем сразу после init_logger: SDK уже запущен, спаны работают,
    # даже если установка глобального хендлера ниже не удалась.
    # Окружение кэшируем здесь: в ходе Settings() больше не конструируется.
    _environment = settings.environment
    _enabled = True
    try:
        # Глушитель ниже — false positive: braintrust.integrations.langchain переопределяет
        # BraintrustCallbackHandler в except ImportError (fallback без langchain-core), из-за чего
        # ty считает результат конструктора union'ом двух классов.
        set_global_handler(BraintrustCallbackHandler())  # ty: ignore[invalid-argument-type]
    except Exception:
        logger.warning("Braintrust global handler not installed", exc_info=True)
    logger.info("Braintrust tracing enabled (project=%s)", settings.braintrust_project)


def flush_tracing() -> None:
    """Допрашивает очередь логов при остановке приложения (best-effort)."""
    if not _enabled:
        return
    try:
        braintrust.flush()
    except Exception:
        logger.warning("Braintrust flush failed", exc_info=True)


def reset_tracing() -> None:
    """Сбрасывает состояние модуля — только для тестов.

    Глобальный LangChain-хендлер не снимает: тесты мокают ``set_global_handler``,
    поэтому снимать его нечего и не нужно.
    """
    global _enabled, _environment
    _enabled = False
    _environment = None
```

- [ ] **Step 4: Запусти тест — он должен пройти**

Run: `uv run pytest tests/integrations/test_tracing.py -q`
Expected: PASS (5 тестов).

- [ ] **Step 5: Проверь линтеры и закоммить**

Run:
```bash
uv run ruff check .
uv run ty check
git add src/mimic42/integrations/tracing.py tests/integrations/test_tracing.py
git commit -m "feat: Braintrust setup module for tracing (issue #92)"
```
Expected: `All checks passed!` дважды, коммит создан.

---

### Task 3: `tracing.py` — корневой спан хода `turn_span` ✅ (a700007 + 5f17a4d; spec ✅, quality ✅ после фикса Critical)

**Files:**
- Modify: `src/mimic42/integrations/tracing.py`
- Test: `tests/integrations/test_tracing.py` (добавить)

- [ ] **Step 1: Напиши падающий тест**

Добавь в `tests/integrations/test_tracing.py`:

```python
import asyncio
from uuid import uuid4


class FakeSpan:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.ended = 0
        self.calls: list[str] = []
        self.start_kwargs: dict[str, Any] = {}
        self.log_error: BaseException | None = None
        self.permalink_value = "https://braintrust.dev/app/p/mimic42/t/turn-1"

    def log(self, **event: Any) -> None:
        if self.log_error is not None:
            raise self.log_error
        self.events.append(event)

    def set_current(self) -> None:
        self.calls.append("set_current")

    def unset_current(self) -> None:
        self.calls.append("unset_current")

    def end(self) -> None:
        self.calls.append("end")
        self.ended += 1

    def permalink(self) -> str:
        return self.permalink_value


def _enable_tracing(monkeypatch: pytest.MonkeyPatch, **settings_kwargs: Any) -> list[FakeSpan]:
    _patch_braintrust(monkeypatch)
    spans: list[FakeSpan] = []

    def start_span(**kwargs: Any) -> FakeSpan:
        span = FakeSpan()
        span.start_kwargs = kwargs
        spans.append(span)
        return span

    monkeypatch.setattr(tracing.braintrust, "start_span", start_span)
    tracing.setup_tracing(_settings(braintrust_api_key="bt-key", **settings_kwargs))
    return spans


def test_turn_span_is_noop_without_tracing() -> None:
    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="openrouter/free", input={"text": "hi"}
    ) as trace:
        trace.log(output={"text": "ok"})

    assert trace.permalink() is None


def test_turn_span_logs_input_metadata_and_output(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)
    agent_id = uuid4()

    with tracing.turn_span(
        agent_id=agent_id,
        turn_id="t1",
        peer="chat",
        model="openrouter/free",
        input={"text": "hi"},
    ) as trace:
        trace.log(output={"text": "ok"})

    assert len(spans) == 1
    span = spans[0]
    assert span.start_kwargs["name"] == "turn chat"
    assert span.start_kwargs["type"] == "task"
    assert span.events[0]["input"] == {"text": "hi"}
    metadata = span.events[0]["metadata"]
    assert metadata["agent_id"] == str(agent_id)
    assert metadata["turn_id"] == "t1"
    assert metadata["peer"] == "chat"
    assert metadata["model"] == "openrouter/free"
    assert isinstance(metadata["environment"], str) and metadata["environment"]
    assert span.events[1] == {"output": {"text": "ok"}}
    assert span.ended == 1
    assert span.calls == ["set_current", "unset_current", "end"]
    assert trace.permalink() == span.permalink_value


def test_turn_span_records_error_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    with pytest.raises(RuntimeError, match="boom"):
        with tracing.turn_span(
            agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
        ):
            raise RuntimeError("boom")

    assert spans[0].events[-1] == {"error": "boom"}
    assert spans[0].ended == 1
    assert spans[0].calls == ["set_current", "unset_current", "end"]


def test_turn_span_survives_start_span_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_tracing(monkeypatch)

    def boom(**_: Any) -> Any:
        raise RuntimeError("sdk down")

    monkeypatch.setattr(tracing.braintrust, "start_span", boom)

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ) as trace:
        trace.log(output={"text": "ok"})

    assert trace.permalink() is None


def test_turn_span_initial_log_failure_keeps_span_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    def start_span_with_broken_log(**kwargs: Any) -> FakeSpan:
        span = FakeSpan()
        span.start_kwargs = kwargs
        span.log_error = RuntimeError("log down")
        spans.append(span)
        return span

    monkeypatch.setattr(tracing.braintrust, "start_span", start_span_with_broken_log)

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ) as trace:
        trace.log(output={"text": "ok"})

    assert len(spans) == 1
    span = spans[0]
    # начальный log упал, но спан живой: хэндл рабочий, спан закрыт и снят с current
    assert trace.permalink() == span.permalink_value
    assert span.ended == 1
    assert span.calls == ["set_current", "unset_current", "end"]


def test_turn_span_records_base_exception_error(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        with tracing.turn_span(
            agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
        ):
            raise asyncio.CancelledError()

    assert spans[0].events[-1] == {"error": "CancelledError"}
    assert spans[0].ended == 1
    assert spans[0].calls == ["set_current", "unset_current", "end"]


def test_turn_span_uses_environment_from_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch, environment="production-test")

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ):
        pass

    assert spans[0].events[0]["metadata"]["environment"] == "production-test"


def test_turn_span_does_not_construct_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    spans = _enable_tracing(monkeypatch)

    class BoomSettings:
        def __init__(self, *_: Any, **__: Any) -> None:
            raise AssertionError("Settings must not be constructed during a turn")

    monkeypatch.setattr(tracing, "Settings", BoomSettings)

    with tracing.turn_span(
        agent_id=uuid4(), turn_id="t1", peer="chat", model="m", input=None
    ) as trace:
        trace.log(output={"text": "ok"})

    assert trace.permalink() == spans[0].permalink_value
    assert spans[0].ended == 1
```

Тесты закрепляют current-контракт спана: `set_current` вызывается ровно один раз, `unset_current` — строго до `end`, и на обычном пути (`test_turn_span_logs_input_metadata_and_output`), и на error-путях (`test_turn_span_records_error_and_reraises`, `test_turn_span_records_base_exception_error`). Без этих проверок `turn_span` снова может «забыть» сделать спан current (контекст ставит только `Span.__enter__`/`set_current`, а не `set_current=True` у `start_span`) или не закрыть его.

В блоке выше — 8 из 10 тестов `turn_span`; при реализации добавлены ещё два: `test_turn_span_is_current_span_for_real_braintrust_machinery` (интеграционный: настоящая span-context машинерия SDK, без сети) и `test_turn_span_set_current_base_exception_still_closes_span` (ревью-фикс: `BaseException` внутри `set_current` не оставляет спан незакрытым).

- [ ] **Step 2: Запусти тест — он должен упасть**

Run: `uv run pytest tests/integrations/test_tracing.py -q`
Expected: FAIL — `AttributeError: module 'mimic42.integrations.tracing' has no attribute 'turn_span'`.

- [ ] **Step 3: Реализуй `turn_span` и `TurnTrace`**

В `src/mimic42/integrations/tracing.py` добавь новые импорты:

```python
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from braintrust.span_types import SpanTypeAttribute
```

и после `reset_tracing` — сами класс и функцию:

```python
class TurnTrace:
    """Хэндл корневого спана хода; безопасен при выключенном трейсинге.

    ``log`` зовётся внутри блока ``turn_span``: после выхода из блока спан
    закрыт, и из хэндла доступен только ``permalink``.
    """

    def __init__(self, span: Any | None) -> None:
        self._span = span

    def log(self, **event: Any) -> None:
        if self._span is None:
            return
        try:
            self._span.log(**event)
        except Exception:
            logger.warning("Braintrust span log failed", exc_info=True)

    def permalink(self) -> str | None:
        if self._span is None:
            return None
        try:
            return self._span.permalink()
        except Exception:
            logger.warning("Braintrust permalink failed", exc_info=True)
            return None


@contextmanager
def turn_span(
    *,
    agent_id: UUID | str,
    turn_id: str,
    peer: str,
    model: str,
    input: Any,
) -> Iterator[TurnTrace]:
    """Корневой спан хода агента.

    Спан делается current на время хода, поэтому вложенные спаны LangChain
    (модель, инструменты, шаги графа) из BraintrustCallbackHandler
    прикрепляются к нему автоматически.

    ``start_span(..., set_current=True)`` лишь запоминает флаг: контекст ставит
    только ``with``-блок (``Span.__enter__`` → ``Span.set_current``), поэтому
    current-пара ``set_current``/``unset_current`` управляется здесь явно.
    """
    if not tracing_enabled():
        yield TurnTrace(None)
        return
    try:
        span = braintrust.start_span(name=f"turn {peer}", type=SpanTypeAttribute.TASK)
    except Exception:
        logger.warning("Braintrust start_span failed", exc_info=True)
        yield TurnTrace(None)
        return
    trace = TurnTrace(span)
    try:
        try:
            span.set_current()
        except Exception:
            logger.warning("Braintrust span set_current failed", exc_info=True)
        try:
            span.log(
                input=input,
                metadata={
                    "agent_id": str(agent_id),
                    "turn_id": turn_id,
                    "peer": peer,
                    "model": model,
                    "environment": _environment,
                },
            )
        except Exception:
            logger.warning("Braintrust initial span log failed", exc_info=True)
        yield trace
    except BaseException as exc:
        trace.log(error=str(exc) or type(exc).__name__)
        raise
    finally:
        try:
            span.unset_current()
        except Exception:
            logger.warning("Braintrust span unset_current failed", exc_info=True)
        try:
            span.end()
        except Exception:
            logger.warning("Braintrust span end failed", exc_info=True)
```

Обязательные свойства этого варианта (закреплены тестами Task 3, Step 1):

- `start_span` и начальный `span.log` — в **разных** try: упавший начальный log не
  маскируется под «start_span failed» и не оставляет спан незакрытым.
- `set_current()`/`unset_current()` вызываются явно и именно в таком порядке
  вокруг `yield`; `end()` остаётся в `finally`.
- Ошибка тела (включая `BaseException`: `asyncio.CancelledError`, `GeneratorExit`)
  пишется на спан как `error`, генератор при этом корректно закрывается.
- `environment` берётся из `_environment`, закэшированного в `setup_tracing`
  (Task 2): в ходе `Settings()` не конструируется.

- [ ] **Step 4: Запусти тест — он должен пройти**

Run: `uv run pytest tests/integrations/test_tracing.py -q`
Expected: PASS — все тесты файла зелёные (10 тестов `turn_span`, включая проверки `set_current`/`unset_current`).

- [ ] **Step 5: Проверь линтеры и закоммить**

Run:
```bash
uv run ruff check .
uv run ty check
git add src/mimic42/integrations/tracing.py tests/integrations/test_tracing.py
git commit -m "feat: turn span for Braintrust tracing (issue #92)"
```
Expected: `All checks passed!` дважды, коммит создан.

---

### Task 4: Включение трейсинга в lifespan приложения

**Files:**
- Modify: `src/mimic42/api/app.py`
- Test: `tests/api/test_app_tracing.py`

- [ ] **Step 1: Напиши падающий тест**

Создай `tests/api/test_app_tracing.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from mimic42.api.app import create_app
from mimic42.config import Settings


async def test_lifespan_sets_up_and_flushes_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, list[Any]] = {"setup": [], "flush": []}

    def fake_setup(settings: Settings) -> None:
        calls["setup"].append(settings)

    def fake_flush() -> None:
        calls["flush"].append(True)

    monkeypatch.setattr("mimic42.api.app.setup_tracing", fake_setup)
    monkeypatch.setattr("mimic42.api.app.flush_tracing", fake_flush)

    app = create_app(settings=Settings(database_connection_string=None))
    async with app.router.lifespan_context(app):
        assert len(calls["setup"]) == 1
        assert calls["flush"] == []

    assert calls["flush"] == [True]
```

- [ ] **Step 2: Запусти тест — он должен упасть**

Run: `uv run pytest tests/api/test_app_tracing.py -q`
Expected: FAIL — `AttributeError: <module 'mimic42.api.app'> has no attribute 'setup_tracing'`.

- [ ] **Step 3: Подключи модуль к lifespan**

В `src/mimic42/api/app.py`:
1. Добавь импорт к остальным импортам mimic42:

```python
from mimic42.integrations.tracing import flush_tracing, setup_tracing
```

2. В `lifespan` первой строкой блока `try:` (перед `# Restore running agents from database after restart`):

```python
            setup_tracing(app_settings)
```

3. Первой строкой блока `finally:` (перед `await _get_agent_manager(app).shutdown()`):

```python
            flush_tracing()
```

- [ ] **Step 4: Запусти тест — он должен пройти**

Run: `uv run pytest tests/api/test_app_tracing.py -q`
Expected: PASS.

- [ ] **Step 5: Убедись, что соседние слои не сломаны**

Run: `uv run pytest tests/api -q`
Expected: PASS (все тесты api-слоя).

- [ ] **Step 6: Проверь линтеры и закоммить**

Run:
```bash
uv run ruff check .
uv run ty check
git add src/mimic42/api/app.py tests/api/test_app_tracing.py
git commit -m "feat: enable Braintrust tracing in app lifespan (issue #92)"
```
Expected: `All checks passed!` дважды, коммит создан.

---

### Task 5: Корневой спан в `_take_turn`, событие `turn.completed`, `trace_url`

**Files:**
- Modify: `src/mimic42/core/agent_runtime.py`
- Test: `tests/core/test_agent_runtime_tracing.py`

- [ ] **Step 1: Напиши падающий тест**

Создай `tests/core/test_agent_runtime_tracing.py`:

```python
from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest

from mimic42.config import Settings
from mimic42.core.agent_runtime import (
    AgentRuntimeConfig,
    AgentTrigger,
    MimicAgentRuntime,
)
from mimic42.integrations import tracing
from mimic42.testing.telegram import FakeTelegramAccount, FakeTelegramClient

TRACE_URL = "https://braintrust.dev/app/p/mimic42/t/turn-1"


class FakeSpan:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.ended = 0

    def log(self, **event: Any) -> None:
        self.events.append(event)

    def end(self) -> None:
        self.ended += 1

    def permalink(self) -> str:
        return TRACE_URL


class FakeLangChainAgent:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def aclose(self) -> None:
        return None

    async def ainvoke(
        self,
        input_data: dict[str, object],
        context: object | None = None,
    ) -> dict[str, object]:
        if self.fail:
            raise RuntimeError("model exploded")
        return {
            "messages": [{"role": "assistant", "content": "reply"}],
            "structured_response": {
                "text": "reply",
                "send_any_message": True,
                "reply_to": None,
            },
        }


class FakeMemoryService:
    async def build_messages(
        self, *, agent_id: UUID, peer: str, user_text: str
    ) -> list[dict[str, Any]]:
        return [{"role": "user", "content": user_text}]

    async def save_messages(self, **_: Any) -> None:
        return None


class FakeActivity:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, **event: Any) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _clean_tracing_state() -> Iterator[None]:
    tracing.reset_tracing()
    yield
    tracing.reset_tracing()


def make_config() -> AgentRuntimeConfig:
    return AgentRuntimeConfig(
        agent_id=uuid4(),
        owner_id=uuid4(),
        telegram_session_string="sessions/test-agent",
        telegram_api_id=12345,
        telegram_api_hash="hash",
        llm_model="openrouter/free",
        system_prompt="Base system prompt",
        soul_prompt="Quiet direct style",
    )


async def _run_turn(
    monkeypatch: pytest.MonkeyPatch, *, fail: bool = False, tracing_on: bool = True
) -> FakeActivity:
    if tracing_on:
        monkeypatch.setattr(tracing.braintrust, "init_logger", lambda **_: object())
        monkeypatch.setattr(tracing, "set_global_handler", lambda _handler: None)
        monkeypatch.setattr(tracing, "BraintrustCallbackHandler", lambda: "handler")
        monkeypatch.setattr(tracing.braintrust, "start_span", lambda **_: FakeSpan())
        tracing.setup_tracing(
            Settings(_env_file=None, braintrust_api_key="bt-key")
        )
    runtime = MimicAgentRuntime(
        config=make_config(),
        telegram_client=FakeTelegramClient(FakeTelegramAccount()),
        langchain_agent=FakeLangChainAgent(fail=fail),
        memory_service=FakeMemoryService(),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    )
    activity = FakeActivity()
    runtime._activity = activity  # ty: ignore[unresolved-attribute]
    await runtime.start()
    if fail:
        with pytest.raises(RuntimeError, match="model exploded"):
            await runtime.trigger_message(AgentTrigger(peer="chat", text="hi"))
    else:
        await runtime.trigger_message(AgentTrigger(peer="chat", text="hi"))
    return activity


async def test_turn_completed_event_carries_trace_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = await _run_turn(monkeypatch)

    completed = [e for e in activity.events if e["event_type"] == "turn.completed"]
    assert len(completed) == 1
    payload = completed[0]["payload"]
    assert payload["peer"] == "chat"
    assert payload["trace_url"] == TRACE_URL
    assert isinstance(payload["turn_id"], str) and payload["turn_id"]
    assert completed[0]["status"] == "succeeded"


async def test_turn_failed_event_carries_trace_url(monkeypatch: pytest.MonkeyPatch) -> None:
    activity = await _run_turn(monkeypatch, fail=True)

    failed = [e for e in activity.events if e["event_type"] == "turn.failed"]
    assert len(failed) == 1
    assert failed[0]["payload"]["trace_url"] == TRACE_URL
    assert failed[0]["payload"]["error_code"] == "RuntimeError"
    assert not [e for e in activity.events if e["event_type"] == "turn.completed"]


async def test_events_have_no_trace_url_without_tracing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activity = await _run_turn(monkeypatch, tracing_on=False)

    turn_events = [
        e for e in activity.events if e["event_type"] in {"turn.completed", "turn.failed"}
    ]
    assert turn_events, "ход должен записать событие уровня turn"
    for event in turn_events:
        assert "trace_url" not in event["payload"]
```

- [ ] **Step 2: Запусти тест — он должен упасть**

Run: `uv run pytest tests/core/test_agent_runtime_tracing.py -q`
Expected: FAIL — `AssertionError: ход должен записать событие уровня turn` (события
`turn.completed` ещё нет; тесты с трейсингом падают по `trace_url`).

- [ ] **Step 3: Оберни ход в `turn_span`**

В `src/mimic42/core/agent_runtime.py`:

1. Добавь импорт рядом с остальными импортами mimic42:

```python
from mimic42.integrations.tracing import TurnTrace, turn_span
```

2. Переименуй текущий `_take_turn` в `_take_turn_inner` с новыми параметрами и убери из
   него создание `turn_id` (теперь он приходит параметром):

```python
    async def _take_turn_inner(
        self,
        trigger: AgentTrigger,
        *,
        turn_id: str,
        trace: TurnTrace,
        started_at: datetime,
    ) -> AgentTriggerResult:
        """Сам ход: модель, отправка ответа, запись. Вызывается под trigger lock."""
        # Вызов мог ждать lock, пока предыдущий ход отозвал сессию.
        if self._session_revoked:
            raise TelegramAuthorizationRequired(REVOKED_SESSION_MESSAGE)
        logger.debug(f"Processing message from {trigger.peer}: {trigger.text[:100]}")
        turn_context = TurnContext(turn_id=turn_id, peer=trigger.peer)
```

(строка `turn_id = str(uuid4())` удаляется, весь остальной код метода остаётся как был).

3. Над `_take_turn_inner` добавь новый `_take_turn`:

```python
    async def _take_turn(self, trigger: AgentTrigger) -> AgentTriggerResult:
        """Ход целиком под корневым спаном трейсинга (issue #92)."""
        turn_id = str(uuid4())
        started_at = datetime.now(UTC)
        with turn_span(
            agent_id=self.config.agent_id,
            turn_id=turn_id,
            peer=trigger.peer,
            model=self.config.llm_model,
            input={
                "peer": trigger.peer,
                "text": trigger.text,
                "reply_to": trigger.reply_to_message_id,
                "media": bool(trigger.media),
            },
        ) as trace:
            return await self._take_turn_inner(
                trigger,
                turn_id=turn_id,
                trace=trace,
                started_at=started_at,
            )
```

- [ ] **Step 4: Прокинь `trace_url` в `turn.failed`**

В `_take_turn_inner` блок `except Exception as e:` (тот, что пишет `turn.failed`) замени на:

```python
        except Exception as e:
            logger.error(f"Error invoking agent: {e}", exc_info=True)
            payload: dict[str, Any] = {
                "turn_id": turn_id,
                "peer": trigger.peer,
                "error_code": type(e).__name__,
            }
            trace_url = trace.permalink()
            if trace_url:
                payload["trace_url"] = trace_url
            await self._record_event(
                event_type="turn.failed",
                status="failed",
                payload=payload,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
```

- [ ] **Step 5: Запиши `turn.completed` перед возвратом результата**

В конце `_take_turn_inner`, перед `return AgentTriggerResult(`:

```python
        trace.log(output={"text": response_text, "sent": send_any})
        completed_payload: dict[str, Any] = {"turn_id": turn_id, "peer": trigger.peer}
        completed_trace_url = trace.permalink()
        if completed_trace_url:
            completed_payload["trace_url"] = completed_trace_url
        await self._record_event(
            event_type="turn.completed",
            status="succeeded",
            payload=completed_payload,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
```

- [ ] **Step 6: Запусти тест — он должен пройти**

Run: `uv run pytest tests/core/test_agent_runtime_tracing.py -q`
Expected: PASS (3 теста).

- [ ] **Step 7: Убедись, что рантайм не сломан**

Run: `uv run pytest tests/core tests/integrations tests/testing -q`
Expected: PASS (все существующие тесты).

- [ ] **Step 8: Проверь линтеры и закоммить**

Run:
```bash
uv run ruff check .
uv run ty check
git add src/mimic42/core/agent_runtime.py tests/core/test_agent_runtime_tracing.py
git commit -m "feat: trace agent turns and link traces from events (issue #92)"
```
Expected: `All checks passed!` дважды, коммит создан.

---

### Task 6: Фронтенд — событие `turn.completed` и ссылка «Трейс»

Перед правкой UI загрузи скилл `impeccable` (AGENTS.md требует его для всего
фронтенда) и держись существующих паттернов `ActionRow`.

**Files:**
- Modify: `frontend/src/lib/activity/eventCatalog.ts`
- Modify: `frontend/src/lib/activity/normalize.ts`
- Modify: `frontend/src/components/activity/ActionRow.tsx`
- Test: `frontend/src/__tests__/activity-trace-link.test.ts`, `frontend/src/__tests__/action-row-trace-link.test.tsx`

- [ ] **Step 1: Напиши падающие тесты**

Создай `frontend/src/__tests__/activity-trace-link.test.ts`:

```typescript
import { describe, expect, test } from 'bun:test';
import { buildActivityFeed, type EventLike } from '@/lib/activity/normalize';
import { getEventMeta } from '@/lib/activity/eventCatalog';

const evt = (over: Partial<EventLike>): EventLike => ({
  id: 'e1',
  event_type: 'turn.completed',
  status: 'succeeded',
  created_at: '2026-09-26T10:00:05Z',
  ...over,
});

describe('trace links', () => {
  test('turn.completed has a Russian label', () => {
    expect(getEventMeta('turn.completed')?.ru).toBe('Ход завершён');
  });

  test('payload.trace_url becomes action.traceUrl', () => {
    const [item] = buildActivityFeed(
      [],
      [
        evt({
          payload: {
            turn_id: 't1',
            peer: '123',
            trace_url: 'https://braintrust.dev/app/p/mimic42/t/turn-1',
          },
        }),
      ],
    );

    expect(item.actions[0]?.traceUrl).toBe('https://braintrust.dev/app/p/mimic42/t/turn-1');
  });

  test('actions without trace_url have traceUrl null', () => {
    const [item] = buildActivityFeed([], [evt({ payload: { turn_id: 't1', peer: '123' } })]);

    expect(item.actions[0]?.traceUrl).toBeNull();
  });
});
```

Создай `frontend/src/__tests__/action-row-trace-link.test.tsx`:

```typescript
import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/react';
import { ActionRow } from '@/components/activity/ActionRow';
import type { ActivityAction } from '@/lib/activity/normalize';

const action = (over: Partial<ActivityAction>): ActivityAction => ({
  id: 'a1',
  eventType: 'turn.completed',
  status: 'succeeded',
  label: 'Ход завершён',
  hint: null,
  args: null,
  result: null,
  startedAt: null,
  completedAt: null,
  traceUrl: null,
  ...over,
});

describe('ActionRow trace link', () => {
  test('ссылка «Трейс» ведёт на trace_url в новой вкладке', () => {
    render(
      <ActionRow
        action={action({ traceUrl: 'https://braintrust.dev/app/p/mimic42/t/turn-1' })}
      />,
    );

    const link = screen.getByRole('link', { name: /Трейс/ });
    expect(link.getAttribute('href')).toBe('https://braintrust.dev/app/p/mimic42/t/turn-1');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noreferrer');
  });

  test('без traceUrl ссылки нет', () => {
    render(<ActionRow action={action()} />);

    expect(screen.queryByRole('link')).toBeNull();
  });
});
```

- [ ] **Step 2: Запусти тесты — они должны упасть**

Run: `cd frontend && bun test src/__tests__/activity-trace-link.test.ts src/__tests__/action-row-trace-link.test.tsx`
Expected: FAIL — `traceUrl` не существует в `ActivityAction`, `getEventMeta('turn.completed')` возвращает `null`, ссылки нет.

- [ ] **Step 3: Добавь событие в каталог**

В `frontend/src/lib/activity/eventCatalog.ts` добавь импорт `CheckCircle2` в список
импортов `lucide-react` и строку в `EVENT_CATALOG` (после `'turn.failed'`):

```typescript
  'turn.completed': { ru: 'Ход завершён', icon: CheckCircle2 },
```

- [ ] **Step 4: Прокинь `traceUrl` в `ActivityAction`**

В `frontend/src/lib/activity/normalize.ts`:

1. В интерфейс `ActivityAction` добавь поле (после `completedAt`):

```typescript
  traceUrl: string | null;
```

2. В функции `toAction` вычисли значение (после `const payload = event.payload ?? null;`):

```typescript
  const traceUrl = typeof payload?.trace_url === 'string' ? (payload.trace_url as string) : null;
```

и добавь `traceUrl,` в возвращаемый объект (после `completedAt`).

- [ ] **Step 5: Нарисуй ссылку в `ActionRow`**

В `frontend/src/components/activity/ActionRow.tsx`:

1. Добавь `ExternalLink` в импорт из `lucide-react`.
2. Между блоком `action.hint` и блоком `duration` вставь:

```tsx
      {action.traceUrl && (
        <a
          href={action.traceUrl}
          target="_blank"
          rel="noreferrer"
          className="shrink-0 inline-flex items-center gap-1 text-[11px] text-plasma-400 hover:text-plasma-300 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-plasma-500 rounded-[2px]"
        >
          Трейс
          <ExternalLink className="h-3 w-3" />
        </a>
      )}
```

- [ ] **Step 6: Запусти тесты — они должны пройти**

Run: `cd frontend && bun test src/__tests__/activity-trace-link.test.ts src/__tests__/action-row-trace-link.test.tsx`
Expected: PASS (5 тестов).

- [ ] **Step 7: Прогони весь фронтенд**

Run:
```bash
cd frontend && bunx tsc --noEmit && bun test
```
Expected: `tsc` без ошибок, все тесты PASS.

- [ ] **Step 8: Закоммить**

Run:
```bash
git add frontend/src/lib/activity/eventCatalog.ts frontend/src/lib/activity/normalize.ts \
  frontend/src/components/activity/ActionRow.tsx \
  frontend/src/__tests__/activity-trace-link.test.ts \
  frontend/src/__tests__/action-row-trace-link.test.tsx
git commit -m "feat(frontend): link Braintrust traces in activity feed (issue #92)"
```
Expected: коммит создан.

---

### Task 7: README и финальная проверка

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Добавь раздел в README**

В `README.md` после раздела про переменные окружения (после блока с `SECRET_KEY`):

```markdown
## Tracing (Braintrust)

Трейсинг ходов агента выключен по умолчанию и включается ключом:

```bash
BRAINTRUST_API_KEY=...        # ключ проекта Braintrust
BRAINTRUST_PROJECT=Mimic42    # Prod и Dev держат разные проекты
```

С ключом каждый ход агента попадает в Braintrust одним trace: корневой спан `turn`
(входящее сообщение, ответ, `agent_id`, `turn_id`, `peer`, модель) и под ним вызовы
модели (токены, латентность) и телеграм-инструменты. События `turn.completed` и
`turn.failed` в дашборде несут `trace_url` — ссылку прямо в трейс.

Без ключа модуль трейсинга — no-op: агент работает как раньше, ничего никуда не
отправляется. Сбои Braintrust не роняют ход агента.

Ручная проверка: положи `BRAINTRUST_API_KEY` в `.env`, запусти агента в Dev, отправь
ему сообщение и открой проект в UI Braintrust — должен появиться trace хода со спанами
`turn`, LLM-вызова и инструментов.
```

- [ ] **Step 2: Финальный прогон бэкенда**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run ty check
```
Expected: `379 + новые тесты passed`, `All checks passed!` дважды.

- [ ] **Step 3: Финальный прогон фронтенда**

Run:
```bash
cd frontend && bunx tsc --noEmit && bun test
```
Expected: без ошибок, все тесты PASS.

- [ ] **Step 4: Ручная живая проверка (если есть ключ)**

1. Положи `BRAINTRUST_API_KEY` и `BRAINTRUST_PROJECT` в `.env`.
2. Запусти бэкенд и агента в Dev, отправь агенту сообщение.
3. В UI Braintrust открой проект: есть trace с спаном `turn`, LLM-спаном (токены) и
   спанами инструментов.
4. В дашборде Mimic42 в ленте активности у события «Ход завершён» ссылка «Трейс»
   открывает этот trace.

Expected: trace виден, ссылка работает. Если ключа нет — шаги пропускаются,
остальные проверки достаточны для PR.

- [ ] **Step 5: Закоммить README и запушь ветку**

Run:
```bash
git add README.md
git commit -m "docs: Braintrust tracing section in README (issue #92)"
git push -u origin feat/issue-92-tracing
```
Expected: ветка запушена.

- [ ] **Step 6: Создай PR и доведи до зелёного CI**

Создай PR (`Closes #92`), затем: `gh pr checks <номер> --watch`; при падении —
`gh run view <id> --log-failed`, почини, допушь. Дождись `MERGEABLE` / `CLEAN`.
