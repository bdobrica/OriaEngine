# Known MVP limitations and release checks

The demo pipeline is implemented; [Stage 25](../TODO.md#stage-25--mvp-release-gate)
remains the release gate. Automated tests provide contract and invariant evidence,
not completion of operator checks or proof of model safety/astrological prediction.

## Calculation and input coverage

- [Place lookup](place-resolution.md) uses a fixed GeoNames cities15000 snapshot,
  not every settlement. Matching is deterministic rather than fuzzy; missing places
  remain unresolved. Timezone rules are bundled IANA 2025b, with historical-source
  limitations, particularly before 1970.
- [Natal calculations](astrology-mcp.md) support Gregorian years 1800–2399,
  ten bodies, tropical geocentric positions, Placidus and fixed six-degree major
  aspect orbs. Houses are unavailable at absolute latitudes of 66 degrees or more,
  or when calculation fails. No alternate house system is substituted.
- Unknown birth time produces no natal positions, houses, angles or aspects.
  Approximate time uses the entered instant with uncertainty; it does not compute
  a probability distribution. Unknown-time transits can show general target-time
  positions, without personalized natal relationships.
- [Transit routing](transits-and-routing.md) is a bounded English rule parser.
  “Today” uses the inbound UTC timestamp; an explicit ISO date uses 12:00 UTC,
  not the user's local day. Transit houses/angles and time-to-exact are unavailable.
- The deterministic calculation engine uses the pinned Swiss Ephemeris Moshier
  backend. There is no trained predictive model, outcome collection or scientific
  forecasting claim. See [licensing considerations](astrology-mcp.md#dependency-and-licensing-notes)
  before distribution or public activation.

## Conversation, privacy and reliability

- Telegram private text and supported callbacks are the current channel surface.
  Groups, media and other update types are ignored. Use one bot per database and
  one polling process per bot.
- The [English input/output guards](response-policy.md) are lexical. They can miss
  paraphrases, other languages or encoded PII and can block benign text. Output
  checks do not prove chart truth or model resistance to prompt injection.
- Raw saved birth fields are excluded from SecondContext requests and explicit
  memory ingestion, but filtered active text and generated replies are retained
  remotely. Blocked drafts can already be in upstream history. Users should avoid
  sharing private details in active chat; local replacement does not erase history.
- [Worker retries](worker-queue.md) are bounded and durable. Ambiguous remote context
  calls and Telegram sends can duplicate effects. There is no remote exactly-once
  guarantee, and dead encrypted payloads are erased rather than replayable.
- Encryption supports one configured key/version. There is no automatic keyring
  rotation. Losing or replacing the key makes existing ciphertext inaccessible;
  coordinate explicit re-encryption and secure backups before any change.
- [Deletion](deletion.md) requires authenticated, compatible SecondContext purge.
  An instance that answers chat can still lack purge. Cleanup retries until repair;
  it retains minimal markers/receipts and does not erase Telegram history, backups,
  retired indexes or AI-provider copies.
- Docker health checks do not prove worker actor progress, provider capabilities
  or successful delivery. Metrics are best effort and private; no collector or
  dashboard is installed. The development stack supplies no production TLS endpoint.

## Remaining operator validation

Use the unchecked [Stage 25 checklist](../TODO.md#stage-25--mvp-release-gate) as the
source of remaining release work. It includes live private Telegram onboarding,
chart/transit interpretation, conversation continuity, commands and deletion;
public HTTPS/proxy and webhook activation; PostgreSQL backup/restore; Redis recovery;
clean developer workflows and a successful GitHub Actions run. Configure the
deployed SecondContext authentication, namespace and purge capability consistently
and validate the actual deployment, not only a local contract stub.

[Automated lanes](testing.md) use synthetic data, local HTTP fakes and real isolated
PostgreSQL/Redis/MCP/application containers. They need no provider credentials.
Optional [live tone review](conversation-worker.md#demo-setup) uses a configured
SecondContext/model and is separate from CI. No documentation or automated gate
claims to validate upstream retention, encrypted backups or the public TLS path.
