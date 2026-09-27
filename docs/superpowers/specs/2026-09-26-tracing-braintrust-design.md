# Дизайн: трейсинг агента в Braintrust

Issue: https://github.com/42-Z/Mimic42/issues/92
Дата: 2026-09-26

## Цель

Видеть в Braintrust каждый ход мимика целиком: что пришло, что модель ответила, какие
инструменты вызывались, сколько токенов потрачено и где упало. Из карточки агента в
дашборде — переход по ссылке прямо в трейс хода. Трейсинг выключен по умолчанию и
включается одним env-ключом; агент без ключа работает ровно как раньше.

## Контекст (по коду и документации)

- Ход агента: `_take_turn` (`src/mimic42/core/agent_runtime.py`) строит контекст
  (`build_messages`), вызывает `self._langchain_agent.ainvoke(...)`, отправляет ответ и
  пишет события `turn.completed` / `turn.failed` через `_record_event`.
- Модель и инструменты: `build_langchain_agent`
  (`src/mimic42/integrations/langchain_agent.py`) собирает `create_agent` из LangChain v1
  поверх LangGraph; middleware — `ModelCallLimitMiddleware`, `ActivityMiddleware`,
  `TokenUsageMiddleware` (последний уже считает токены в `agent_token_usage`).
- Braintrust для LangChain: `BraintrustCallbackHandler` + `set_global_handler` — глобальный
  обработчик, который подхватывает все вызовы. Работает с LangGraph; пишет спаны графа и
  нод, LLM-вызовов (промпт, ответ, токены `prompt`/`completion`/`cached`, латентность),
  инструментов (аргументы и результат), ошибки на упавший спан
  (https://braintrust.dev/docs/integrations/sdk-integrations/langchain,
  https://braintrust.dev/docs/integrations/agent-frameworks/langgraph).
- Python SDK: `braintrust.init_logger(project=..., api_key=...)` — один раз на старте;
  `start_span()` — корневой спан хода (вложенные спаны и traced LLM-вызовы прикрепляются к
  нему, пока он current); `span.log()`; `span.permalink()` — ссылка на трейс
  (https://braintrust.dev/docs/sdks/python/api-reference).
- Ключ: `BRAINTRUST_API_KEY` SDK подхватывает из окружения сам; логи шлются батчами в фоне
  (`async_flush=True` по умолчанию), `flush()` допрашивает очередь
  (https://braintrust.dev/docs/sdks/python/install-and-instrument).
- Конфиг приложения — `Settings` (pydantic-settings, `src/mimic42/config.py`); env-имена
  фиксируются в `.env.example`.
- Слой core → integrations в репо уже принят (`core/token_usage.py` импортирует
  `integrations.database_models`), поэтому прямой импорт модуля трейсинга из
  `agent_runtime` допустим.
- Мультиарендность: `AgentManager` держит несколько рантаймов в одном event loop, ходы
  идут параллельно; вложенные спаны изолируются contextvars, у каждого хода свой
  `turn_id` (uuid4).

## Решение

### 1. Включение и конфигурация

- `Settings` (`src/mimic42/config.py`):
  - `braintrust_api_key: str | None` (env `BRAINTRUST_API_KEY`);
  - `braintrust_project: str = "Mimic42"` (env `BRAINTRUST_PROJECT`).
  Трейсинг включён, когда задан ключ. Prod и Dev заводят разные проекты
  (`"Mimic42 Prod"` / `"Mimic42 Dev"`).
- Зависимость `braintrust` в `pyproject.toml`.
- `.env.example`: новый блок (комментарий + `BRAINTRUST_API_KEY=` и
  `BRAINTRUST_PROJECT=Mimic42`); README — абзац «Трейсинг»: как включить и проверить.
- Старт приложения (`main.py`, lifespan): `setup_tracing(settings)` —
  `braintrust.init_logger(project=settings.braintrust_project, api_key=...)` и
  `set_global_handler(BraintrustCallbackHandler())`. На остановке — best-effort
  `braintrust.flush()`.

### 2. Структура трейса

Каждый ход агента — один trace:

- **Корневой спан `turn`** (type `task`): input — входящее сообщение (`peer`, `text`,
  признаки reply/медиа), output — текст ответа агента и `sent` — факт доставки
  (`sent_message is not None`, а не намерение `send_any_message`); `sent: true` означает
  «ответ доставлен целиком»: если первая часть длинного ответа ушла, а вторая упала —
  `sent: false`; metadata — `agent_id`, `turn_id`,
  `peer`, модель (`AgentRuntimeConfig.llm_model`), `environment` (`Settings.environment`,
  модуль трейсинга берёт его из `Settings` сам). Исключение хода пишется на этот спан.
- **Дочерние спаны** из `BraintrustCallbackHandler` (вкладываются автоматически): шаги
  графа LangGraph, каждый LLM-вызов (сообщения промпта, ответ, токены, латентность),
  каждый инструмент (имя, аргументы, результат) — то есть все телеграм-инструменты.
- В payload событий **`turn.completed`** (новый тип события на успешный исход хода;
  миграция БД не нужна — `agent_events.event_type` это `text`) и **`turn.failed`**
  добавляется **`trace_url`** — `span.permalink()`, чтобы из дашборда прыгать в трейс
  одним кликом. При выключенном трейсинге `trace_url` в payload не попадает.
  `status="succeeded"` у `turn.completed` означает «конвейер хода завершён», а не
  «ответ доставлен»: сбой доставки фиксируется событием `message.send_failed`, а факт
  доставки — полем `output.sent` корневого спана.
  Фронтенд: запись `turn.completed` в каталог событий и ссылка «Трейс» в строке
  события ленты активности.

### 3. Точки интеграции

- Новый модуль `src/mimic42/integrations/tracing.py` — вся работа с Braintrust в одном
  месте:
  - `setup_tracing(settings)` — идемпотентно: без ключа ничего не делает; с ключом —
    `init_logger` + `set_global_handler(BraintrustCallbackHandler())`;
  - `tracing_enabled()` — признак «трейсинг включён»;
  - `turn_span(*, agent_id, turn_id, peer, model, input)` —
    async-контекстный менеджер корневого спана хода; возвращает хэндл с `log(...)`
    (прокси к `span.log`) и `permalink()`; при выключенном трейсинге — no-op-хэндл с тем
    же интерфейсом.
- `src/mimic42/core/agent_runtime.py` (`_take_turn`): ход обёрнут в `turn_span(...)`;
  ответ агента логируется output-ом спана; в payload обоих исходов
  (`turn.completed`, `turn.failed`) кладётся `trace_url`.
- `src/mimic42/integrations/langchain_agent.py` **не меняется**: колбэки подхватываются
  глобально через `set_global_handler`, `create_agent` и `ainvoke` остаются как есть.
- `src/mimic42/main.py`: вызов `setup_tracing` на старте, `flush()` на остановке.

### 4. Ошибки и краевые случаи

- Ключа нет → всё выключено: `braintrust` не вызывается ни разу, поведение агента не
  меняется.
- Некорректный ключ / Braintrust недоступен → `setup_tracing` ловит исключения и пишет
  warning; агент продолжает работать без трейсинга. Отправка логов идёт в фоне с
  ретраями и не роняет ход: `turn_span` — best-effort, ошибки трейсинга не пробрасываются
  в ход.
- Остановка приложения → `flush()` с коротким таймаутом, не задерживает shutdown.
- Параллельные ходы нескольких агентов не перемешиваются: спаны вложены по contextvars,
  у каждого хода свой `turn_id`.
- Дубликаты исключены: `setup_tracing` идемпотентен (повторный вызов не плодит
  обработчиков).

## Проверка

- `tests/integrations/test_tracing.py` и `tests/core/test_agent_runtime_tracing.py`
  (без сети; `braintrust` подменяется фейком через monkeypatch):
  - без ключа: `setup_tracing` — no-op, `turn_span` возвращает no-op-хэндл, ход проходит;
  - с ключом: `init_logger` вызван с нашими `project`/`api_key`, `set_global_handler`
    получил `BraintrustCallbackHandler`;
  - `turn_span` пишет input и metadata (`agent_id`, `turn_id`, `peer`, модель,
    `environment`) и output ответа;
  - исключение хода пишется на спан и пробрасывается наружу;
  - `trace_url` попадает в payload `turn.completed` и `turn.failed`.
- Существующие слои не затрагиваются: `uv run pytest` остаётся зелёным, `ruff` и `ty`
  чистые.
- Команды: `uv run pytest`, `uv run ruff check .`, `uv run ty check`.
- Ручная проверка: `BRAINTRUST_API_KEY` в `.env`, один ход агента в Dev, в UI Braintrust
  виден trace хода (спан `turn`, LLM-спаны, инструменты, токены), ссылка `trace_url` из
  события открывает этот трейс.

## Вне скоупа

- Маскирование текстов (`set_masking_function`), редакция PII: по решению тексты
  сообщений и промпты уходят в SaaS как есть.
- Эвалы, промпт-плейграунд, алерты и дашборды самого Braintrust.
- Свой UI трейсов внутри дашборда Mimic42 (максимум — ссылка `trace_url`).
- Трейсинг Mem0-запросов и сборки контекста (`build_messages`).
- Sampling, настройки ретеншна, cost-аналитика по деньгам.
- Отдельный pytest-маркер для живых проверок Braintrust (проверяем вручную по README).
