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

## Развёртывание

CI main-ветки выводит digest и Git revision в итогах задания Docker. Передайте
оба значения без SHA-тега: тег — только вспомогательная ссылка, не входные
данные развёртывания.

```bash
sudo ./deploy/single-host/deploy.py \
  --config /etc/codex-lb/deployment.env \
  --image ghcr.io/ranilzinurov/codex-lb@sha256:<64-hex-digest> \
  --revision <40-hex-git-revision>
```

Команда сначала запускает `docker compose config -q`, проверяет защищённость
файла секретов и выводит отчёт вида `required=…MiB available=…MiB` до любого
`pull` или остановки сервиса. Затем она проверяет платформу `linux/amd64`, OCI
метку `org.opencontainers.image.revision` и точку входа образа. Повторный запуск
того же работающего digest завершается как безопасный `No-op`.

Состояние известных исправных образов хранится в
`/var/lib/codex-lb-deploy/known-good.json`. Оно является метаданными владения
для очистки: после успешного развёртывания остаются активный образ и один
предыдущий исправный образ. Удаляются только digest, ранее записанные этой командой;
чужие контейнеры, образы, volume и файлы не выбираются. Docker-логи контейнера
ограничены драйвером `local` (`3 × 10 MiB`), а удаляются только файлы
`codex-lb-deploy-*.sqlite` из `DEPLOY_BACKUP_DIR`.

## Резервная копия и ручное восстановление SQLite

Перед заменой существующего сервиса команда создаёт SQLite backup через
consistency-preserving SQLite backup API и проверяет `PRAGMA integrity_check`.
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

После восстановления снова запустите `deploy.py` с нужным известным digest.
