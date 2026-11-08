# AGENTS.md

Make the **smallest coherent change** that satisfies the task while preserving this repository's ownership boundary, published contracts, compatibility obligations, and the cross-component security model. Do not fix unrelated issues opportunistically; report them separately when relevant.

## Read before changing

Before modifying behavior:

1. Read the relevant accepted records in `docs/adr/`.
2. Read the affected contracts, API/schema definitions, and normative security/architecture documentation.
3. Read `PLAN.md` and `TODO.md` for current implementation intent when they exist.
4. Treat `README.md` as orientation, not as the normative architecture specification.

When sources conflict, use this order for intended behavior:

**accepted ADRs → versioned contracts/API schemas → normative security/architecture docs → PLAN.md → TODO.md → README.md**

Code and tests are implementation evidence, not architectural authority. Do not silently weaken an accepted decision, security invariant, or published contract merely to match current implementation.

If the authoritative sources are ambiguous or incomplete, prefer the change that preserves existing external behavior and component boundaries. Do not invent a new cross-component responsibility or security rule without an explicit architectural basis.

## Engineering rules

* Do not create direct cross-repository database access or depend on another repository's `internal` implementation types.
* Cross-component behavior must use versioned wire/schema contracts and stable identifiers.
* Preserve backward compatibility for published contracts unless an accepted architectural decision explicitly permits a breaking change.
* Do not let Skills, marketplace metadata, Workspace membership, memory, model output, or guardrail results expand Run authority.
* Keep credentials and long-lived secrets outside untrusted agent/harness state. Never commit secrets, credentials, tokens, or sensitive runtime payloads to source, fixtures, logs, documentation, or evidence.
* Treat caches, indexes, projections, and derived state as non-authoritative unless an accepted ADR explicitly says otherwise.
* Public API/schema changes require corresponding contract, compatibility, documentation, and test updates.
* Accepted ADRs are immutable in meaning. Supersede an accepted ADR with a new ADR instead of rewriting architectural history.
* Avoid speculative abstractions and unrelated refactors.
* New dependencies require a concrete repository-local justification.
* Do not hand-edit generated artifacts when a source definition or generator exists. Modify the source and regenerate using the repository's documented workflow.
* Follow existing repository conventions unless they conflict with a higher-authority source listed above.

## Adult conversation experience

* OriaEngine is primarily a technology showcase for consenting adults. Preserve the thorough, versioned policy disclosure and explicit adult consent in the application flow.
* After consent, keep dialogue as free, natural, and useful as possible. Trust adults to make their own decisions; avoid moralizing, paternalism, unnecessary refusals, and unsolicited protective coaching.
* Users are responsible for what they voluntarily share with Oria, including information about other people. Volunteered personal context is not itself a reason to refuse, lecture, or redirect the conversation to profile editing.
* Support natural discussion about people, pets, organizations and possessions. After consent, learn meaningful user-disclosed events within the accepted data use; honor requests not to remember. Oria remains responsible for secure storage, account isolation, retrieval, correction and deletion. Follow the [natural-time and life-event design](docs/conversation-memory-plan.md); local encrypted event/entity learning, lookup, correction and erasure are implemented in the [private-memory reference](docs/private-memory.md). SecondContext projections and linked calculations remain planned.
* Treat relative, absolute, mixed and event-anchored dates as ordinary language. Resolve against persisted message arrival and explicit timezone/anchor context; preserve date-only/approximate precision. Distinguish life events, calculation targets and own-profile edits instead of routing every date to transits.
* The [natural-date resolver](docs/current-time.md) and encrypted 24-hour clarification state are implemented. Resume clarification against the original ingress reference, keep birth candidates local, and clear temporary state on withdrawal/deletion. Temporary clarification is not itself a successful save acknowledgement. Canonical mutations and receipts must commit together; local erasure never claims remote transcript erasure.
* Use SecondContext for scoped salience and linked interpretations through versioned contracts. Keep canonical event/entity records in Oria; validate retrieved references and revisions. House-topic associations are interpretive metadata, not evidence of calculated houses or an established correlation.
* Relationship compatibility and synastry, including requested interpretive ratings using a partner's supplied birth details, are ordinary supported product use cases. Do not require the partner to register, complete onboarding, or separately accept Oria's policy. Ask only for calculation inputs that help the requested reading; work with partial information when possible.
* Distinguish calculation inputs shared in conversation from changes to the user's saved profile. A partner's birthday is not an instruction to edit that profile or a transit target. Keep shared information within the requesting user's scope and deletion lifecycle; never create access to another account's records.
* Keep general AI/astrology disclosures in the consent, help, and privacy surfaces. Do not hardcode recurring disclaimers or professional-support reminders into ordinary conversation or example turns.
* Give the requested reading directly and weave calculated facts and interpretation into the discussion. Explain a specific missing fact or uncertainty when it affects the answer; do not prepend a general warning to each reading.
* Apply relevant privacy, authorization, and substantive safety boundaries proportionately. When a request actually crosses a boundary, respond briefly and specifically, then continue with useful supported conversation. Adult consent does not authorize fabricated facts, access to another account's private records, or expanded model/tool authority.
* Assess harmful or destructive behavior from the request and proposed answer, not isolated words or a blanket topic ban. Ordinary discussion and insight about health, finances, grief, relationships or other sensitive subjects remain supported. Do not encourage or enable harm to the user or other entities.
* Treat the authored [dialogue sketches and review guide](docs/dialogue/README.md) as conversational design references, not production scripts or evidence about a real user.

## Shared-host operations

* This server also runs unrelated projects. Restrict container maintenance to explicitly identified Oria Compose projects; the active MVP project is `oria-live-test`.
* Never use host-wide container, image, network or volume pruning for Oria cleanup. Preserve live storage and secrets; remove only identified disposable Oria resources.
* Prefer published, versioned Quay images pinned by digest for the MVP. Follow [deployment instructions](docs/deployment.md) and verify publication before changing live image references.

## Repository and documentation hygiene

* Keep the root `README.md` concise: purpose, status, quick start, key concepts, and links to durable documentation.
* Do not duplicate `PLAN.md` in the README.
* Move durable implemented decisions into `docs/adr/` and durable reference material into `docs/`.
* Prefer Mermaid for architecture diagrams and relative links for repository-local documentation.
* Use RFC 2119/8174 normative terms only when the requirement is intentionally normative.
* Keep current implementation sequencing and remaining work in `PLAN.md`/`TODO.md`.
* Keep release, validation, and implementation evidence in `docs/evidence/` or the repository's existing evidence area.
* Remove completed TODO/plan items when appropriate rather than using `TODO.md` or `PLAN.md` as a changelog.

## Verification

* Use the repository's documented developer commands. Prefer the root aggregate verification target (for example, `make verify`) when one exists.
* Run focused tests first, then the broadest practical repository gate for the change.
* Tests should validate intended contracts and invariants, not merely preserve accidental current behavior.
* Run generators, formatters, linters, schema checks, migrations, and compatibility checks when the affected area requires them.
* Do not claim that a test, migration, generator, live-provider check, deployment check, or other verification step was run when it was not.
* If verification cannot be run, state what was not verified and why.

## Completing implementation

After a successful implementation:

* Update `TODO.md` and `PLAN.md` when the change affects current sequencing, remaining work, or implementation intent. Do not update them solely to record that a completed task occurred.
* Record durable verification or release evidence in the repository's established evidence area when required.
* Review the final diff for unrelated changes, generated-file drift, accidental secrets, and unintended contract changes.
* Summarize what changed and what verification was performed.

When the task and execution environment permit committing changes:

* Commit the completed coherent change to the active branch to preserve work lineage.
* Use one of these commit prefixes as appropriate: `docs`, `feat`, `build`, `fix`, or `ci`.
* An optional component scope may be added, for example `feat(runtime): ...`.
* Keep the commit message concise and specific to the implemented change.
* Include related `PLAN.md`/`TODO.md` updates in the same logical commit unless repository conventions require otherwise.
