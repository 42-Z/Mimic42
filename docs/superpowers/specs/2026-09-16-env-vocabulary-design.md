# Единый словарь переменных окружения

Дата: 2026-09-16

## Задача

Убрать зоопарк `.env` и имён переменных: сейчас одно и то же значение
описано тремя словарями (`SUPABASE_URL` / `TEST_SUPABASE_URL` /
`NEXT_PUBLIC_SUPABASE_URL`), тесты дублируют файл приложения, а запуск
тестов зависит от того, догадался ли разработчик сделать `source .env.test`.

Цель — один словарь имён, минимальный набор файлов и загрузка без ручных
телодвижений, при сохранении заслона от прод-проекта.

## Что не так сегодня

1. **Тесты дублируют приложение.** `.env` и `.env.test` описывают один и тот же
   Dev-проект: `SUPABASE_URL` и `TEST_SUPABASE_URL`, а равно и
   `DATABASE_CONNECTION_STRING`/`TEST_DATABASE_CONNECTION_STRING`, совпадают байт в
   байт. Дублируется всё, что не отличается.
2. **`SECRET_KEY` разъехался на одной базе.** Приложение шифрует строки ключом
   `SECRET_KEY`, тесты — `TEST_SECRET_KEY`, а база одна. Строки, созданные одной
   стороной, вторая расшифровать не может — отсюда `InvalidToken` при старте
   приложения, когда в Dev лежат агенты, созданные тестами или прошлой конфигурацией.
3. **Никто не грузит `.env.test`.** Тестовый слой читает только `os.environ`
   (`conftest.py`, `mimic42/testing/server.py`), а `pytest` и Playwright такой файл
   сами не читают. Последствия:
   - `uv run pytest` — команда из README — сегодня вообще красный:
     `2 failed, 149 passed, 28 skipped`. Оба падения в
     `tests/integration/test_testing_server.py` (`test_onboarding_script_endpoint_sets_code_and_password`
     и `test_onboarding_reset_endpoint_clears_the_script`) — это
     `KeyError: TEST_DATABASE_CONNECTION_STRING` из `build_test_app()`: эти два теста
     не берут фикстуру `clean_slot`, поэтому мимо них проходит и скип, а
     `_test_settings()` требует переменные напрямую;
   - остальные 28 db-тестов уходят в `pytest.skip` — в отчёте это выглядит как
     «их и не было»;
   - `bun run test:e2e` падает с «TEST_SUPABASE_URL не задан»;
   - рабочий рецепт — руками `set -a && source .env.test && set +a`, и он не
     задокументирован.
4. **Мёртвые артефакты.** `frontend/.env.test` не читает никто (Playwright не
   выставляет `NODE_ENV=test`, а значения e2e приходят из явного `env` в
   `playwright.config.ts`); его содержимое — от удалённого GoTrue-стаба.
   Правило `!.env.template` в `.gitignore` висит под несуществующий файл.
5. **Префикс `TEST_` не защищает прод.** От прод-проекта защищает
   `assert_test_project`, который проверяет фактические значения. Разделение имён
   защитой не является — оно лишь создаёт дубли и маскирует забытый загрузчик.
6. **`.env.test.example` противоречит практике.** Файл обещает, что service-role
   ключ «ни pytest, ни e2e, ни CI не получают», тогда как локальный e2e запускается
   через `source .env.test`, где этот ключ лежит.

## Решения

### Один словарь имён

`TEST_`-дубли убираются полностью. Остаются два префикса, оба вынужденные:

- **без префикса** — всё общее для приложения, backend-тестов и CI:
  `SUPABASE_URL`, `DATABASE_CONNECTION_STRING`, `SECRET_KEY`,
  `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `OPENROUTER_API_KEY`, `MEM0_API_KEY`,
  `CORS_ALLOW_ORIGINS`, и `SUPABASE_ANON_KEY` (только фронт и e2e, в локальном
  `.env` его нет — см. ниже);
- **`NEXT_PUBLIC_`** — требуется Next.js, иначе значение не вшивается в клиентский
  бандл. Прод-значения для фронта берутся не из `.env`, а из GitHub Variables
  на сборке образа.

Имена, у которых нет пары в приложении, остаются тестовыми и сохраняют префикс:
`TEST_USER_PASSWORD` (логин e2e и подготовка учёток), `TEST_SUPABASE_SERVICE_ROLE_KEY`
(только `scripts/test_env_bootstrap.py`).

### Файлы: пять вместо семи

| Файл | Роль | Гитигнор |
|---|---|---|
| `.env` | База **и для приложения, и для тестов**: подключение, секреты, рабочий Telegram-апп | да |
| `.env.test` | Только переопределения (2–3 строки): `TELEGRAM_API_ID=1`, `TELEGRAM_API_HASH=test-api-hash`, `TEST_USER_PASSWORD` | да |
| `.env.example` | Единственный шаблон backend-конфигурации: раздел «база», раздел «переопределения для тестов», ссылка на `/etc/mimic42.env` для прода | нет |
| `frontend/.env.local` | Три `NEXT_PUBLIC_*` на Dev | да |
| `frontend/.env.example` | Шаблон фронта без изменений | нет |

Удаляются: `frontend/.env.test`, `.env.test.example`, правило `!.env.template`.
`frontend/.env.local` не сливается в корень: Next читает env только из своей
директории, а веб-образ собирается с контекстом `./frontend`, поэтому корневой
`.env` в него физически не попадает.

### Загрузка без ручного `source`

- **Приложение** — без изменений: pydantic `env_file=".env"`.
- **pytest** — `conftest.py` до создания `Settings` подгружает в `os.environ` сначала
  `.env`, затем `.env.test` с `override=True` (так тестовые значения перекрывают
  базовые: `TELEGRAM_API_ID=1` вместо рабочего приложения, тестовый пароль).
- **Playwright** — `playwright.config.ts` грузит те же два файла через `dotenv`
  (объявлен явно в `frontend/devDependencies`) и мапит значения в `NEXT_PUBLIC_*`
  для `webServer.env`. `@next/env` для этого не годится: он читает `.env.test`
  только при `NODE_ENV=test`, а выставлять этот режим нельзя — под ним не
  собирается и не стартует Next. `process.env` у Next в наивысшем приоритете,
  поэтому тестовый бандл не подхватит прод-переменные.
- **Тестовый сервер** — `_test_settings()` сохраняет явный `mem0_api_key=None`:
  боевой ключ из `.env` не должен попадать в тесты при любой схеме имён.
- **Anon-ключ фронта** не дублируется в корневой `.env`: он нужен только браузеру,
  поэтому локально берётся из `frontend/.env.local` (там он уже есть как
  `NEXT_PUBLIC_SUPABASE_ANON_KEY`), а в CI — из секрета `SUPABASE_ANON_KEY`.
  Playwright разрешает его как `SUPABASE_ANON_KEY ?? NEXT_PUBLIC_SUPABASE_ANON_KEY`
  и падает, если нет ни одного.

Отсутствие файлов не ошибка: `load_dotenv` на несуществующем пути — no-op, поэтому
в CI (где файлов нет и значения приходят из секретов) поведение не меняется.

Объявление зависимости: `python-dotenv` уже приезжает транзитивно с
`pydantic-settings`, но раз мы импортируем его напрямую — добавляется явно в
dev-группу `pyproject.toml`.

### db-тесты — opt-in через выбор, без флагов

Сейчас 38 db-тестов не запускаются «сами» только потому, что переменных нет в
окружении. После перехода на общую загрузку `.env` они начнут запускаться на
каждом `uv run pytest`, а это ~6 минут и очистка слотов в общей Dev-базе. Поэтому
исключение db-тестов становится явным правилом, а не побочным эффектом:

```toml
[tool.pytest.ini_options]
addopts = ["-m", "not db"]
markers = ["db: тесты против настоящей базы Mimic42 Dev"]
```

- `uv run pytest` — 141 passed, 38 deselected. Быстро и безопасно.
- `uv run pytest -m db` — 38 против Dev. Явный `-m` с командной строки перекрывает
  addopts (проверено: pytest 9.0.3 берёт последний `-m`), поэтому отдельная
  переменная-переключатель не нужна: сам факт «прошу db» и есть opt-in.
- `-k` или путь сами по себе db-тесты не включают — addopts продолжает
  действовать; сузить прогон можно как `uv run pytest -m db -k slots`.
- Нет `.env` и/или `DATABASE_CONNECTION_STRING` → **падение** с объяснением
  (в `conftest.py` это `pytest.fail` вместо нынешнего `pytest.skip`). Раз db-тесты
  нельзя получить случайно, отсутствие настроек при явном запросе — ошибка
  конфигурации, а не повод отчитаться зелёным на нуле прогонов.
- Два теста, которые сегодня падают (см. п. 3), переписывать не нужно: их
  требование к окружению закрывает авто-загрузка `.env`, а если `.env` нет, они
  упадут вместе с остальными db-тестами — что и требуется по предыдущему пункту.

### Единый `SECRET_KEY`

Локальный `SECRET_KEY` становится тем же значением, что уже лежит в `.env`
(он расшифровывает существующие строки Dev), а `TEST_SECRET_KEY` удаляется — тесты
берут `SECRET_KEY` из `.env`. Это устраняет причину `InvalidToken`: строки,
созданные тестами, приложение снова сможет прочитать.

Следствие, которое принимается осознанно: агенты, созданные ранее с
`TEST_SECRET_KEY`, станут нечитаемыми. Это тестовые артефакты внутри Dev, и их
убирает `reset` перед следующим прогоном.

### Прод-безопасность

Единственный заслон — `assert_test_project` (allowlist: реф должен быть явно указан
в DSN, домене или claim `ref` JWT). Он вызывается внутри примитивов записи
(`purge_slot_data`, `hide_incomplete_onboarding_drafts`, `current_onboarding_draft_id`,
`acquire_slot`/`release_slot`, `build_test_app`), а не только у вызывающих, и не
зависит от имён переменных. Именно поэтому отказ от `TEST_`-префикса безопасен.

## GitHub

Прод-секретов бэкенда в GitHub нет и не появляется: они живут только в
`/etc/mimic42.env` на сервере, пайплайн их не передаёт. Прод-значения фронта
(`NEXT_PUBLIC_*`) остаются репо-переменными — anon-ключ по дизайну публичен.

Переименование секретов:

| сейчас | станет | назначение |
|---|---|---|
| `TEST_DATABASE_CONNECTION_STRING` | `DATABASE_CONNECTION_STRING` | общее: приложение + тесты |
| `TEST_SUPABASE_URL` | `SUPABASE_URL` | общее |
| `TEST_SECRET_KEY` | `SECRET_KEY` | общее (шифрование сессий) |
| `TEST_SUPABASE_ANON_KEY` | `SUPABASE_ANON_KEY` | логин в e2e → мапится в `NEXT_PUBLIC_*` |
| `TEST_DB_PASSWORD` | `SUPABASE_DB_PASSWORD` | только CLI (`supabase link` / `db push`) |

Без изменений, по решению владельца репозитория:
`TEST_SUPABASE_SERVICE_ROLE_KEY` (Dev-ключ, нужен `test_env_bootstrap.py`),
`SUPABASE_ACCESS_TOKEN` (остаётся аккаунт-уровневым — принятый риск: такой токен
способен дотянуться и до прода; снимается отдельной задачей при желании),
`TEST_USER_PASSWORD`, `DEPLOY_*`, `CLAUDE_CODE_OAUTH_TOKEN`.

Среда `production`, флаг `environment: production` в `deploy.yml` и `rollback.yml` —
без изменений. Среда остаётся пустой (0 секретов, 0 переменных, 0 protection rules):
деплой срабатывает на push в `main`, а merge в `main` уже требует апрува по
ruleset'у. Принятый остаточный зазор: актор с правом bypass (админ) может смерджить
без ревью — как это и произошло с #65 — и такое изменение уедет в прод без второго
человека.

### Порядок выката

Порядок обязателен, иначе встанет CI:

1. завести секреты под новыми именами (старые при этом живы);
2. смерджить правку `ci.yml` под новые имена;
3. убедиться, что все пять джоб зелёные;
4. удалить старые имена секретов.

## Изменения в CI

`ci.yml`: джобы `backend-db`, `e2e` и `migrations-drift` переходят на новые имена.
Джоба `backend-db` продолжает вызывать `pytest -m db`: её `-m` перекрывает addopts,
поэтому ни новых переменных, ни правок логики ей не нужно. Джоба `backend` гоняет
`-m "not db"` — то же, что и addopts по умолчанию, но оставлено явным, чтобы
намерение читалось из воркфлоу. `migrations-drift` берёт
`secrets.SUPABASE_ACCESS_TOKEN` и `secrets.SUPABASE_DB_PASSWORD` (имя секрета
совпадает с именем переменной, которую читает CLI). Заглушки телеги
(`TELEGRAM_API_ID=1`, `TELEGRAM_API_HASH=test-api-hash`) остаются литералами в джобах.

## Что осознанно не делаем

- **Не сливаем `frontend/.env.local` в корень.** Требовало бы ручной подстановки
  через `next.config.js` и не работает при сборке образа (контекст `./frontend`).
- **Не вводим `.env.development`.** Для Next это слот коммитимых дефолтов
  окружения, а в env лежат реальные секреты — класть в гит нечего; для backend это
  не конвенция pydantic, а самодельная развилка по `ENVIRONMENT`.
- **Не защищаем `Settings()` в юнит-тестах от `.env`.** pydantic читает `.env`
  сегодня и будет читать завтра; на поведение это не влияет, потому что ни один тест
  не строит реальных клиентов LLM/Mem0 (`_test_settings` жёстко гасит Mem0). Если
  появится тест, поднимающий реальный клиент, — возвращаемся к этому пункту.
- **Не автоматизируем сверку списка ключей** в `deploy/README.md` с `.env.example`.
  Heredoc там остаётся как готовые команды для сервера, а источником имён
  объявляется `.env.example`; расхождение ловится на ревью.
- **Не трогаем** `deploy/.env` (compose-переменные `IMAGE_TAG`/`API_PORT`/`WEB_PORT`)
  и `/etc/mimic42.env`: они на другой машине и не пересекаются со словарём приложения.
  Попутно правится только комментарий `deploy/deploy.sh:5`, где файл секретов назван
  `api.env` вместо `/etc/mimic42.env`.

## Проверка

- `uv run ruff check .` и `uv run ruff format --check .` — чисто.
- `uv run ty check` — чисто.
- `uv run pytest -q` — 141 passed, 38 deselected (db исключены addopts'ом).
- `uv run pytest -m db -q` — 38 passed против Dev, без `source`.
- `uv run pytest -m db` во временно переименованном `.env` (настроек нет) —
  падение с внятным текстом, а не тихий скип.
- `cd frontend && bunx tsc --noEmit && bun test` — чисто.
- `cd frontend && bun run test:e2e` **без** `source` — проходит.
- `grep -rn "TEST_SUPABASE\|TEST_SECRET\|TEST_DATABASE\|TEST_TELEGRAM"` по репозиторию
  не находит ничего, кроме `TEST_USER_PASSWORD` и
  `TEST_SUPABASE_SERVICE_ROLE_KEY`.
- После переименования секретов — все пять джоб `CI` зелёные на PR.

## Затрагиваемые файлы

- `.env`, `.env.test`, `.env.example` — содержимое; `.env.test.example` — удаление.
- `.gitignore` — минус `!.env.template`, минус `!.env.test.example`.
- `conftest.py` — загрузка `.env` + `.env.test`, `pytest.fail` вместо `pytest.skip`
  при отсутствии настроек, проверка значений под новыми именами.
- `src/mimic42/testing/server.py` — `_test_settings()` под новые имена; заодно
  гард module-level `app` (сейчас `if os.environ.get("TEST_DATABASE_CONNECTION_STRING")`):
  после переименования локально он станет истинным всегда, и `app` будет собираться
  при импорте. Это безопасно — `build_test_app()` не открывает соединений, только
  конструирует приложение и проверяет значения через `assert_test_project`, — и
  даже полезно: чужой `.env` упадёт на импорте, а не на первом запросе.
- `src/mimic42/testing/slot_cli.py` — новое имя DSN.
- `tests/integration/test_app_lifespan.py`, `tests/integration/test_conversation.py` —
  `TEST_SECRET_KEY` → `SECRET_KEY`.
- `scripts/test_env_bootstrap.py` — новые имена переменных.
- `pyproject.toml` — явный `python-dotenv` в dev-группе, `addopts = ["-m", "not db"]`,
  объявление маркера `db`.
- `frontend/playwright.config.ts` — загрузка через `dotenv`, новые имена,
  маппинг в `NEXT_PUBLIC_*`.
- `frontend/package.json` — `dotenv` в devDependencies.
- `frontend/.env.test` — удаление.
- `.github/workflows/ci.yml` — имена секретов в трёх джобах.
- `README.md` — раздел про тесты: авто-загрузка, opt-in db-тестов, что локальный
  `.env` смотрит в Dev.
- `deploy/deploy.sh` — комментарий про `/etc/mimic42.env`.
