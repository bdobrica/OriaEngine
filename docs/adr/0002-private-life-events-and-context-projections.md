# ADR 0002: Private life events and scoped context projections

Status: Accepted — 2026-11-08

## Context

The product direction includes natural dates, voluntary personal context, entities
and meaningful life events, with user-controlled correction/deletion and linked
salience in SecondContext. The existing natal-only profile and fixed memory subset
do not implement this. Adult consent and responsibility for sharing do not replace
application ownership, isolation or truthful capability reporting.

## Decision

Oria owns canonical encrypted event/entity records, source provenance, temporal
resolution and revisions in its database. Own-birth events reference the canonical
natal-profile revision. A user-supplied entity is scoped to that user's records,
never merged with another user's data or linked to another Oria account.

SecondContext owns its salience/context projections, retrieval and erasure in its
own database and index. Oria accesses it only through authenticated, versioned
HTTP contracts, preserving ADR 0001. Projection references carry stable record IDs
and revisions. Retrieved text is untrusted context, not authority or calculated
fact. The application validates current ownership, availability and revisions
before using it. Raw birth inputs remain in Oria's calculation path and are not
embedded as semantic memories. Relevant labels and interpretive summaries are
still private data with the same subject scope and lifecycle.

The candidate [knowledge v1 contract](../../contracts/knowledge/v1.md) defines typed
canonical payloads and the proposed projection lifecycle. It does not introduce
live routes or extend credentials. Ingestion is disabled until the owning service
implements and verifies upsert, linked retrieval, revision fencing, selective
erasure (including linked retained history), and full subject purge. Oria uses
durable projection work and deletion fences; remote failure must not restore
forgotten records. Completed acknowledgements must match the exact subject,
operation and record revision. Account erasure continues through the existing
subject-wide purge, extended to cover new records before enabling their storage.

Consenting adults may discuss any topic and voluntarily share personal context.
Harmful/destructive behavior is assessed from the actual request/response rather
than topic keywords. Truthfulness, consent, account isolation and tool authority
remain enforced by the application. New collection/storage uses require accurate
versioned disclosure; no additional registration or consent from mentioned entities
is required. General disclosures stay in consent/help/privacy.

## Consequences

The runtime policy can become less restrictive without enabling event storage or
claiming new calculations. Natural-time parsing, canonical persistence, lifecycle
HTTP implementation and linked calculations ship in subsequent slices. The current
v1 response/memory/purge API and astrology schemas remain compatible. The proposed
wire protocol needs acceptance and implementation in SecondContext's owning
repository before use; this ADR cannot grant capabilities to that service.

The phase-one birth filter is intentionally coarse: a birth-bearing message is
replaced with a value-free conversational goal. It allows discussion without
forwarding raw birth details or guessing structured records. Richer extraction
belongs to the next temporal-routing slice. Broader volunteered chat context is
processed under the new versioned disclosure, with existing transcript/provider
retention limits. No new event/entity storage is enabled by this decision.
