# Трекер задач: GitHub

Задачи и планы работ этого репозитория хранятся в GitHub Issues репозитория
`ranilzinurov/codex-lb`. Для всех операций используется `gh`.

## Основные операции

- Создать задачу: `gh issue create --title "..." --body-file <file>`.
- Прочитать задачу и обсуждение: `gh issue view <number> --comments`.
- Получить открытые задачи: `gh issue list --state open --json number,title,body,labels,comments`.
- Добавить комментарий: `gh issue comment <number> --body "..."`.
- Изменить метки: `gh issue edit <number> --add-label "..."` или
  `--remove-label "..."`.
- Закрыть задачу: `gh issue close <number> --comment "..."`.

Репозиторий определяется по `origin`. Pull request не используется как входная
поверхность triage.

## Публикация задач навыками

Когда навык просит опубликовать задачу, он создаёт отдельный GitHub Issue.
Задачи публикуются в порядке зависимостей и получают метку `ready-for-agent`.

Зависимости оформляются нативными GitHub issue dependencies. Идентификатор для
API берётся из поля `id` задачи, а не из номера `#N` или `node_id`:

```shell
gh api --method POST \
  repos/ranilzinurov/codex-lb/issues/<child>/dependencies/blocked_by \
  -F issue_id=<blocker-database-id>
```

Если нативные зависимости недоступны, в теле зависимой задачи сохраняется
строка `Blocked by: #<number>`. Задача доступна исполнителю, когда все её
блокирующие задачи закрыты.
