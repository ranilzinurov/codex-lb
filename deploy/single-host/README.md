# Single-host развёртывание по digest

Этот каталог задаёт production-контракт для одного Docker-хоста с SQLite. Сервис
запускается только из опубликованного `linux/amd64` образа, адресованного
неизменяемым digest. Исходный код на хосте не собирается.

`deploy.py` — единственная команда развёртывания. Она берёт неблокирующую
блокировку, проверяет место на диске и образ-кандидат до остановки текущего
сервиса, создаёт консистентную резервную копию SQLite, запускает Compose и
проверяет Docker health, локальный readiness и публичный readiness. Если
образ-кандидат не проходит проверку после остановки сервиса, команда возвращает
предыдущий известный исправный образ и проверяет его готовность.

## Локальный выпуск в GHCR

Выпуск выполняется с локальной машины из точного SHA, уже опубликованного в
`origin`. Наличие незакоммиченных файлов в основной рабочей копии допустимо:
сборка всегда получает отдельный чистый detached worktree и не видит эти файлы.

Сначала проверьте план без сборки и публикации. Диагностика требует те же
учётные данные и проверяет доступность Docker daemon, buildx, Trivy и вход в
GHCR во временном Docker config:

```bash
GITHUB_USER=<github-user> GITHUB_TOKEN=<packages-write-pat> \
  make release-local-dry-run RELEASE_SHA=<40-hex-sha>
```

Для публикации используйте ту же пару переменных окружения. Токен передаётся
`docker login` через stdin и хранится только во временном `DOCKER_CONFIG`:

```bash
GITHUB_USER=<github-user> GITHUB_TOKEN=<packages-write-pat> \
  make release-local RELEASE_SHA=<40-hex-sha>
```

Для полного операторского потока по SSH задайте существующий checkout на
сервере и выполните одну команду:

```bash
GITHUB_USER=<github-user> GITHUB_TOKEN=<packages-write-pat> \
  make release-deploy RELEASE_SHA=<40-hex-sha> \
  DEPLOY_HOST=<user@host> DEPLOY_REMOTE_REPOSITORY=/opt/codex-lb
```

Она публикует кандидат, передаёт на сервер только готовый манифест, выполняет
`doctor`, deploy и повторный `doctor`, который подтверждает активный и
фактически запущенный digest. Временная серверная копия манифеста удаляется при
любом исходе. Если оператору нужен `sudo`, добавьте
`RELEASE_DEPLOY_FLAGS=--sudo`; путь к control-файлу задаётся через
`DEPLOY_REMOTE_CONFIG`.

Команда автоматически выбирает `fork-contract` либо полный `make ci` по
областям изменений выбранного коммита; `RELEASE_FLAGS=--full` принудительно
повышает уровень до полного. Затем buildx публикует только `linux/amd64` с
локальным повторно используемым кэшем, получает registry digest, сверяет OCI
revision и один раз запускает блокирующий Trivy-контроль опубликованного
digest. Временные worktree, Docker config и незавершённый кэш удаляются при
любом исходе.

Успешный результат записывается в `release-manifest-<sha-prefix>.json`. Формат
содержит `schema_version: 1`, repository, полный Git SHA, неизменяемый digest,
платформу и результаты ворот `validation`, `revision`, `security`; значений
токенов и других секретов в нём нет. Только манифест с `ready: true` пригоден
для развёртывания.

## Порядок выпуска и обновления

Операторский путь состоит из одного кандидата и одного и того же манифеста на
всех этапах:

1. На локальной машине выполните `make release-local`; сохраните созданный
   `release-manifest-<sha-prefix>.json`.
2. Передайте на сервер только манифест и checkout скриптов развёртывания. Секреты
   остаются в существующем `/etc/codex-lb/runtime.env`, а данные — в именованном
   volume `codex-lb-data`.
3. Запустите `deploy.py doctor --manifest ...`. Продолжайте только при успешных
   семи проверках.
4. Запустите `deploy.py --manifest ...`. После успеха проверьте, что поле
   `active.image` в `/var/lib/codex-lb-deploy/known-good.json` равно digest из
   манифеста, а последняя строка `deploy-events.jsonl` имеет outcome
   `deployment_succeeded`.
5. Проверьте вход в dashboard и один запрос через существующий API-ключ. Команда
   развёртывания не заменяет `runtime.env`, volume или ключ шифрования, поэтому
   повторная авторизация не требуется.

Если кандидат не проходит readiness либо контроль отпечатка, команда сама
запускает предыдущий digest и записывает `rollback_succeeded`. При ошибке самого
отката outcome содержит `rollback_failed`; в этом случае используйте digest из
`previous`/последнего успешного события и процедуру ручного восстановления ниже.

## Первичная настройка

На Docker-хосте разместьте checkout этого репозитория и создайте два
host-owned файла вне репозитория:

```bash
sudo install -d -m 700 /etc/codex-lb /var/lib/codex-lb-deploy/backups
sudo install -m 600 deploy/single-host/runtime.env.example /etc/codex-lb/runtime.env
sudo install -m 600 deploy/single-host/deployment.env.example /etc/codex-lb/deployment.env
sudoedit /etc/codex-lb/runtime.env
sudoedit /etc/codex-lb/deployment.env
```

`runtime.env` передаётся только контейнеру. В нём находятся настройки
приложения и секреты, включая при необходимости bootstrap token. Скрипт
отказывается использовать файл, доступный группе или остальным пользователям.
Команду можно запускать без `sudo` пользователем с доступом к Docker; в таком
случае каталоги состояния и резервных копий должны принадлежать этому
пользователю. Контейнер резервного копирования записывает SQLite-файл с UID/GID
оператора, чтобы проверка целостности и последующее восстановление не требовали
смены владельца через `root`.
Для SQLite путь должен оставаться
`sqlite+aiosqlite:////var/lib/codex-lb/store.db`, так как этот каталог —
постоянный volume `codex-lb-data`.

`deployment.env` не содержит секретов. В нём обязательны:

| Переменная | Назначение |
| --- | --- |
| `DEPLOY_RUNTIME_ENV_FILE` | Путь к `runtime.env` с правами `0600`. |
| `DEPLOY_PUBLIC_READY_URL` | URL `/health/ready` через production reverse proxy. |
| `DEPLOY_MIN_FREE_SPACE_MB` | Минимум свободного места до `pull`; по умолчанию 2048 MiB. |
| `DEPLOY_BACKUP_RETENTION` | Число резервных копий, созданных командой; по умолчанию 3. |

Остальные параметры и их безопасные значения приведены в
[`deployment.env.example`](deployment.env.example). Compose открывает оба
порта только на loopback; внешний доступ должен обеспечивать reverse proxy.

## Предварительная диагностика

Перед окном обновления запустите неизменяющую состояние диагностику с тем же
кандидатом, который планируется развернуть:

```bash
sudo ./deploy/single-host/deploy.py doctor \
  --config /etc/codex-lb/deployment.env \
  --manifest /path/to/release-manifest-<sha-prefix>.json
```

Для оркестратора добавьте `--json`. Версионированный отчёт
`schema_version: 1` содержит отдельные статусы Docker, Compose, registry,
deploy state, свободного места, data volume и каталога резервных копий. В нём
нет значений из `runtime.env`. Поле `deployment_state` отдельно передаёт
`active_image`, `previous_image` и `running_image`, поэтому автоматизация
сравнивает полные digest без разбора человекочитаемой строки. `doctor` не
создаёт каталоги и lock/state-файлы,
не загружает и не удаляет образы, не останавливает и не запускает контейнеры.
Ненулевой код означает, что развёртывание начинать нельзя.

## Развёртывание

Передайте на сервер готовый манифест локального выпуска. Deploy принимает его
только при `schema_version: 1`, `ready: true`, платформе `linux/amd64`, точном
`repository@sha256:...` и успешных воротах validation/revision/security.
Изменяемый SHA-тег не является входными данными.

```bash
sudo ./deploy/single-host/deploy.py \
  --config /etc/codex-lb/deployment.env \
  --manifest /path/to/release-manifest-<sha-prefix>.json
```

Deploy всегда требует готовый release manifest. Для аварийного возврата
используйте сохранённый манифест соответствующего известного digest; прямой
обход ворот через пару `--image/--revision` не поддерживается.

Команда сначала запускает `docker compose config -q`, проверяет защищённость
файла секретов и выводит отчёт вида `required=…MiB available=…MiB` до любого
`pull` или остановки сервиса. При дефиците она может удалить только исторические
digest, ранее записанные этой командой; кандидат, активный образ и единственный
образ отката защищены. После каждого удаления место проверяется повторно, общий
Docker prune не используется. Если порог не достигнут, работающий сервис не
изменяется. Затем команда проверяет платформу `linux/amd64`, OCI
метку `org.opencontainers.image.revision` и точку входа образа. Повторный запуск
того же работающего digest завершается как безопасный `No-op`.

Состояние известных исправных образов хранится в
`/var/lib/codex-lb-deploy/known-good.json`. Оно является метаданными владения
для очистки: после успешного развёртывания остаются активный образ и один
предыдущий исправный образ. Удаляются только digest, ранее записанные этой командой;
активный контейнер исключается из очистки по полному Docker ID. Чужие контейнеры,
образы, volume и файлы не выбираются. Docker-логи контейнера
ограничены драйвером `local` (`3 × 10 MiB`), а удаляются только файлы
`codex-lb-deploy-*.sqlite` из `DEPLOY_BACKUP_DIR`.

До остановки и после готовности кандидата команда формирует отпечаток
`schema_version: 1`. Он содержит идентификатор volume/пути БД, счётчики
`accounts`, `api_keys`, `model_sources`, `automation_jobs` и только SHA-256
защищённых значений. Идентификаторы строк и исходные токены, API-ключи, пароли
и секреты в state и вывод не попадают. Новые записи и рост счётчиков допустимы;
смена хранилища, уменьшение счётчика, исчезновение либо изменение существующего
защищённого значения вызывают откат.

`known-good.json` фиксирует фактически активный digest и последний успешный
отпечаток. Журнал `/var/lib/codex-lb-deploy/deploy-events.jsonl` с правами
`0600` записывает успешное развёртывание, недоступность/ошибку отката либо
фактически восстановленный предыдущий digest без секретов.

## Резервная копия и ручное восстановление SQLite

Перед заменой существующего сервиса команда создаёт SQLite backup через
consistency-preserving SQLite backup API и проверяет `PRAGMA integrity_check`.
Сама база открывается в режиме `mode=ro`, но volume монтируется с записью:
SQLite требует доступ к служебному `-shm` при чтении актуального WAL после
остановки приложения.
При первой установке базы ещё нет, поэтому это явно сообщается. При неудаче
образ-кандидат откатывается автоматически, но SQLite никогда не
восстанавливается автоматически: миграция могла уже изменить схему, и такое
решение должен принять оператор.

Чтобы явно восстановить указанную резервную копию, сначала остановите сервис,
затем выполните команду с известным локальным image. Она удаляет WAL/SHM только
после остановки и заменяет основную базу выбранным backup:

```bash
IMAGE=ghcr.io/ranilzinurov/codex-lb@sha256:<known-local-digest>
sudo env CODEX_LB_IMAGE="$IMAGE" CODEX_LB_RUNTIME_ENV_FILE=/etc/codex-lb/runtime.env \
  docker compose --project-name codex-lb -f deploy/single-host/docker-compose.yml stop server
sudo docker run --rm --entrypoint python \
  --mount type=volume,src=codex-lb-data,dst=/var/lib/codex-lb \
  --mount type=bind,src=/var/lib/codex-lb-deploy/backups,dst=/backup,readonly \
  "$IMAGE" \
  -c 'import pathlib, shutil; target=pathlib.Path("/var/lib/codex-lb/store.db"); [pathlib.Path(str(target) + suffix).unlink(missing_ok=True) for suffix in ("", "-wal", "-shm")]; shutil.copy2("/backup/codex-lb-deploy-<timestamp>.sqlite", target)'
```

После восстановления снова запустите `deploy.py` с сохранённым готовым
манифестом нужного известного digest.

## Изолированная проверка жизненного цикла

Перед изменением single-host runtime выполните:

```bash
make single-host-lifecycle-test
```

Проверка поднимает локальный временный registry и три минимальных
`linux/amd64`-образа, затем воспроизводит первоначальную установку, успешное
обновление с сохранением контрольных записей и хеша тестового секрета, отказ
неготового кандидата и откат к фактически предыдущему digest. Имена контейнеров,
сети, volume и порты уникальны для запуска; завершение всегда удаляет их.
Рабочие серверные файлы, Docker config и production volume не используются.
