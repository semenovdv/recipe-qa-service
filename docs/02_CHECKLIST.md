# Ограничения и Acceptance Criteria — Recipe Q&A Service

Цель — получить не просто список того, **что нужно сделать**, а набор требований, которые можно использовать как:

- основу для `SPEC.md`;
- checklist во время разработки;
- основу для acceptance tests;
- критерии проверки перед submission;
- основу для golden eval;
- контроль scope в рамках ограниченных 6–8 часов.

### Типы требований


| Тип            | Значение                                                                                               |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| **MUST**       | Жёсткое требование. Невыполнение означает несоответствие заданию.                                      |
| **SHOULD**     | Явно рекомендуемый подход / ожидание. Влияет на качество и оценку, но допускает осознанный компромисс. |
| **PREFERENCE** | Предпочтение авторов задания. Другой вариант допустим при наличии обоснования.                         |
| **BONUS**      | Дополнительная возможность, не заменяющая core requirements.                                           |
| **ASSUMPTION** | Решение, которое не задано напрямую и должно быть явно зафиксировано разработчиком.                    |




### Приоритеты


| Приоритет | Значение                          |
| --------- | --------------------------------- |
| **P0**    | Критично для соответствия заданию |
| **P1**    | Важно для качества / оценки       |
| **P2**    | Дополнительное улучшение          |


---



# 2. Core Product Behavior


| ID      | Type | Priority | Checklist | Требование                                             | Как проверить                                                    |
| ------- | ---- | -------- | --------- | ------------------------------------------------------ | ---------------------------------------------------------------- |
| CORE-01 | MUST | P0       | ☐         | Сервис отвечает на вопросы о рецептах из public corpus | Выполнить несколько вопросов через API/UI                        |
| CORE-02 | MUST | P0       | ☐         | Ответы должны основываться только на corpus            | Задать вопрос, ответа на который нет в corpus; проверить refusal |
| CORE-03 | MUST | P0       | ☐         | Каждый успешный ответ должен содержать citations       | Проверить response                                               |
| CORE-04 | MUST | P0       | ☐         | Citation содержит recipe title и URL                   | JSON/schema validation                                           |
| CORE-05 | MUST | P0       | ☐         | Если corpus не может ответить — сервис отказывает      | Golden out-of-corpus test                                        |
| CORE-06 | MUST | P0       | ☐         | Отказ должен быть polite                               | Manual/eval review                                               |
| CORE-07 | MUST | P0       | ☐         | Refusal должен быть machine-readable                   | Проверить `refused` и `refusal_reason`                           |


---



# 3. API



## `POST /ask` (core)


| ID     | Type | Priority | Checklist | Требование                                            | Как проверить               |
| ------ | ---- | -------- | --------- | ----------------------------------------------------- | --------------------------- |
| API-01 | MUST | P0       | ☐         | Существует `POST /ask`                                | HTTP integration test       |
| API-02 | MUST | P0       | ☐         | Endpoint принимает question                           | Отправить valid request     |
| API-03 | MUST | P0       | ☐         | Response является structured JSON                     | JSON parsing + Content-Type |
| API-04 | MUST | P0       | ☐         | Полная schema определена в `SPEC.md`                  | Проверить `SPEC.md`         |
| API-05 | MUST | P0       | ☐         | `answer` имеет тип непустой `string`                   | Schema validation           |
| API-06 | MUST | P0       | ☐         | Response содержит `citations`                         | Schema validation           |
| API-07 | MUST | P0       | ☐         | Каждый citation содержит `title` и `url`              | Schema validation           |
| API-08 | MUST | P0       | ☐         | Response содержит `refused: boolean`                  | Schema validation           |
| API-09 | MUST | P0       | ☐         | Response содержит `refusal_reason`                    | Schema validation           |
| API-10 | MUST | P0       | ☐         | `refusal_reason` ограничен допустимыми значениями     | Enum validation             |
| API-11 | MUST | P0       | ☐         | Refusal определяется структурой, а не анализом текста | Contract test               |




### Минимальный response contract

```
{
  "answer": "non-empty string",
  "citations": [
    {
      "title": "...",
      "url": "..."
    }
  ],
  "refused": false,
  "refusal_reason": "out_of_corpus | out_of_domain | safety | null"
}
```

---



# 4. Retrieval / Grounding

Это одно из наиболее существенных архитектурных ограничений задания.


| ID     | Type   | Priority | Checklist | Требование                                                        | Как проверить                                        |
| ------ | ------ | -------- | --------- | ----------------------------------------------------------------- | ---------------------------------------------------- |
| RET-01 | MUST   | P0       | ☐         | Ответ должен базироваться на recipes, которые сервис retrieved    | E2E/golden test                                      |
| RET-02 | MUST   | P0       | ☐         | Model не должна отвечать из собственной памяти                    | Создать вопрос с информацией, отсутствующей в corpus |
| RET-03 | MUST   | P0       | ☐         | Retrieval должен находить правильный source                       | Golden set                                           |
| RET-04 | MUST   | P0       | ☐         | Citations должны соответствовать источникам ответа                | Сравнить retrieved sources и citations               |
| RET-05 | MUST   | P0       | ☐         | Система должна уметь определить недостаточность corpus            | Out-of-corpus eval                                   |
| RET-06 | SHOULD | P1       | ☐         | Retrieval method должен быть обоснован                            | ADR                                                  |
| RET-07 | SHOULD | P1       | ☐         | Constraints должны учитываться в retrieval/filtering architecture | Retrieval/filter tests + ADR                         |
| RET-08 | SHOULD | P1       | ☐         | До EDA используется stable-ID baseline; лучший подтверждённый EDA signal может заменить его | EDA + ADR + deterministic tests |




### Критическое ограничение

Нельзя строить систему по принципу:

> User question → LLM → answer

с простым требованием в prompt «не выдумывай».

Поведение должно быть связано с **retrieved corpus**, а не с knowledge модели.

---



# 5. Constraints в пользовательском вопросе

Система обязана соблюдать ограничения, содержащиеся в вопросе.


| ID     | Type | Priority | Checklist | Требование                                            | Как проверить                             |
| ------ | ---- | -------- | --------- | ----------------------------------------------------- | ----------------------------------------- |
| CON-01 | MUST | P0       | ☐         | Соблюдать time constraint                             | `"under 30 minutes"`                      |
| CON-02 | MUST | P0       | ☐         | Соблюдать diet constraint                             | `"vegetarian"`                            |
| CON-03 | MUST | P0       | ☐         | Соблюдать ingredient constraint                       | Вопрос с ingredient requirement/exclusion |
| CON-04 | MUST | P0       | ☐         | Constraint не должен игнорироваться моделью           | Golden eval                               |
| CON-05 | MUST | P0       | ☐         | Acceptance criteria для constraints определены в SPEC | Review SPEC                               |


---



# 6. Refusal Policy


| ID     | Type   | Priority | Checklist | Требование                                        | Как проверить      |
| ------ | ------ | -------- | --------- | ------------------------------------------------- | ------------------ |
| REF-01 | MUST   | P0       | ☐         | Refuse out-of-corpus questions                    | Golden test        |
| REF-02 | MUST   | P0       | ☐         | Refuse out-of-domain questions                    | Golden test        |
| REF-03 | MUST   | P0       | ☐         | Refusal machine-readable                          | Contract test      |
| REF-04 | MUST   | P0       | ☐         | Используется правильный `refusal_reason`          | Golden test        |
| REF-05 | MUST   | P0       | ☐         | Refusal сформулирован вежливо                     | Manual/eval review |
| REF-06 | SHOULD | P1       | ☐         | Refusal policy явно описана                       | SPEC               |
| REF-07 | SHOULD | P1       | ☐         | Архитектурное решение по refusal policy объяснено | ADR                |
| REF-08 | MUST   | P0       | ☐         | Поведение для empty question определено           | SPEC + test        |


---



# 7. Safety / Allergy

Задание отдельно требует осторожного поведения для вопросов вроде:

> `"Is this nut-free?"`


| ID      | Type | Priority | Checklist | Требование                                                            | Как проверить |
| ------- | ---- | -------- | --------- | --------------------------------------------------------------------- | ------------- |
| SAFE-01 | MUST | P0       | ☐         | Система должна иметь определённую policy для allergy/safety questions | SPEC          |
| SAFE-02 | MUST | P0       | ☐         | Необходимо самостоятельно определить, что означает `"careful"`        | SPEC          |
| SAFE-03 | MUST | P0       | ☐         | Safety refusal должен быть machine-readable                           | Golden test   |
| SAFE-04 | MUST | P0       | ☐         | Нельзя делать unsupported safety/allergy claims                       | Negative test |
| SAFE-05 | MUST | P0       | ☐         | Edge case `"Is this nut-free?"` должен быть обработан явно            | SPEC + test   |




### Важный момент

Задание **не задаёт готовую allergy policy**.

Следовательно, это `ASSUMPTION`: разработчик должен принять решение и записать его в `SPEC.md`.

Нельзя оставить такую логику скрытой внутри кода.

---



# 8. Corpus / Ingestion


| ID      | Type   | Priority | Checklist | Требование                                | Как проверить              |
| ------- | ------ | -------- | --------- | ----------------------------------------- | -------------------------- |
| CORP-01 | MUST   | P0       | ☐         | Используется Wikibooks Cookbook           | Проверить ingestion        |
| CORP-02 | MUST   | P0       | ☐         | Данные получаются через MediaWiki API     | Code review                |
| CORP-03 | MUST   | P0       | ☐         | Corpus содержит 40–60 recipes             | Automated count            |
| CORP-04 | MUST   | P0       | ☐         | Используется несколько категорий          | Проверить ingestion config |
| CORP-05 | MUST   | P0       | ☐         | Corpus имеет variety                      | Corpus review              |
| CORP-06 | MUST   | P0       | ☐         | Разные cuisines                           | Corpus review              |
| CORP-07 | MUST   | P0       | ☐         | Есть overlapping dishes                   | Corpus review              |
| CORP-08 | MUST   | P0       | ☐         | Есть разный уровень structure             | Corpus review              |
| CORP-09 | MUST   | P0       | ☐         | Ingestion script committed                | Git                        |
| CORP-10 | MUST   | P0       | ☐         | Corpus можно пересобрать только из script | Clean checkout + rebuild   |
| CORP-11 | SHOULD | P1       | ☐         | Corpus build воспроизводим                | Повторный ingestion/build  |


---



# 9. Frontend


| ID    | Type         | Priority | Checklist | Требование                          | Как проверить           |
| ----- | ------------ | -------- | --------- | ----------------------------------- | ----------------------- |
| UI-01 | MUST         | P0       | ☐         | Есть web UI                         | Открыть UI              |
| UI-02 | MUST         | P0       | ☐         | Frontend написан на TypeScript      | Repository/build review |
| UI-03 | MUST         | P0       | ☐         | UI — одна страница                  | Review                  |
| UI-04 | MUST         | P0       | ☐         | Можно ввести question               | Manual E2E              |
| UI-05 | MUST         | P0       | ☐         | UI показывает answer                | Manual E2E              |
| UI-06 | MUST         | P0       | ☐         | UI показывает citations             | Manual E2E              |
| UI-07 | MUST         | P0       | ☐         | UI показывает refusals              | Manual E2E              |
| UI-08 | MUST         | P0       | ☐         | UI должен function                  | E2E                     |
| UI-09 | NOT REQUIRED | —        | ☐         | UI appearance/polish не оценивается | Не тратить время        |
| UI-11 | MUST         | P0       | ☐         | Core UI отправляет запрос в `/ask`          | UI integration test     |
| UI-13 | MUST         | P0       | ☐         | Core UI показывает answer и citations list       | Manual/E2E              |
| UI-16 | MUST         | P0       | ☐         | Raw Markdown syntax не отображается пользователю | UI security test    |
| UI-17 | MUST         | P0       | ☐         | При новом вопросе предыдущий результат очищается       | Manual/E2E              |


---



# 10. Deployment

Локального запуска недостаточно.


| ID     | Type   | Priority | Checklist | Требование                                  | Как проверить         |
| ------ | ------ | -------- | --------- | ------------------------------------------- | --------------------- |
| DEP-01 | MUST   | P0       | ☐         | Service deployed                            | Deployment check      |
| DEP-02 | MUST   | P0       | ☐         | Есть public URL для UI                      | HTTP                  |
| DEP-03 | MUST   | P0       | ☐         | Есть public URL для API                     | HTTP                  |
| DEP-04 | MUST   | P0       | ☐         | Evaluator может использовать оба            | External E2E          |
| DEP-05 | MUST   | P0       | ☐         | Есть container-level visibility             | Logs/status/dashboard |
| DEP-06 | MUST   | P0       | ☐         | Способ доступа записан в README             | README review         |
| DEP-07 | SHOULD | P1       | ☐         | Используется Infrastructure as Code         | Repository review     |
| DEP-08 | MUST   | P0       | ☐         | Deployment files committed                  | Git                   |
| DEP-09 | MUST   | P0       | ☐         | New deployment возможен без manual UI steps | Clean deployment      |
| DEP-10 | MUST   | P0       | ☐         | Secrets находятся в environment             | Secret scan           |
| DEP-11 | MUST   | P0       | ☐         | Secrets отсутствуют в repository            | Git/secret scan       |
| DEP-12 | SHOULD | P1       | ☐         | Builds reproducible                         | Rebuild               |
| DEP-13 | SHOULD | P1       | ☐         | Docker preferred                            | Repository            |
| DEP-14 | MUST   | P0       | ☐         | Deployment безопасно запускать дважды       | Deploy twice          |
| DEP-15 | SHOULD | P1       | ☐         | Cheap/free tiers допустимы                  | Cost review           |




### Deployment должен позволять

```
clean repository
      ↓
deployment configuration
      ↓
deployment
      ↓
working UI + API
```

без необходимости вручную настраивать систему через hosting UI.

---



# 11. `SPEC.md`

На текущем этапе спецификация хранится в `docs/03_SPEC.md` как numbered
working draft. Корневой `SPEC.md` — canonical entry point, который ссылается
на этот файл; отдельную копию спеки поддерживать не нужно.


| ID      | Type | Priority | Checklist | Требование                                                  | Как проверить    |
| ------- | ---- | -------- | --------- | ----------------------------------------------------------- | ---------------- |
| SPEC-01 | MUST | P0       | ☐         | Существует `SPEC.md`                                        | File check       |
| SPEC-02 | MUST | P0       | ☐         | SPEC написан до кода                                        | Git history      |
| SPEC-03 | MUST | P0       | ☐         | Описан full API contract                                    | Review           |
| SPEC-04 | MUST | P0       | ☐         | Определена full response schema                             | Review           |
| SPEC-05 | MUST | P0       | ☐         | Есть acceptance criteria                                    | Review           |
| SPEC-06 | MUST | P0       | ☐         | Empty question                                              | SPEC             |
| SPEC-07 | MUST | P0       | ☐         | Out-of-domain question                                      | SPEC             |
| SPEC-08 | MUST | P0       | ☐         | Disagreement between recipes                                | SPEC             |
| SPEC-09 | MUST | P0       | ☐         | Allergy questions                                           | SPEC             |
| SPEC-10 | MUST | P0       | ☐         | Latency budget                                              | SPEC             |
| SPEC-11 | MUST | P0       | ☐         | Cost target / 1,000 questions                               | SPEC             |
| SPEC-12 | MUST | P0       | ☐         | Все ambiguity либо clarified, либо записаны как assumptions | Review           |
| SPEC-13 | MUST | P0       | ☐         | Нет hidden hardcoded behavior                               | Code/spec review |
| SPEC-14 | MUST  | P0       | ☐         | Для core `/ask` описаны все inputs/outputs | Review |


---



# 12. ADRs

Должно быть **2–3 Architecture Decision Records**.


| ID     | Type | Priority | Checklist | Требование                                              | Как проверить |
| ------ | ---- | -------- | --------- | ------------------------------------------------------- | ------------- |
| ADR-01 | MUST | P0       | ☐         | Есть 2–3 ADR                                            | File count    |
| ADR-02 | MUST | P0       | ☐         | ADRs описывают важные architectural choices             | Review        |
| ADR-03 | MUST | P0       | ☐         | Перечислены alternatives                                | Review        |
| ADR-04 | MUST | P0       | ☐         | Определены criteria                                     | Review        |
| ADR-05 | MUST | P0       | ☐         | Описаны trade-offs                                      | Review        |
| ADR-06 | MUST | P0       | ☐         | Где возможно, есть реальные cost/latency numbers        | Review        |
| ADR-07 | MUST | P0       | ☐         | Описаны условия, при которых решение становится invalid | Review        |


Возможные темы:

- chunking strategy;
- retrieval method;
- metadata filters;
- model selection;
- refusal policy;
- caching;
- deployment target.

---



# 13. Eval Harness


| ID      | Type   | Priority | Checklist | Требование                                                  | Как проверить   |
| ------- | ------ | -------- | --------- | ----------------------------------------------------------- | --------------- |
| EVAL-01 | MUST   | P0       | ☐         | Есть golden set                                             | Repository      |
| EVAL-02 | MUST   | P0       | ☐         | 12–15 questions                                             | Count           |
| EVAL-03 | MUST   | P0       | ☐         | Для каждого ожидается correct source                        | Golden data     |
| EVAL-04 | MUST   | P0       | ☐         | Для нужных вопросов ожидается refusal                       | Golden data     |
| EVAL-05 | MUST   | P0       | ☐         | Для constraint questions задан expected behavior            | Golden data     |
| EVAL-06 | MUST   | P0       | ☐         | Есть автоматический script                                  | Run             |
| EVAL-07 | MUST   | P0       | ☐         | Script проверяет JSON contract                              | Run             |
| EVAL-08 | MUST   | P0       | ☐         | Script выдаёт results/report                                | Run             |
| EVAL-09 | MUST   | P0       | ☐         | Manual tests не являются единственным доказательством       | Review          |
| EVAL-10 | SHOULD | P1       | ☐         | Golden set покрывает core + refusals + constraints + safety | Coverage review |
| EVAL-11 | MUST   | P0       | ☐         | `/ask` eval проверяет обычный JSON response contract         | Eval runner      |


---



# 14. Automated Tests


| ID      | Type   | Priority | Checklist | Требование                                       | Как проверить |
| ------- | ------ | -------- | --------- | ------------------------------------------------ | ------------- |
| TEST-01 | MUST   | P0       | ☐         | Есть automated tests                             | Test runner   |
| TEST-02 | MUST   | P0       | ☐         | Тестируется ingestion                            | Tests         |
| TEST-03 | MUST   | P0       | ☐         | Тестируется retrieval                            | Tests         |
| TEST-04 | MUST   | P0       | ☐         | Тестируются filters                              | Tests         |
| TEST-05 | MUST   | P0       | ☐         | Тестируется API contract                         | Tests         |
| TEST-06 | MUST   | P0       | ☐         | Есть granular commit history                     | Git log       |
| TEST-07 | SHOULD | P1       | ☐         | Часть tests была committed before implementation | Git history   |
| TEST-08 | MUST   | P0       | ☐         | Non-LLM logic покрыта automated tests            | Test review   |


---



# 15. [README.md](../README.md)


| ID        | Type   | Priority | Checklist | Требование                                  | Как проверить       |
| --------- | ------ | -------- | --------- | ------------------------------------------- | ------------------- |
| README-01 | MUST   | P0       | ☐         | `README.md` существует                      | File                |
| README-02 | MUST   | P0       | ☐         | Описан local run                            | Follow instructions |
| README-03 | SHOULD | P1       | ☐         | Docker preferred                            | README              |
| README-04 | MUST   | P0       | ☐         | Описан deployment                           | README              |
| README-05 | MUST   | P0       | ☐         | Объяснено, почему выбран provider           | README              |
| README-06 | MUST   | P0       | ☐         | Описан deployment process                   | README              |
| README-07 | MUST   | P0       | ☐         | Cost of one question                        | README              |
| README-08 | MUST   | P0       | ☐         | Cost of 1,000 questions                     | README              |
| README-09 | MUST   | P0       | ☐         | Указаны selected models                     | README              |
| README-10 | MUST   | P0       | ☐         | Объяснён model selection                    | README              |
| README-11 | MUST   | P0       | ☐         | Условия смены на cheaper/more capable model | README              |
| README-12 | MUST   | P0       | ☐         | Current bottleneck                          | README              |
| README-13 | MUST   | P0       | ☐         | Next optimization                           | README              |
| README-14 | MUST   | P0       | ☐         | Описано расследование bad answer            | README              |
| README-15 | MUST   | P0       | ☐         | Описано, что логируется/traced              | README              |
| README-16 | MUST   | P0       | ☐         | Container-level access                      | README              |
| README-17 | MUST   | P0       | ☐         | Public UI URL                               | README              |
| README-18 | MUST   | P0       | ☐         | Public API URL                              | README              |


---



# 16. Observability / Operations


| ID     | Type   | Priority | Checklist | Требование                                          | Как проверить |
| ------ | ------ | -------- | --------- | --------------------------------------------------- | ------------- |
| OPS-02 | MUST   | P0       | ☐         | Можно расследовать bad answer                       | README + logs |
| OPS-03 | MUST   | P0       | ☐         | Описано, что логируется/traced                      | README        |
| OPS-04 | SHOULD | P1       | ☐         | Можно понять retrieval/model path при расследовании | Logs/review   |


> Последний пункт — инженерная интерпретация production/operations требования, а не дословное требование исходного текста.

---



# 17. Cost & Latency


| ID      | Type   | Priority | Checklist | Требование                                               | Как проверить |
| ------- | ------ | -------- | --------- | -------------------------------------------------------- | ------------- |
| PERF-01 | MUST   | P0       | ☐         | В SPEC задан latency budget                              | SPEC          |
| PERF-02 | MUST   | P0       | ☐         | В SPEC задан cost target / 1,000 questions               | SPEC          |
| PERF-03 | MUST   | P0       | ☐         | README содержит cost / question                          | README        |
| PERF-04 | MUST   | P0       | ☐         | README содержит cost / 1,000 questions                   | README        |
| PERF-05 | MUST   | P0       | ☐         | README содержит current bottleneck                       | README        |
| PERF-06 | MUST   | P0       | ☐         | README содержит next optimization                        | README        |
| PERF-07 | SHOULD | P1       | ☐         | ADRs содержат реальные cost/latency numbers где возможно | ADR review    |


---



# 18. AI Coding Workflow


| ID    | Type | Priority | Checklist | Требование                                              | Как проверить    |
| ----- | ---- | -------- | --------- | ------------------------------------------------------- | ---------------- |
| AI-01 | MUST | P0       | ☐         | Agent instructions committed                            | Repo             |
| AI-02 | MUST | P0       | ☐         | `CLAUDE.md` / rule files committed, если использовались | Repo             |
| AI-03 | MUST | P0       | ☐         | Important prompts committed                             | Repo             |
| AI-04 | MUST | P0       | ☐         | Relevant spec files committed                           | Repo             |
| AI-05 | MUST | P0       | ☐         | Есть notes о том, что принято от agent                  | Repo             |
| AI-06 | MUST | P0       | ☐         | Есть notes о том, что переписано самостоятельно         | Repo             |
| AI-07 | MUST | P0       | ☐         | Разработчик несёт ответственность за решения и код      | Review/follow-up |


---



# 19. Production Engineering


| ID     | Type   | Priority | Checklist | Требование                                                | Как проверить   |
| ------ | ------ | -------- | --------- | --------------------------------------------------------- | --------------- |
| ENG-01 | MUST   | P0       | ☐         | Service должен быть production-oriented, не demo          | Overall review  |
| ENG-02 | MUST   | P0       | ☐         | Code quality practices                                    | Code review     |
| ENG-03 | MUST   | P0       | ☐         | Security practices                                        | Security review |
| ENG-04 | MUST   | P0       | ☐         | CI/CD practices                                           | CI/deployment   |
| ENG-05 | MUST   | P0       | ☐         | Operations practices                                      | Ops review      |
| ENG-06 | MUST   | P0       | ☐         | Если production-grade не достигнут — gap записан в README | README          |
| ENG-07 | MUST   | P0       | ☐         | Описано, что необходимо для закрытия gap                  | README          |
| ENG-08 | SHOULD | P1       | ☐         | Reproducible builds                                       | Rebuild         |
| ENG-09 | SHOULD | P1       | ☐         | Infrastructure as Code                                    | Repository      |
| ENG-10 | MUST   | P0       | ☐         | Deployment idempotent                                     | Deploy twice    |
| ENG-11 | SHOULD | P1       | ☐         | CI включает quality/security scans; agent-assisted review используется как advisory check | CI/review |


---



# 20. Scope Constraints

Время и scope также являются частью задания.


| ID       | Type       | Priority | Checklist | Требование                                             | Как проверить |
| -------- | ---------- | -------- | --------- | ------------------------------------------------------ | ------------- |
| SCOPE-01 | MUST       | P0       | ☐         | Time budget: 6–8 часов focused work                    | Process       |
| SCOPE-02 | MUST       | P0       | ☐         | Не добавлять unnecessary polish                        | Scope review  |
| SCOPE-03 | MUST       | P0       | ☐         | Scope cutting должен быть сознательным                 | README        |
| SCOPE-04 | MUST       | P0       | ☐         | Что вырезано, должно быть recorded                     | README        |
| SCOPE-05 | MUST       | P0       | ☐         | Core functions имеют приоритет                         | Review        |
| SCOPE-06 | MUST       | P0       | ☐         | Extra features не заменяют incomplete core             | Review        |
| SCOPE-07 | PREFERENCE | P1       | ☐         | Python preferred для backend                           | Stack         |
| SCOPE-08 | MUST       | P0       | ☐         | TypeScript mandatory для frontend                      | Repository    |
| SCOPE-09 | PREFERENCE | P1       | ☐         | Docker preferred                                       | Deployment    |


---



# 21. Submission


| ID     | Type | Priority | Checklist | Требование                              | Как проверить    |
| ------ | ---- | -------- | --------- | --------------------------------------- | ---------------- |
| SUB-01 | MUST | P0       | ☐         | Private Git repository                  | Repository       |
| SUB-02 | MUST | P0       | ☐         | Evaluator получил access                | Access test      |
| SUB-03 | MUST | P0       | ☐         | Deployed URL указан                     | README           |
| SUB-04 | MUST | P0       | ☐         | Container-level access указан           | README           |
| SUB-05 | MUST | P0       | ☐         | Все deliverables находятся в repository | Repository audit |


---



# 22. Финальный Acceptance Checklist



## 🔴 P0 — Core

- `POST /ask` работает
- `/ask` возвращает task-compatible JSON
- Response соответствует full JSON schema
- Ответы основаны только на retrieved corpus
- Model не отвечает из собственной памяти
- Каждый успешный ответ содержит citations
- Citation содержит title + URL
- Out-of-corpus → machine-readable refusal
- Out-of-domain → machine-readable refusal
- Safety → machine-readable refusal, когда применимо
- Refusal имеет корректный `refusal_reason`
- Empty question имеет определённое поведение
- Time constraint соблюдается
- Diet constraint соблюдается
- Ingredient constraint соблюдается
- Policy для conflicting recipes определена
- Allergy policy определена
- UI работает end-to-end
- Frontend написан на TypeScript
- Standard JSON UI отправляет запрос в `/ask` и показывает answer/citations/refusal



## 🔴 P0 — Corpus

- Wikibooks Cookbook
- MediaWiki API
- 40–60 recipes
- Несколько категорий
- Разные cuisines
- Overlapping dishes
- Разный уровень structure
- Ingestion script committed
- Corpus можно пересобрать из script



## 🔴 P0 — Specification

- `SPEC.md` существует
- `SPEC.md` создан до implementation
- Full API contract
- Inputs/outputs core endpoint-ов
- Full response schema
- Acceptance criteria
- Empty question
- Out-of-domain
- Conflicting recipes
- Allergy questions
- Latency budget
- Cost target / 1,000 questions
- Все ambiguity явно разрешены или записаны как assumptions
- Нет hidden hardcoded behavior



## 🔴 P0 — ADRs

- 2–3 ADRs
- Alternatives
- Decision criteria
- Trade-offs
- Cost/latency numbers где возможно
- Conditions for invalidation



## 🔴 P0 — Evaluation

- Golden set
- 12–15 questions
- Expected source для каждого
- Expected refusal где необходимо
- Expected constraint behavior
- Automated eval script
- Script проверяет JSON contract
- Script выдаёт report
- Manual testing не является единственным доказательством



## 🔴 P0 — Tests

- Automated tests
- Ingestion tests
- Retrieval tests
- Filter tests
- API contract tests
- Granular commit history
- Хотя бы часть tests committed before implementation



## 🔴 P0 — Deployment

- Service deployed
- Public UI URL
- Public API URL
- Container-level access
- Access описан в README
- Deployment definition committed
- New deployment без manual UI steps
- Secrets только environment
- Secrets отсутствуют в repository
- Deployment безопасно выполнить дважды
- Build воспроизводим



## 🔴 P0 — README

- Local run instructions
- Deployment provider
- Why this provider
- Deployment process
- Cost / question
- Cost / 1,000 questions
- Selected models
- Model selection rationale
- Conditions for model change
- Current bottleneck
- Next optimization
- Bad-answer investigation
- Logging/tracing strategy
- Container-level access
- UI URL
- API URL



## 🔴 P0 — AI Workflow

- Agent instructions committed
- Rule files / `CLAUDE.md`, если использовались
- Important prompts committed
- Relevant spec files committed
- Notes: что принято от AI
- Notes: что переписано самостоятельно



## 🟡 P1 — Quality

- Python backend
- Docker
- IaC
- Strong observability
- Cost/latency measurements
- Хорошо обоснованные ADRs



## 🟢 P2 — Bonus

Все bonus requirements вынесены в
[`03_SPEC_APPENDIX.md`](03_SPEC_APPENDIX.md) и оцениваются только
после complete core.

---



# 23. 10 требований, которые особенно легко пропустить

1. **Ответы только из corpus.**
  RAG должен реально ограничивать answer generation.
2. **Machine-readable refusal.**
  Просто написать `"Sorry, I don't know"` в `answer` недостаточно.
3. **Constraints должны реально соблюдаться.**
  Особенно `time`, `diet`, `ingredient`.
4. **Allergy/safety policy должна быть вашей явно задокументированной decision.**
5. **Нужно определить поведение, когда два рецепта противоречат друг другу.**
6. **Corpus должен быть воспроизводимым.**
  Не просто закоммитить полученные 50 рецептов — нужен ingestion script, через который corpus можно собрать снова.
7. **Eval harness обязателен.**
  12–15 golden questions + автоматическая проверка — это часть доказательства корректности системы.
8. **Deployment обязателен.**
  Локально работающий repository не соответствует заданию.
9. **SPEC → ADR → Eval → Code** — это фактически ожидаемый workflow.
  Авторы задания отдельно оценивают способность сначала определить поведение и способ его проверки, а уже потом писать implementation.
10. **Не нужно пытаться сделать всё идеально.**
  Если production-grade не достигнут за отведённое время, нужно честно зафиксировать gap и описать, что требуется для его закрытия.

Источник требований: исходное Take-Home Assignment. 00_TASK.md
