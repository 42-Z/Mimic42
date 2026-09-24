# Rewrite AGENTS.md Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переписать `AGENTS.md` (и синхронизировать `CLAUDE.md`), сохранив видение и правила качества проекта, добавив фактический стек, карту структуры, команды разработки/pre-PR, конвенции кода, bash-правила и анти-паттерны агента — в одном файле, без вложенных уровней (проект один, монорепы нет).

**Architecture:** Один корневой `AGENTS.md` остаётся единственным входом для агента. Секции Modrinth, переносимые в наш проект: «Стек», «Структура проекта» (таблица), «Команды» (dev + pre-PR, зеркалящие CI), «Конвенции», «Bash», «Анти-паттерны». Секции-наследники Modrinth, которые НЕ переносим: вложенные AGENTS.md, таблицы apps/packages монорепы, Turborepo/pnpm. Правила «Изучай документацию», «БД», «Баги», «Git» остаются с сохранением авторского тона, но с исправленными опечатками.

**Tech Stack:** Markdown, uv/Ruff/ty/pytest (backend), Bun/Next.js/Playwright (frontend), GitHub Actions CI как источник истины для pre-PR команд.

---

### Task 1: Подготовка ветки

**Files:**
- None modified (git только)

Контекст: текущая ветка `feat/unified-activity-tab` с незакоммиченными изменениями — переключаться на ней нельзя, изменения уедут в чужую ветку. Работаем в worktree от `main`.

- [ ] **Step 1: Обновить main**

```bash
git fetch origin main
```

Expected: выход без ошибок, `origin/main` обновлён.

- [ ] **Step 2: Создать worktree с веткой от main**

```bash
git worktree add /home/sasha42/vscode/Mimic42-agents-md -b docs/rewrite-agents-md origin/main
```

Expected: `Preparing worktree` + `Switched to a new branch 'docs/rewrite-agents-md'`.

- [ ] **Step 3: Переместить сессию в worktree**

Use `tools.opencode.session_move` (via `execute`) with `directory: /home/sasha42/vscode/Mimic42-agents-md`.

Expected: `{"sessionID": "...", "directory": "/home/sasha42/vscode/Mimic42-agents-md"}`.

---

### Task 2: Переписать AGENTS.md

**Files:**
- Modify: `AGENTS.md` (полная замена содержимого)

Документ — не код, TDD неприменим; проверка — Task 4 (команды из документа реально работают) + Task 5 (ревью).

- [ ] **Step 1: Записать новый `AGENTS.md` целиком**

```markdown
# Mimic 42

Максимально реалистичный ИИ-агент, который имитирует человека

Агент взаимодействует с миром через Telegram

Этот нейробот создан, чтобы полноценно и натурально управлять Telegram

## Задумка

### Агентская сторона

- Агент на LangChain с инструментами
- Долгосрочная память на Mem0
- Сессия целиком сохраняется в базу данных — сообщения и использования инструментов не теряются

Он должен общаться живо, как человек

Должен быть базовый промпт (объясняющий, что агент делает) + пользовательский (темперамент и стиль)

### Чат сторона

- Инструменты, которые релизуют ВСЕ функции для использования Telegram
- ТГ не через бота, а через юзербота на Telethon
- Задействовать каждый метод Telethon в качестве инструмента для агента

Необходимо сделать широкий спектр инструментов, чтобы нейросеть могла делать буквально все

### Дашборд сторона

- Приложение многопользовательское (каждый может создать своего агента)
- Веб-сайт с авторизацией
- Настраивается: характер (SOUL.md), API-токен и т.д.

Сначала идёт онбординг-воркфлоу, где пошагово задаётся характер и авторизация в сессию ТГ

Затем открывается статистика с действиями бота

## Стек

- Бэкенд: Python 3.13, FastAPI, SQLAlchemy 2.0 async, LangChain, Telethon, Mem0
- Фронтенд: Next.js 14 (App Router), TypeScript, Tailwind CSS, Bun
- Модели: OpenRouter (`OPENROUTER_API_KEY`, глобальная модель `openrouter/free`)
- База: Supabase Postgres, миграции через Supabase CLI
- Авторизация: Supabase JWT, проверяется локально через JWKS

## Структура проекта

| Путь | Назначение |
| --- | --- |
| `src/mimic42/api/` | FastAPI-приложение (`app.py`) и проверка Supabase JWT (`auth.py`) |
| `src/mimic42/core/` | Рантайм агента (`agent_runtime.py`), менеджер рантаймов (`manager.py`), онбординг, activity, память, шифрование сессий (`crypto.py`), каталог моделей |
| `src/mimic42/integrations/` | Telethon-клиент и Telegram-инструменты, LangChain-агент, Mem0, репозитории SQLAlchemy, OpenRouter-каталог |
| `src/mimic42/testing/` | Тестовый сервер и хелперы для e2e |
| `frontend/` | Дашборд на Next.js (источник правды — `frontend/src/app/`) |
| `supabase/migrations/` | SQL-миграции (Supabase CLI) |
| `tests/` | Pytest: `api/`, `core/`, `integrations/`, `integration/`, `testing/` |
| `docs/superpowers/plans/` | Планы реализации |

## Команды

### Бэкенд

```bash
uv sync --all-groups                                  # установка зависимостей
uv run uvicorn mimic42.main:app --reload              # dev-сервер на :8000
uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q   # обычный прогон (как в CI)
uv run ruff check .                                    # линт
uv run ruff format --check .                           # проверка формата
uv run ty check                                        # типы
```

### Фронтенд (внутри `frontend/`)

```bash
bun install --frozen-lockfile   # зависимости (скопируй .env.example → .env.local)
bun run dev                     # dev-сервер Next.js
bunx next lint                  # линт
bun run typecheck               # типы
bun test                        # юнит-тесты
bun run test:e2e                # Playwright e2e (нужны TEST_* переменные)
```

### Pre-PR

Перед открытием pull request прогони **полный** набор (это джобы CI `backend` и `frontend`; джобы `backend-db`, `e2e` и `migrations-drift` CI гонит отдельно на своих секретах):

- Бэкенд: `uv sync --locked --all-groups && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q`
- Фронтенд (в `frontend/`): `bun install --frozen-lockfile && bunx next lint && bun run typecheck && bun test`

Не запускай полный набор после каждого промпта пользователя — только когда пользователь собирается открывать PR или прямо просит.

## Правила

- Используй uv, Ruff и ty, Bun, Supabase CLI
- Обязательно читай документацию библиотек, с которыми работаешь
- Используй Git и делай изменения в отдельной ветке с последующим PR
- Делай коммиты сам

### Организация работы

GitHub Project: https://github.com/orgs/42-Z/projects/2/

Это центральное место организации рабочего процесса и хранения статусов заданий. Проверяй его при планировании работы и после завершения задач.

Когда берёшь задачу из issue — сразу назначь себя на неё (Assignees), чтобы было видно, кто за что отвечает.

### Git и коммиты

- Коммиты по Conventional Commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`, при необходимости со scope — `fix(activity): ...`
- Тема коммита на английском, одна строка
- После коммита и push проверяй CI (`gh pr checks`); не оставляй красный CI или заблокированный PR

### Поиск по документации

Всегда предпочитай чтение документации вместо инспекции через скрипты

Ты должен читать документацию по каждому методу, классу, свойству, которое используешь. Это не опция, это обязательство

Открывай сайт документации или llms.txt, а не просто используй разовый веб-поиск

Изучай документацию десятки раз на всех этапах: планирование, выполнение, проверка

Мастхевые ресурсы:

- https://bun.com/docs
- https://docs.langchain.com/oss/python/langchain/overview
- https://docs.mem0.ai/introduction
- https://docs.telethon.dev/en/stable/
- https://supabase.com/docs
- https://fastapi.tiangolo.com/
- https://docs.sqlalchemy.org/en/20/

### Конвенции кода

- Python: отступ 4 пробела, длина строки 100 (настраивает Ruff в `pyproject.toml`), правила линта `E, F, I, B, UP, ANN`
- TypeScript/React: отступ — как в соседнем коде файла; компоненты стилей через `cn()` (clsx + tailwind-merge)
- Комментарии: не используй «заголовочные» комментарии (`=== Хелперы ===`); пиши doc-комментарии, inline-комментарии — только когда без них код не понятен; код должен быть самодокументируемым
- Не создавай новых файлов вне исходного кода (bash-скрипты, SQL-файлы) без явного запроса

### Bash

- Не пайпь вывод через `head`, `tail`, `less`, `more` — не обрезай вывод фильтрами, читай его полностью
- Если нужно ограничить вывод — используй флаги самой команды: `git log -n 10`, а не `git log | head -10`
- Ошибки ищи в полном выводе: обрезанный пайпом лог — главная причина ненайденных причин ошибок

### БД

На сервере продакшн-база с реальными агентами, а на компьютере тестовая база, чтобы запущенные одновременно Мимики не мешали друг другу

Миграции и изменения надо делать с помощью Supabase CLI и скиллов Supabase

Тесты, требующие подключения к тестовой базе, помечены маркером `db` (CI гонит их отдельной джобой `backend-db` через `pytest -m db`); остальные тесты: `pytest -m "not db and not e2e and not real_tg and not real_llm"`; маркеры `e2e`, `real_tg`, `real_llm` — живые/сквозные тесты, для локального прогона их не запускай

Перед слиянием ветки разберись, как в этом репозитории устроены CI и деплой, и сделай выводы: что автоматизировано, а что остаётся на тебе

После слияния ветки выясни, что ещё требуется довести до конца — в первую очередь по базе данных — и доведи: сделай сама или скажи хозяину

### Живые тесты

Тесты `real_tg` ходят в настоящий Telegram через общие аккаунты: один проверяющий (сессия в `.env.test` и в секретах CI) и один мимик (сессия в Dev-базе). Если одну сессию одновременно подключить с двух машин, Telegram может её отозвать — так уже потерялся один проверяющий аккаунт

Поэтому прогон `real_tg` берёт замок — advisory lock в Dev-базе (`mimic42.testing.real_tg.lock`). Если замок занят, прогон сразу останавливается: дождись окончания чужого прогона, не обходи замок. Postgres снимает его сам, когда соединение закрывается, так что упавший прогон никого не блокирует

Скрипты, которые вручную подключаются к сессиям проверяющего или мимика, тоже берут этот замок через `RealTelegramLock`

### Баги

Если агент не работает, выбрасывается исключение или случается какое-то неожиданное поведение, их надо исправлять

Ты должен посмотреть логи, историю сессии, выяснить обстоятельства и понять, из-за чего происходит конкретная ошибка

Источником ошибки могли быть не только твои изменения, но и старые — всё надо приводить к рабочему состоянию

Не пытайся сделать заплатки или костыли, а решай всё окончательно

### Анти-паттерны

- Не говори «я это не ломал» / «проблема существовала раньше» — если проблема в тебе, просто исправь её
- Не перекладывай вину на чужой код и не предлагай пользователю чинить самому
- Не запускай полный pre-PR набор после каждого сообщения — только перед PR или по прямой просьбе

### UI

При работе с UI скилл Impeccable всегда
```

- [ ] **Step 2: Проверить, что файл записан полностью**

Run: `wc -l AGENTS.md && tail -3 AGENTS.md`
Expected: последняя строка — `При работе с UI скилл Impeccable всегда`, число строк ~170.

---

### Task 3: Заменить CLAUDE.md симлинком

`CLAUDE.md` сейчас — байтовая копия `AGENTS.md`, которая уже разошлась с источником (в main появились новые секции). Вместо синхронизации копий делаем `AGENTS.md` единственным источником правды, а `CLAUDE.md` — симлинком на него (git сохраняет симлинки, читатели следуют по ним).

- [ ] **Step 1: Заменить файл симлинком**

```bash
rm CLAUDE.md && ln -s AGENTS.md CLAUDE.md
```

- [ ] **Step 2: Проверить**

Run: `ls -la CLAUDE.md && head -1 CLAUDE.md`
Expected: `CLAUDE.md -> AGENTS.md`, первая строка `# Mimic 42`

---

### Task 4: Верификация команд из документа

Команды в AGENTS.md должны работать именно так, как записаны.

- [ ] **Step 1: Бэкенд-набор (в worktree)**

```bash
uv sync --locked --all-groups && uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -m "not db and not e2e and not real_tg and not real_llm" -W error -q
```

Expected: exit code 0, все пять шагов зелёные. Если что-то упало — это баг проекта, почини до коммита (правило «Баги»).

- [ ] **Step 2: Фронтенд-набор**

```bash
cd frontend && bun install --frozen-lockfile && bunx next lint && bun run typecheck && bun test
```

Expected: exit code 0.

- [ ] **Step 3: Проверить битые ссылки секции ресурсов**

Run: `grep -oE 'https://[^ )]+' AGENTS.md | while read u; do code=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 15 "$u"); echo "$code $u"; done`
Expected: все ответы `200` (или `403` для док, которые закрыты ботам — тогда заменить URL и перепроверить).

- [ ] **Step 4: Проверить, что старые опечатки исчезли**

Run: `grep -nE 'упралять|иммитирует|инструемнта|Приложениие|измненеия|кмпьютере|Дэшборд' AGENTS.md CLAUDE.md`
Expected: пустой вывод, exit code 1.

---

### Task 5: Коммит, push, PR, CI

- [ ] **Step 1: Коммит**

```bash
git add AGENTS.md CLAUDE.md
git commit -m "docs: rewrite AGENTS.md with stack, structure, commands and agent guardrails"
```

Expected: `[docs/rewrite-agents-md <sha>] docs: rewrite ...`, 2 files changed.

- [ ] **Step 2: Push**

```bash
git push -u origin docs/rewrite-agents-md
```

Expected: remote branch создан.

- [ ] **Step 3: Создать PR**

```bash
gh pr create --title "docs: rewrite AGENTS.md" --body "Rewrites AGENTS.md (and syncs CLAUDE.md): factual stack, project structure table, dev/pre-PR commands mirroring CI, code conventions, bash output rules, anti-patterns. Fixes typos and the broken Impeccable skill reference note. No nested AGENTS.md levels — single project."
```

Expected: URL PR.

- [ ] **Step 4: Проверить CI**

Run: `gh pr checks <PR number>`
Expected: все проверки зелёные. Если красные — `gh run view <run_id> --log-failed`, починить, закоммитить, push, повторить.

- [ ] **Step 5: Проверить состояние PR**

Run: `gh pr view <PR number> --json mergeable,mergeStateStatus`
Expected: `"mergeable": true`, `"mergeStateStatus": "CLEAN"`.

---

## Self-Review (выполнен автором плана)

- **Spec coverage:** видение и правила качества сохранены ✓; исправлены опечатки ✓; битая ссылка на скилл заменена на рабочую (Task 2, секция «Фронтенд» — Impeccable сохранён осознанно: это имя скилла из пользовательского конфига автора, вне установленного каталога; если скилл переименован — заменить на фактический id) ✓; вложенные уровни НЕ добавлены (по требованию) ✓; команды/структура/стек/конвенции/bash/анти-паттерны добавлены ✓.
- **Placeholders:** нет TBD/TODO; все команды и полный текст файла зафиксированы в Task 2 ✓.
- **Consistency:** команды Task 4 совпадают с секцией «Pre-PR» Task 2 и с `.github/workflows/ci.yml`; пути из таблицы структуры проверены `ls` ✓.
