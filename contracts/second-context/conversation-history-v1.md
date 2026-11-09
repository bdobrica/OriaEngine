# Oria / SecondContext conversation history — v1

Status: accepted consumer contract, 2026-11-09; **OCH2 adapter implemented;
OCH3 worker integration and rollout pending**.
[ADR 0003](../../docs/adr/0003-accepted-conversation-history.md) records the decision.
This extends [the existing adapter contract](v1.md), not astrology, canonical records,
linked-context ownership or credential authority.

The owning specification is SecondContext's
[conversation-history v1](https://github.com/bdobrica/SecondContext/blob/bbd1e1b06c33050c3b6714d180b98bf33a15f1ca/docs/contracts/conversation-history-v1.md)
and [ADR 0007](https://github.com/bdobrica/SecondContext/blob/bbd1e1b06c33050c3b6714d180b98bf33a15f1ca/docs/adr/0007-conversation-history.md).
The [schema snapshot](conversation-history-v1.schema.json) and
[synthetic fixtures](conversation-history-v1.examples.json) are copied from that
repository's public `docs/contracts/` sources at commit `bbd1e1b`, never its internal types. Update/check
with `python scripts/sync_history_contract.py --source /path/to/SecondContext`
(add `--check` to compare only). Normal tests use the checked-in snapshot and do
not require a sibling checkout. The provider owns schema changes; review compatibility
before syncing. Schemas validate shape, not ownership or service capability.

## Consumer wire profile

Use existing service bearer and exact `X-SecondContext-Subject`, plus exact body
`user`; legacy subject-bound mode remains supported. Do not send Telegram IDs.
Keep `POST /v1/responses` with filtered input, current instructions/facts and
`metadata.session_id`. Add:

```text
X-SecondContext-Session: <same persisted conversation UUID>
X-SecondContext-History: recent
X-SecondContext-Turn: <persisted inbound_events UUID>
X-SecondContext-Acceptance: explicit
```

A session is scoped to the owner; the ingress UUID remains unchanged across worker
retries. One event creates at most one managed exchange. Freeze the prepared request,
including time/facts/source revisions, for an attempted turn; retry the same body.
Do not rebuild facts on ambiguous retry or reuse an ID for a different operation.
If canonical state changes, cancel the old work and prepare a later eligible event
in a revalidated session. No raw inbound envelope enters SecondContext.

Before enablement, POST `/v1/context/capabilities` with `{user}`. Require exact
subject, contract 1, implementation `conversation-history-1`, ready, both generation
endpoints, single-user-text managed input, recent/off modes, explicit/generated
acceptance, all three finalize actions, linked-session coverage and limits sufficient
for Oria's 4,096-character input and 16,384-character accepted reply. Baseline recent
cap is eight exchanges; the prompt budget may include fewer. Unknown/partial results,
unsupported routes or wrong identities fail closed; health does not imply support.
Old deployments remain usable only through the explicitly configured legacy mode.
History enabled against an unsupported provider is a configuration failure, not a
silent downgrade. Typed adapters, bounded HTTP and capability caching belong to OCH2.

A generated result remains an untrusted draft. Validate the existing Responses body
and exact managed Contract/Session/Turn/Snapshot headers. Bind the response ID to
the saved turn. Do not infer acceptance from a complete generation. Finalize with
`contract_version:1`, exact user/session_id/turn_id, `action:"accept_generated"`,
response_id and assistant_text after all local validation/replacement. Verify the
closed receipt, every identity, action, status accepted, positive sequence, response
ID and linked-session coverage. A replacement may omit source content but cannot
introduce new canonical dependencies beyond those linked before generation.

## Acceptance, delivery and recovery

1. Resolve the earliest eligible event and current consent/source state under the
   existing owner serialization. Durably save the encrypted prepared request before
   the first provider attempt, without committing partial domain mutations merely
   to freeze it. Recovery must not reconstruct changed facts/time for the same ID.
2. Generate the pending draft and validate the reply. Commit domain changes, the
   exact saved reply and encrypted finalize work atomically. Pre-commit failure
   does not authorize sending that reply or making an acceptance mutation.
3. A post-commit worker rechecks consent/revisions, finalizes that exact reply and
   durably records the exact receipt. Lost acknowledgement retries the same body.
4. Deliver the saved reply through Telegram, independently recording successful,
   known-failed or ambiguous delivery. Never generate again merely to retry delivery.
5. Resolve pending finalize/delivery before later generation. Do not assume an
   accepted reply was shown; if a terminal delivery failure/ambiguity affects the
   next turn, supply an application instruction that prior reply delivery is
   unconfirmed. Do not represent that reply as something the user read.

Recovery uses existing five-attempt/24-hour inbound retention bounds; a separate
finalize retry stage must not reset that envelope lifetime or create infinite
head-of-line blocking. Retry transient errors with bounded backoff. On exhaustion,
mark the event terminal, wipe payloads and attempt a payload-free `abandon` for a
still-pending turn. Abandon is post-commit work and requires the same scoped IDs.
Keep only the minimal cancellation identifiers until acknowledgement or remote
24-hour pending expiry; no text reconstruction. Accepted turns cannot be abandoned:
if acceptance may already have committed, retry the exact saved accept while its
payload exists; after expiry mark acceptance/delivery uncertain and do not claim it
failed or resend a regenerated reply. The next session request may encounter a
pending barrier until abandonment/expiry resolves; no legacy bypass.

A provider terminal conflict, expired turn or deleted session ends that old event;
it is not a reason to allocate another ID to replay the same canceled input. A new
user event may proceed after recovery. If delivery failed after remote acceptance,
the accepted exchange remains eligible. Channel delivery is not part of remote
receipt state. OCH3 must test interrupted calls, lease recovery and bounded terminal
paths, not promise exactly-once generation or Telegram sends.

Privacy commands, inspection, withdrawal, selective erasure and account deletion
must remain serviceable while continuity is pending. Recheck current policy and
consent revision before generation, finalize and delivery. Withdrawal wipes pending
input/reply/finalize content and cancels late writes/delivery; abandonment cleanup
and required erasure may still run. Reacceptance never revives canceled payloads.
Saved accepted history is not automatically erased by withdrawal, consistent with
existing policy; users retain deletion controls. A remote write already accepted
before withdrawal may remain; do not claim otherwise.

## Local exchange eligibility and sources

`accept_local` supplies prepared user_text, assistant_text and knowledge_refs, without
a response ID. It is allowed only for an active-consent conversational branch:

| Local result | Capture rule |
| --- | --- |
| Ordinary conversational follow-up/question or deterministic answer | Prepared active input and validated reply; no restricted content |
| Current local calculated reading | Only if all canonical dependencies already have acknowledged current projections; typed facts stay local and reply passes preparation |
| Onboarding, saved profile display/edit, birth/date/record private clarification | Never capture |
| Consent/help/privacy, memory inspection, save/correct/forget receipts, deletion confirmations, error/status messages | Never capture |
| Secret-bearing input, raw birth fields/continuations, routing/account identifiers | Never capture; no raw-to-local-finalize escape path |

Ordinary non-birth conversational questions can be captured; temporary encrypted
clarifications carrying private candidates cannot. Do not automatically capture every
local handler. If eligibility/preparation is uncertain, omit the whole exchange.
The generated and local variants share input/reply character bounds. Strings are
not semantic privacy detection; use the active-input preparation and reply checks.

For either variant, current canonical source references go through existing
linked-context validation/linking. Include every dependency of retained derived
text; a bare empty array must not hide a calculated reading's sources. Pending
projection delivery, stale revisions, unavailable linked capability or pending
selective erasure prevent source-dependent capture and remote generation; keep
local fallback replies under their existing lifecycle without pretending they were
remembered. No arbitrary metadata or canonical record/birth serialization is added.

## Erasure, retention and disclosure review

Replay is separate from fixed semantic memories and linked interpretation summaries.
“Don't remember this” continues to suppress additional canonical/interpretation
learning, not establish private-chat mode. Never treat a past reading as current
chart data; current calculation/revision checks remain mandatory.

The provider retains accepted transcript/results until session/subject erasure;
its 24-hour pending limit is not an accepted-history TTL. Oria's prepared requests,
accepted replies and finalize payloads are encrypted, owner/event/kind bound and
erased on event completion/terminal expiry within the existing 24-hour worker lifecycle.
No durable local transcript archive is added. Payload-free sequence/receipt/delivery
state can remain for deduplication; remove new owner rows on account deletion.

Local pending erasure suppresses replay/classification immediately. Exact linked
correction/erasure acknowledgement includes the whole linked session, new turn rows,
retained original drafts/results and retry content. A payload-free remote session
fence prevents delayed recreation. Rotate Oria's persisted session UUID only after
cleanup/current canonical revalidation, and never migrate canceled/old transcript
into it. Full-subject purge covers new state under the existing permanent subject
fence. No remote forgetting claim until exact erasure acknowledgement. Independent
unlinked chat, provider retention, backups and Telegram remain separate.

Review outcome: disclosure `2026-11-08.5` describes retained filtered messages,
blocked drafts and linked erasure, but not explicit history replay, sending prepared
local exchanges, or classification of previous dialogue. These are additional
processing to disclose. OCH3/OCH5 MUST publish a new version and require fresh
acceptance in ingress and workers before enabling the feature. Do not change the
live policy in this contract-only slice or claim history already works.

Required release copy must explain: bounded earlier accepted dialogue may be sent
again to SecondContext's model; eligible prepared local exchanges are included;
accepted replies can be retained/replayed even if Telegram delivery fails; rejected
drafts are excluded from replay but may remain in retry/provider storage until their
applicable cleanup; pending payloads expire while accepted history follows erasure;
linked deletion can remove entire sessions; no automatic memory extraction occurs.
Before observation/adaptive mode, also disclose OpenAI Decisions processing of
current and bounded earlier dialogue, separately from generation. Keep these
statements in consent/help/privacy, not recurring conversational disclaimers.

## Validation and remaining delivery

Schema fixture tests and snapshot comparison establish the agreed wire shapes.
OCH2 implements [DTO/HTTP/receipt validation](../../docs/conversation-history-adapter.md),
OCH3 adds durable transactions/recovery and OCH4
real integration replay checks, including incorrect receipt identities, local input
exclusions, replaced drafts, lost acknowledgements, terminal delivery failure,
withdrawal/reacceptance, missing source links and selective/full deletion races.
CH2/CH3 must prove service implementation before OCH5 enablement. Decisions and
cache economics remain inside SecondContext and outside this consumer API.
