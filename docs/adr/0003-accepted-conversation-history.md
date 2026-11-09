# ADR 0003: Accepted conversation history through SecondContext

Status: Accepted — 2026-11-09. Contract decision; runtime OCH2/OCH3 pending.

## Context

SecondContext persists drafts and retrieves memories but does not replay dialogue.
Oria must preserve ordinary follow-ups without letting rejected drafts, old chart
claims or unrelated chats become authoritative context. Its accepted reply and
Telegram delivery can diverge after failures.

## Decision

Adopt the additive [conversation-history v1 consumer contract](../../contracts/second-context/conversation-history-v1.md)
against SecondContext's `conversation-history-1` capability and ADR 0007. Keep the
existing Responses adapter path and subject authentication. The provider owns
ordered history and selection; Oria owns consent, prepared input, current facts,
validation and delivery. ADR 0001/0002 ownership and linked-source erasure remain.

Use managed recent history with explicit acceptance and an ingress-event UUID turn
ID. Commit the accepted reply and encrypted finalization work in the same local
transaction, finalize post-commit, and deliver the saved reply only after its exact
receipt. Persist delivery independently. Later generation resolves pending work;
privacy/consent/erasure operations bypass this continuity barrier. Bounded failures
terminate or recover explicitly; no automatic fallback to untracked generation.

Only narrowly allowlisted prepared local conversational exchanges may use local
acceptance. Exclude profile/onboarding, raw birth input, credentials, private
clarification and privacy/mutation receipts. Source-dependent text requires current
acknowledged source links. A replacement cannot introduce unlinked source facts.
Past text remains dialogue, not current calculations, successful saves or authority.

Withdrawal cancels writes/delivery and wipes pending payloads without reviving them
on reacceptance. Required erasure continues. Expired remote drafts cannot become
history. Linked-session correction/erasure includes accepted/local turns and retry
results; delayed calls cannot recreate erased sessions. Oria rotates a session only
after the old work is resolved and current canonical data is revalidated.

## Consequences

This decision changes no runtime setting, disclosure or route. OCH2/OCH3 require
new DTOs, encrypted durable work and tested recovery. Before enablement, release a
new disclosure version covering replay, local prepared exchanges and accepted but
possibly undelivered replies; require fresh acceptance. Classifier observation is
additional provider processing and needs explicit disclosure before CH4 use.

No exactly-once provider execution or Telegram delivery is promised. Remote
acceptance survives delivery failure and does not assert that the user saw it.
Existing legacy clients remain compatible. Capability, source/deletion lifecycle,
consumer and real-provider checks precede release; health is insufficient.
