# Relative time and ordinary career readings

## Change

Migration `0009` adds an optional explicit current timezone preference. `/timezone`
sets/clears it under existing consent and user locks; `/profile` displays it.
Birthplace and natal cache validity are unchanged. Deletion clears the preference
during local cleanup. The deterministic English router resolves supported relative
and local-clock targets against persisted ingress time, with bundled timezone rules
and clarification for DST gaps/folds. Existing ISO-date noon-UTC behavior remains.
The model receives the request's UTC clock reference, never the timezone preference.

Ordinary career reflection remains supported. Policy matching distinguishes
`trade-offs` and a narrow vocabulary of work-related `address` verb phrases from
financial transactions and private-address collection. The exact application-owned
professional-support reminder is allowed while every other part of the reply
remains checked. Serious high-stakes requests and unsafe generated claims retain
their existing boundaries; a disclaimer does not authorize them.

## Diagnostics and validation

The existing live worker metrics showed two output-policy replacements and no
input high-stakes block in the inspected window. Original conversation text and
blocked drafts were not read: logs exclude them and completed Oria event payloads
are erased. No transcript database access or Server-Tools modification was used.

Focused checks cover UTC/local date boundaries, elapsed versus calendar offsets,
month ends, named weekdays, local clocks, DST gaps/folds, invalid/multiple targets,
legacy date compatibility, consent, owner isolation, natal-cache preservation,
deletion, clock privacy filtering and reminders preceding/following unsafe claims.
The adapter contract verifies aware UTC clock instructions without new wire fields.

The final `make verify UV=/tmp/oria-tools/bin/uv` gate passed: Ruff formatting/lint,
strict mypy, 14 release-selection tests, 431 unit tests, 122 integration tests,
112 contract tests and 11 Telegram replay tests. Docker services used disposable
test projects, distinct from the live deployment. Migration upgrade/repeat/downgrade,
metadata checks and both development/published-image-style deployment fixtures passed.
Two upstream TestClient deprecation warnings were non-fatal. No dependency/lockfile,
generated astrology schema or SecondContext implementation change was required.

Live MCP/SecondContext checks used disposable synthetic subjects and the candidate
image. Relative work questions and a career follow-up produced calculated/guarded
replies successfully in the final sample. Each synthetic subject was purged,
including on failed checks; repeated purge was verified. No Telegram user message
was sent by these checks. These samples are not a guarantee of model behavior.

## Live application update

The local application image `oria-live-test:relative-time-20261029` is
`sha256:895e76228c82dd08057a94136bd39f41771ce832b5b84f5dd76052cb4cea1113`.
Only gateway and worker were stopped/recreated. An isolated one-off Oria migration
job completed successfully before their restart; SecondContext and infrastructure
were not restarted. A read through Oria's own connection confirmed revision `0009`
and the timezone column without reading profile values. All seven persistent
services were healthy. The private deployment env still has mode `0600`; stable keys,
tokens and webhook registration were preserved. No image was published.

Post-update gateway liveness/readiness, secret rejection, malformed-body rejection
and body limits passed. Public HTTPS rejected an unauthenticated webhook with 403.
Telegram still reported the correct webhook/update types, no pending updates and
no delivery error. The private operator snapshot reported healthy DB/Redis, zero
queued work and no dead jobs. These checks did not admit or send Telegram messages.

## Remaining limits

Relative parsing is a documented bounded English grammar, not unrestricted natural
language understanding. A calculated snapshot is not an entire-day/week forecast.
The lexical guard can still reject other benign phrasings. The previously observed
SecondContext transcript-replay limitation remains; follow-ups have current natal
facts but do not automatically recover the preceding transit snapshot.
Real-user verification of the new timezone command and corrected readings remains
an operator rehearsal after deployment. Authenticated private transcript inspection
requires an owning-service read contract; raw chat logging remains disabled.
