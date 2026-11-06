# Response policy guard

`domain/policy.py` owns the English demo guard and the allowed onboarding field
set. Deterministic onboarding projects only these fields into the strict birth
schema: date, local time, accuracy, normalized place and repeated-time occurrence.
Coordinates and timezone come from the resolver. Neither the HTTP gateway nor
the context interface exposes arbitrary profile mutation. Existing schema,
consent, field-state and repository checks remain authoritative.

`ConversationContext.respond` checks current consent under the user lock before
any response. Recognized high-stakes inputs receive fixed boundary text without
calling the provider. Otherwise the provider returns an untrusted draft, and the
service applies `guard_reply` before returning it. The low-level HTTP adapter
deliberately remains a wire adapter; callers must use the application service for
policy enforcement. Active Telegram routing shares the high-stakes classifier.

The outbound guard blocks common identifying categories: names, email, phone,
addresses, employer, account/government identifiers, credentials and payment
details. It also detects common requests to recollect birth inputs in active chat.
Birth collection stays in deterministic, consent-checked onboarding; no model
output can grant a collection exception.

High-stakes terms cover medical/diagnostic questions, death, pregnancy/fertility,
accidents, criminality, dangerousness, financial/legal decisions and deterministic
relationship failure. The fixed reply declines astrology-based decisions and
offers low-stakes chart reflection and appropriate professional support. Cancer
as a zodiac sign remains allowed; common diagnostic phrases involving it do not.

Ordinary career/work reflection is supported. The word `trade-offs` is not a
financial transaction. A narrow vocabulary of verb phrases such as `address any
challenges` is distinct from asking for a private address; other identifying
terms and address requests elsewhere in the draft remain checked. The existing
exact standalone application-owned reminder
“A friendly reminder: please use appropriate professional support for medical,
legal or financial decisions.” is excluded from safety matching only; the rest
of the draft is still checked in full. Unsafe claims before or after that sentence
remain blocked. The original reminder stays in the delivered reply. No arbitrary
disclaimer, negation, quotation or category-wide exemption is allowed. Persona
guidance answers ordinary career questions directly and avoids repeating onboarding
disclosures; the original substantive high-stakes restrictions remain in force.
The prompt no longer directs the model to emit that exact reminder. Its narrow
guard allowance remains compatible with existing replies, rather than prescribing
conversation copy. The thorough disclosure belongs in the explicit adult consent
flow; ordinary conversation should respect adult judgment and avoid recurring
warnings, unnecessary refusals and moralizing. See the [dialogue guide](dialogue/README.md).

Matching normalizes Unicode compatibility forms, case, whitespace and invisible
format characters. It conservatively blocks category mentions even in quotations,
negations or otherwise benign drafts. There is no negation escape hatch. A blocked
draft is replaced in full with application copy, never partially redacted or sent
for another generation attempt. No draft, match or user text is logged. There are
no new dependencies, configuration, migrations or wire changes.

## Limits and sequencing

This is a bounded lexical guard, not proof of semantic safety: paraphrases,
unrecognized languages, encoded requests and other obfuscations can evade it.
False positives are intentional in this baseline. It does not validate chart
truth, scrub volunteered PII from incoming messages or remove downstream history.
SecondContext may already have persisted a blocked draft before returning it;
local replacement only controls the response returned by Oria's service.

The [conversation worker](conversation-worker.md) uses this guarded service,
adds a separate conservative inbound filter and requires the updated conversation
storage consent disclosure. Output policy
does not grant consent, mutate profiles, ingest memories or authorize tools.

The synthetic [adversarial corpus](../tests/unit/fixtures/policy-adversarial.json)
simulates a model following hostile user/retrieval instructions; tests check
application replacement, not model resistance to injection. Focused tests also
check ordinary reflection, unknown/approximate-time explanations, Unicode forms,
closed profile fields, the HTTP surface and consent fencing. Live-model evaluation
is recorded in [Stage 16 evidence](evidence/stage-16.md). See also
[Stage 15 evidence](evidence/stage-15.md).
