# Recipe Q&A Service

## Статус

Репозиторий находится на этапе specification/planning. Реализация сервиса,
публичные URL, deployment provider, выбранная модель и измеренные cost/latency
будут зафиксированы после завершения core implementation. Корневой
[`SPEC.md`](SPEC.md) — canonical entry point, а нормативный текст
хранится в [`docs/03_SPEC.md`](docs/03_SPEC.md), без второй копии.

До EDA анализа корпуса фиксируется baseline `lowest stable recipe ID` для
одинаково релевантных рецептов после фильтрации. Если EDA найдёт более хороший
и надёжный сопоставимый сигнал — например, popularity, количество просмотров
или пользовательские likes — он может заменить baseline. Сигнал не может
нарушать hard constraints; смена стратегии фиксируется в ADR и
детерминированных тестах. Если надёжного сигнала нет, остаётся stable-ID
baseline.

## Core scope

Обязательный MVP включает:

- воспроизводимый корпус из 40–60 рецептов Wikibooks Cookbook;
- grounded `POST /ask` с machine-readable response, citations и refusals;
- одностраничный TypeScript UI с обычным JSON-режимом;
- deterministic tests, 12–15-question golden eval, Docker и deployment.

Дополнительные требования, включая streaming inline citations, вынесены в
[`03_SPEC_APPENDIX.md`](03_SPEC_APPENDIX.md). Они реализуются
только после core, не заменяют обязательные API, UI, tests, eval или
deployment и используют тот же retrieval/grounding pipeline.

## Scope cuts

В рамках лимита 6–8 часов намеренно исключены authentication, accounts,
multi-turn chat, saved history, voice/image assistance, nutrition calculations,
shopping lists, recipe generation и UI polish. Эти cuts уменьшают риск оставить
core-путь недоделанным. Для возврата любой из функций сначала понадобятся
отдельные требования, acceptance cases, тесты и оценка стоимости/latency.

## Long-chat policy for a future extension

MVP не является чатом и не хранит историю. Если multi-turn chat появится позже,
для model context нужно суммаризовывать старую историю, но пользовательский
текст и полный transcript должны сохраняться и показываться пользователю
полностью. Summary не должен заменять исходный текст в UI или становиться
единственным audit trail.

## Quality, security and AI-assisted checks

До merge CI должен запускать formatter/linter, type checks, unit/contract tests,
dependency and secret scans, а также container/SAST checks, когда они применимы.
Агентское review (например, CodeRabbit или внутренний агент) используется как
дополнительная проверка качества и уязвимостей: его замечания проверяются
человеком и не являются единственным security gate. В финальном README нужно
указать фактически выбранные инструменты и результаты запусков.

## Deployment, cost and latency

Эти значения пока не определены, поскольку implementation и deployment ещё не
выбраны. Финальная версия README должна указать provider и причину выбора,
public UI/API URLs, container-level access, команды локального и чистого
deployment, выбранные модели, стоимость одного и 1 000 вопросов, latency,
текущий bottleneck и следующий optimization.

## AI usage notes

В репозитории должны быть сохранены использованные instructions/prompts и
короткая заметка о том, что принято от агента, а что переписано самостоятельно.
Ответственность за архитектурные решения и код остаётся за разработчиком.
