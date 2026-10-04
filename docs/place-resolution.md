# Local place and historical time resolution

`LocalPlaceResolver` reads the bundled GeoNames `cities15000` snapshot, country
names and first-level administrative regions. Lookup never sends a query to an
external service or an LLM. Dataset provenance, input hashes and generated file
hashes are in [`manifest.json`](../src/oria_engine/data/manifest.json).

## Coverage and selection

The [GeoNames export](https://download.geonames.org/export/dump/readme.txt) covers
cities above roughly 15,000 inhabitants and administrative capitals, rather than
every village. Original, ASCII and alternate city names are matched exactly after
case folding, accent removal and whitespace normalization. Countries accept their
English dataset name, ISO alpha-2/alpha-3 code, plus `UK` and `USA`. No fuzzy match,
nearest-city substitution or country-wide default timezone is used.

Every candidate requires a user selection, including a single match. Names and
regions distinguish ambiguous cities. More than eight matches asks for
`city - region, country`, such as `Springfield - Illinois, US`; candidates are
never silently truncated. A missing city remains unresolved. Extend the controlled
dataset if demo users need smaller towns; do not select a different birthplace.

Latitude, longitude and IANA timezone are taken together from the selected
GeoNames record. Its timezone column is the dataset's assignment for that location;
there is no separate polygon lookup or timezone inference from the country.
The selected values stay inside the encrypted profile. Queries are not persisted in drafts/profiles. Post-consent inbound text uses
the temporary encrypted [queue retention](worker-queue.md) rules.

## Historical conversion and clarification

`domain.birth_time` uses Python
[`zoneinfo`](https://docs.python.org/3/library/zoneinfo.html) against the bundled
TZif snapshot (IANA 2025b, imported from the development system's zoneinfo tree).
It explicitly opens these files, so host timezone updates cannot silently change
results. The [IANA database](https://data.iana.org/time-zones/tz-link.html) is public
domain. This is a fixed demo baseline, not a claim to use the latest rule release.
Historical records, especially before 1970, may be incomplete; deterministic
conversion does not establish the historical accuracy of the source records.

Both folds are converted to UTC and round-tripped back to the entered wall time:

- One distinct instant: conversion is unambiguous.
- Two instants: ask for the first or second occurrence, displaying numeric offsets.
- No instant: request date/time/place correction or unknown time; never shift a gap.
- Unknown time: no UTC instant is invented.

Non-hour transitions and skipped dates follow the same rule. Approximate time
retains its accuracy flag; a UTC value is the conversion of that approximate input,
not a claim of exactness or an inferred uncertainty interval. Changing date, time
or place clears the prior occurrence. Stale callbacks cannot reuse that decision.

New onboarding confirmations write profile schema **2**, adding nullable
`birth_time_occurrence` (`0` = earlier UTC instant, `1` = later). Version 2 validates
conversion before encryption. Original local date/time, accuracy and place remain
unchanged. `utc_instant()` derives UTC for the calculation boundary; UTC is
not stored as independent authoritative state. Version 1 ciphertext stays readable;
its unresolved gap/overlap fails conversion rather than choosing implicitly.
The derived-profile flow routes such legacy profiles through clarification before calculation.
No PostgreSQL migration is needed: the existing final-profile version constraint
permits version 2. The internal draft gains an optional occurrence field; older
drafts without it still load. Older application releases cannot read the new
confirmed profiles/drafts: deploy readers and writers together and do not roll
back without a compatible reader.

## Dataset generation

The bundled data is public reference data, not user fixtures. GeoNames attribution:
**GeoNames geographical database, geonames.org**, licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The importer transforms
the export into compressed JSON, retains city names/aliases and calculation fields,
and drops unrelated export columns. No endorsement by GeoNames is implied.

To refresh, download `cities15000.zip`, `countryInfo.txt` and `admin1CodesASCII.txt`
from the GeoNames export directory into a temporary directory. Retain the exact
upstream files for regeneration and verify their checksums against the manifest.
Run from the repository root with a reviewed compiled IANA zoneinfo directory:

```sh
uv run python scripts/import_places.py /tmp/oria-geonames /usr/share/zoneinfo
make verify
```

This writes `src/oria_engine/data/places.json.gz`, `timezones.zip`, and
`manifest.json`. Do not hand-edit these generated artifacts. Archive entries and
gzip timestamps are fixed; matching source files and toolchain reproduce the
outputs. Review data/version changes with the tests before committing. A timezone
refresh may change derived instants; Derived cache validity includes dataset/rule versions and invalidates stale results.

Tests cover country scoping, aliases, candidate bounds, multiple countries, known
UTC fixtures, northern/southern hemisphere overlaps and gaps, a half-hour clock
change, Nepal's historical offset change, Samoa's skipped day, encrypted occurrence
round trips, restart, edits, and final confirmation. Live Telegram checks remain
in [the operator smoke test](telegram.md).
