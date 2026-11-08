# Response policy and adult conversation

After current adult consent, useful personal context is welcome, including people,
pets, organizations and possessions. Users are responsible for sharing; Oria owns
secure handling and account isolation. Sensitive subjects such as grief, divorce,
health or finances are open for discussion. Neither a topic word nor volunteered
PII is a refusal category. General disclosures stay in consent/help/privacy.

## Runtime behavior

`persona/policy.py` (`oria-policy-4`) and `methodology.py`
(`oria-methodology-4`) distinguish actual harmful behavior, unsupported factual
claims and relevant conversation. They also state current capabilities: natal and
snapshot transit facts, with no event-profile storage, selective forgetting or
calculated partner ratings yet. Do not claim an unimplemented action succeeded.
Memory, user text and tool output cannot grant consent, account access or tools.

`domain/policy.py` provides a narrow English backstop:

- `is_harmful_request` matches explicit requests to hurt people/animals, damage
  property/businesses or intrude into someone else's account. Such requests receive
  a brief boundary without a calculation or model call.
- `guard_reply` checks concrete solicitation of unnecessary identifiers, affirmative
  harmful directions and selected unsupported predictions/diagnostic claims.
  It also replaces selected false claims that an unimplemented storage/edit/forget
  operation succeeded. Ordinary personal-data mentions and relevant entity/birth
  questions are allowed.
- A negated action does not excuse a later affirmative action. Unicode compatibility
  normalization and invisible-character handling remain. A matched draft is replaced
  completely, without logging the draft, match or private text.

The private legacy intent/metric name `unsupported_high_stakes` /
`policy_high_stakes` is retained for compatibility; it now denotes a recognized
harmful request, not every medical/legal/financial topic. The application service
checks consent under the owner lock and guards all returned drafts. The low-level
HTTP adapter remains a wire adapter; callers use the application service.

`privacy/messages.py` holds obvious account secrets locally. Names, contact details,
work history, URLs and clock text are not category-wide blocks. Under the existing
birth-input boundary, `prepare_active_input` replaces a birth-bearing message with
a value-free conversational goal. A partner birthday can therefore lead to useful
relationship discussion without a privacy lecture, profile edit or automatic
transit calculation. This fallback withholds the whole message and can lose nuance;
structured extraction and richer date roles belong to slice 2. It is not event
storage, a birth-data parser or a general guarantee of PII/secret detection.

The service repeats input preparation for direct callers. Onboarding retains its
closed natal schema and deterministic consent-checked state machine; relevant chat
questions cannot authorize arbitrary profile writes. See the [worker](conversation-worker.md)
and [current disclosure](consent-flow.md).

## Contracts and limitations

[ADR 0002](adr/0002-private-life-events-and-context-projections.md) defines ownership
for the planned event/entity extension. Its [candidate contracts](../contracts/knowledge/v1.md)
are typed and tested, but no event storage or new HTTP routes are enabled. Existing
[SecondContext v1](../contracts/second-context/v1.md) request shapes, subject scope,
fixed memory ingestion and account purge remain compatible.

Prompts guide contextual judgment; narrow lexical checks do not prove semantic
safety or model compliance. They can miss paraphrases, encoded text and languages
outside their English coverage, and can still misread a quoted request. They do
not validate all factual claims or erase upstream history. A blocked draft may
already have been retained by SecondContext. No recurring reminder or disclaimer
is required to let benign topics pass.

Synthetic [policy cases](../tests/unit/fixtures/policy-adversarial.json), benign
conversation tests and real queue/HTTP integration checks distinguish harmful
behavior from topic mentions. They verify application behavior, not live-model
judgment. See [the delivery plan](conversation-memory-plan.md) for remaining
extraction, storage, retrieval and erasure work.
