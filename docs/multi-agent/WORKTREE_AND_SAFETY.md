# Worktrees, процессы и сохранность работы

## Вывод

Переиспользовать `worktree.py` и `land.py`, но усилить проверки в Python.
Инструкций агенту недостаточно для блокировки второго процесса и сохранности несохранённых файлов.
Worktree изолирует Git index и файлы проекта. Он не является системной песочницей для доступа к HOME или сети.
У Kimi prompt mode `-p` документированная auto policy действует даже без флага `--auto`.
Его ограничение workspace/read-only нужно доказать отдельно до включения соответствующего профиля.

## Риск удаления из исходного аудита

Ниже описана исходная ошибка. Она исправлена: `land` создаёт уникальный служебный worktree,
сохраняет изменения и отказывается от forced cleanup при неизвестном состоянии.

`scripts/land.py:268–272` переиспользует фиксированный путь `.claude/worktrees/auto-bmad-land`.
Если путь существует, код вызывает `git worktree remove --force`, затем без проверки делает `shutil.rmtree`.
Это удаляет и обычный каталог, и несохранённый результат старого запуска.
Проверка на временном репозитории подтвердила потерю `uncommitted.txt`.

`test_in()` также возвращает существующий worktree через `checkout -f`.
`cleanup()` удаляет дерево с `--force`. Изменения, оставленные тестами, могут исчезнуть.
До CLI runtime нужен отдельный safety PR с regression tests.
Предпочтительно тестировать merge commit в новом уникальном служебном worktree.
Если тесты изменили дерево, сохранить его и вернуть путь; не стирать результат безусловно.

## Manifest запуска

Новый CLI хранит session, manifest, попытки, результаты и журналы в
`<git-common-dir>/auto-bmad-sessions/<run-id>/`, вне writable worktree агента.
Inbox команд находится в `<worktree>/.auto-bmad/runs/<run-id>/inbox/`; это rendezvous, не authoritative journal.
Liveness использует heartbeat в Git metadata вместе с root flock и не требует `ps` внутри sandbox.
Session test workers имеют свой heartbeat и сигналят только собственную process group.
Cleanup sentinel controller-процесса закрывает приём тестов и удерживает execution lease до
остановки detached session workers и освобождения test folder lock. При неизвестном состоянии
lease остаётся занят, а runtime сообщает needs_attention.
Host выполняет подтверждающие проверки с защищённым cache по code tree и команде;
результаты из writable `.auto-bmad/tests/` не являются свидетельством для checkpoint.
Для попытки сохранять:

| Поле | Назначение |
|---|---|
| run/task/attempt ID, parent attempt | Связь story и вложенных заданий |
| role, profile, adapter, CLI version | Кто выполнял работу |
| config hash, engine snapshot hash | Какой процесс и правила применялись |
| repo common-dir, canonical worktree path | Проверенная идентичность репозитория |
| branch, base/head SHA, review diff hash | Точный набор проверяемых изменений |
| changed files, dirty state | Состояние после успеха, ошибки и cancel |
| PID, process start identity, process group | Безопасная остановка своих процессов |
| lease owner и delegated owner | Кто сейчас имеет право записи |
| status, checkpoints, errors, artifacts | Resume и диагностика |
| merge authorization | Конкретные target/source SHA, разрешённые пользователем |

Файлы manifest писать через temp + atomic replace под lock.
Checkpoint фиксировать до и после операции с побочным эффектом.
JSONL events дополняют manifest; события не заменяют восстановление фактического Git-состояния.

## Владение worktree

Новый CLI создаёт worktree через manager до запуска агента, затем задаёт cwd процесса.
Он не использует Claude `EnterWorktree` или native isolation другого CLI.
Legacy `.claude/worktrees` и ветки `auto-bmad/*`, `bmad/*` остаются распознаваемыми.
В новом CLI ветки имеют вид `codex/auto-bmad/<label>-<uuid>`, где label — story/epic target.
Имена уникальны между запусками одной story.
Распознавание ownership новых деревьев идёт по manifest, а не только по имени каталога.

Один canonical worktree имеет один execution lease.
Lock хранится под общим Git directory, чтобы два независимых процесса увидели одну блокировку.
Использовать проверенный межпроцессный механизм, например `fcntl.flock` на поддерживаемой macOS/Linux платформе.
Наличие PID без start identity не доказывает живого владельца из-за повторного использования PID.
При неизвестной идентичности требуется reconcile, а не принудительный захват.

Контроллер передаёт writer lease одному implementer и ждёт его завершения.
Право возвращается контроллеру только после завершения дочернего процесса и проверки состояния.
Во время параллельного review все leases read-only, writer отсутствует.
Triage с записью evidence — отдельная узкая writable зона, а не право менять код.
Запрос дочернего агента не может сам создать себе lease или повысить permissions.

Lease исключает конфликт между сотрудничающими auto-bmad процессами.
Он не запрещает человеку или стороннему процессу менять файлы.
Перед gates сравнивать ожидаемые head/tree fingerprints и останавливать устаревший результат.

## Создание и seed

Проверить чистое исходное дерево, полный base SHA и доступ к Git metadata.
Не использовать `checkout -B` для ветки восстановления: это может сбросить сохранённые commits.
Seed копирует только разрешённые локальные BMAD/runtime настройки.
Текущий `seed()` копирует ignored TOML/YAML под `_bmad`; `seed_run()` добавляет Claude-specific local files.
Для других backend нужен отдельный allowlist, а не копирование всех скрытых конфигов.
Auth stores, tokens и пароли не копировать.
Подхват конфигурации из главного дерева закрепить в resolved snapshot, иначе середина запуска может увидеть новые настройки.

Проверить symlink/path containment для seed, result paths и hooks files.
Git linked worktree использует общий `.git`; разрешения sandbox должны позволять нужные операции metadata.
Не расширять write access на весь HOME ради Git commit.

## Merge policy

В новом CLI MVP `merge_policy = "manual"`: run никогда не сливает автоматически.
Запуск заканчивается веткой, base/head, результатами checks и конкретной командой `land`.
Явный вызов человеком `land` считается разрешением на это слияние.
Агент может вызвать его только после отдельного явного разрешения пользователя на конкретный target.
Перед merge повторно проверить source/head, target/head, отсутствие активных leases и dirty state.
Если tips изменились после одобрения, старое одобрение не применять.

Текущий Claude `PARALLEL.md` автоматически сливает волны.
Это прежнее поведение сохраняется в legacy режиме, но не переносится как default нового CLI.
Волны могут требовать слияния в промежуточную integration-ветку для следующей волны.
Такое слияние тоже требует явного разрешения, даже если оно не затрагивает main.
Без разрешения run останавливается в `awaiting_merge`; следующая зависимая волна не запускается.
Автоматическое разрешение конфликтов агентом не включать в MVP.

## Удаление

Удалять дерево можно только после проверки ownership, отсутствия процессов/lease и сохранности результата.
Проверять staged, unstaged и untracked файлы, включая ignored файлы, которые могли создать agents/tests.
Обычный `git status` не видит ignored output; одного его недостаточно для запрета потери данных.
Постоянно исключённые seed-файлы отличать от новых изменений по manifest/hash.
При ошибке проверки считать состояние неизвестным и оставить дерево.
Отклонить удаление main tree, чужого worktree, symlink escape и непроверенного каталога.
Незалитые commits сохранять в ветке даже после освобождения каталога.
Не переносить `--force` в автоматический cleanup нового runtime.

## Recovery и cancellation

После аварии сначала сверить manifest, Git branch/head, spec и процессы.
Checkpoint `running` без живого процесса превращается в `interrupted`, а не `done`.
Если engine успел commit, но родитель потерял ответ, проверить commit/spec и продолжить finishing.
Если осталось dirty tree, сохранить его и продолжить только по проверенному engine resume path.
Не начинать story заново с intent: это может создать вторую spec.
Не сбрасывать ветку и не удалять дерево ради повторного запуска.

События finishing получают idempotency key: run/task/attempt/operation.
Внутренние tracking/questions updates проверяются перед повтором.
Внешние shell hooks не дают exactly-once без поддержки получателя.
Сохранять intent/result вызова hook и передавать event ID; после неоднозначного сбоя не повторять опасный hook автоматически.
Статистика не должна повторно учитывать один attempt.

Мягкий stop завершает текущую story и не запускает следующую.
Жёсткий cancel прекращает дочерние CLI, owned tests и stubs, затем сохраняет dirty worktree.
Не останавливать процессы пользователя по имени или занятому порту.
Не считать cancel успешным, пока cleanup не подтвердил результат либо не вернул `needs_attention`.

## Тестовые ресурсы

Текущий `testrun` lock действует на каталог, а не на общий DB/порт разных worktrees.
Разные stories могут конфликтовать через внешние ресурсы даже при корректной Git-изоляции.
До waves проверить resource isolation проекта либо сериализовать соответствующие checks.
Test cache по tree+command не подтверждает неизменность Docker, toolchain и внешних сервисов.
Для внешней среды нужен явный rerun либо контекст cache key; не объявлять cache доказательством свежести всех условий.

## Обязательные проверки

- Два процесса не могут одновременно писать в один worktree; delegated handoff не зависает.
- Cancel убирает только свои процессы и сохраняет dirty/untracked/ignored результаты.
- Resume после commit до ответа не дублирует реализацию, tracking и statistics.
- Merge запрещён без авторизации и при изменённых tips.
- `land` сохраняет занятый служебный каталог и изменения после tests.
- Recovery работает для прежних Claude веток и новых manifest-owned деревьев.
