# Astrology calculation service

The stateless FastMCP HTTP service at `/mcp` exposes
`calculate_natal_chart(request)` and the additive Stage 13
[`calculate_transits(request)`](transits-and-routing.md), returning typed facts. It has no
database, user identity, LLM, geocoder or outbound service dependency. The [derived-profile flow](astrology-profiles.md) calls it after explicit profile
confirmation and activates profiles only after successful typed calculation.

## Run and verify

```sh
make bootstrap
make mcp
make mcp-test
make verify
```

For application development, `make dev` includes the private MCP service and
container worker. Use `make mcp-local` with a host worker instead. Stop the previous
local stack before changing modes; see [development](development.md).

`make mcp` builds and starts the Compose `astrology-mcp` service. It is opt-in via
the `astrology` profile, so ordinary database tests and `make infra-up` retain
their existing behavior. The container runs as UID/GID 65532 with a read-only
filesystem, no application secrets, no volumes, no published ports and a private
internal network. An application container must join the same `astrology` network
and use `http://astrology-mcp:8000/mcp`. Do not expose this unauthenticated endpoint
publicly. For host-run polling, `make mcp-local` explicitly adds loopback port
8000 through `deploy/compose.polling.yaml`; set `ASTROLOGY_MCP_URL` accordingly.
`make infra-down` removes the local project's containers.

Liveness is `/healthz`. Readiness at `/readyz` verifies pinned dependency versions
and executes a synthetic known-time calculation; failures return a generic 503.
The image health check calls readiness. Logs use the existing payload-free JSON
formatter, and validation/calculation errors returned over MCP are also generic.
Raw arguments, numerical chart results and library diagnostics are never logged.

`make mcp-test` builds a separate Compose project, waits for readiness, calls
known- and unknown-time natal and transit requests over real HTTP MCP, validates the typed results,
checks container isolation and removes that project's containers/network. It never
touches developer database volumes. Docker, build-network access and a C compiler
in the build image are required; the final image has no compiler. The first build
may take several minutes. `make verify` includes all contract tests and this test.

## Version 1 contract

The [MCP transport limits](../contracts/astrology/transport-v1.md) bound each HTTP
response to 256 KiB before SDK parsing and each operation to 20 seconds. The consumer
requests uncompressed JSON/SSE and rejects compressed responses. Calculation schemas
and numerical meanings remain unchanged.

The published [JSON schemas](../contracts/astrology/v1.json) are generated from
[`contracts.py`](../src/oria_engine/astrology/contracts.py). MCP arguments have a
single `request` property. Both nested and top-level identity/extra attributes are
rejected. The schema version is distinct from the calculation-engine version.
Changes to accepted inputs or output meanings require explicit compatibility
review, updated schemas/docs and fixtures; do not silently reinterpret v1.

Regenerate with `uv run python scripts/generate_astrology_schema.py`; contract
tests run its `--check` mode to detect drift. Private wire models redact repr/str;
serialization is intended only for the authorized calculation boundary.

Known-time requests supply an explicitly UTC `timestamp_utc` and accuracy
`exact` or `approximate`. Unknown-time requests supply only `local_birth_date`
and accuracy `unknown`. All require latitude/longitude; coordinates are decimal
degrees, north/east positive. Only Gregorian years 1800–2399 and house system
`P` (Placidus) are supported. OriaEngine remains responsible for prior consent,
place normalization and historical local-to-UTC resolution.

Unknown time returns empty planets/aspects/cusps, null angles and explicit
unavailability. The service does not calculate a noon chart or invent a UTC
instant. Approximate time calculates the entered instant with an uncertainty
reason; its angles/houses are approximate too, not authoritative exact facts.

## Calculation conventions

- `pyswisseph==2.10.3.2`, Swiss Ephemeris `2.10.03`, engine `oria-natal-1`.
- Explicit **Moshier** backend built into that release; no external ephemeris files.
  This is a deliberate demo baseline, not an automatic fallback from Swiss/JPL
  files. Every planetary result checks the returned backend flags. An external
  `SE_EPHE_PATH` is rejected. The versioned built-in tables define data provenance.
- Apparent geocentric tropical ecliptic longitude of date for Sun, Moon, Mercury,
  Venus, Mars, Jupiter, Saturn, Uranus, Neptune and Pluto, in that order. Longitude
  is `[0,360)` degrees; speed is degrees/day. Negative speed means retrograde.
- UTC is converted using `utc_to_jd` to TT for positions and UT1 for houses, using
  the pinned library's leap-second/Delta-T conventions and Moshier tidal setting.
  Before 1972 the library interprets the civil input as UT1. This historical
  convention is part of v1, not a claim to subsecond historical time accuracy.
- Placidus houses/Ascendant/MC are available below absolute latitude 66 degrees
  when the library succeeds. At higher latitudes or on house failure they are
  absent with `houses_unsupported`; no alternate system is substituted.
  Planet houses use longitude intervals between successive cusps, inclusive at
  the starting cusp, ignoring ecliptic latitude. This is not Swiss `house_pos`'s
  three-dimensional house-position method.
- Major aspects use a fixed inclusive 6-degree orb: conjunction 0, sextile 60,
  square 90, trine 120 and opposition 180 degrees. Each unordered body pair is
  visited once. Separation is the shortest unsigned angle in `[0,180]`; orb is
  absolute distance from the target. Full-precision numerical measurements are
  preserved, not rounded before classification.
- Relative velocity is longitude speed of `body_b` minus `body_a`. Applying means
  the instantaneous derivative of absolute orb is negative. It is null within
  `1e-8` degrees of exactness/separation cusps or `1e-8` degrees/day of zero relative
  motion. This describes local motion, not a prediction of a future crossing.
  `time_to_exact_hours` is always null and its availability flag false in natal v1.

Library calls are serialized by a process lock and relevant global settings reset
per calculation. Numerical/platform differences are tested with a `1e-6` degree
and degree/day tolerance. This tolerance is a regression threshold, not a claimed
physical accuracy. Changing the engine/backend/conventions requires a version
change and reviewed golden fixtures. Future derived caches must include these
versions along with the source profile and timezone snapshot versions.

## Reference fixtures

The exact-time synthetic fixture is 2000-01-01 12:00:00 UTC, latitude 51.5,
longitude 0. Reference longitudes, speeds, all twelve cusps and angles come from
the standalone upstream **C `swetest` executable**, not from the Oria adapter.
This independently tests the wrapper against the same pinned astronomy library;
it is not independent validation of the underlying ephemeris theory.

Build `libswe/swetest` with `make swetest` in the `pyswisseph` source archive
identified by `uv.lock` (SHA-256
`c54c305e83dbd5d2b71e58d8a69d8ee41de24c4d3328ce09e2af860a3537624d`).
Record the fixture with:

```sh
uv run python scripts/generate_natal_reference.py /path/to/libswe/swetest
```

The generator invokes `-b1.1.2000 -utc12:00:00 -p0123456789 -emos -edir/nonexistent/oria-ephemeris
-house0,51.5,p -fPls -g, -head`. It writes the unmodified CSV reference output.
Do not hand-edit it. The unknown-time JSON fixture records the explicit v1
unavailability policy. Analytical tests additionally cover wraparound, orb
boundaries, stationary/retrograde relative motion and cusp assignment.

## Dependency and licensing notes

The new binding supplies the required astronomical functions; no higher-level
astrology framework or trained model is introduced. Runtime dependencies are
locked in `uv.lock`, and the Docker build uses `uv sync --frozen`.

[Swiss Ephemeris](https://www.astro.com/swisseph/swephinfo_e.htm) offers AGPL and
professional licensing; [pyswisseph](https://pypi.org/project/pyswisseph/) declares
AGPL. This implementation is prepared for local development/testing. Before
distribution or public activation, resolve the licenses for the binding and
underlying engine together; an upstream professional license does not itself
relicense a third-party binding. The repository's existing license is unchanged.

API conventions follow the [Swiss Ephemeris programming manual](https://www.astro.com/swisseph/swephprg.htm)
and the [FastMCP HTTP deployment documentation](https://gofastmcp.com/deployment/http).
