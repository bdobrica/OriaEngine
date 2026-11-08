# Natural dates, current timezone and clarification

The application resolves bounded English/Gregorian expressions using the message's
persisted aware UTC arrival time, never the worker or model clock. Typed candidates
distinguish life events, birth inputs, anniversaries, own-profile corrections,
calculation targets and other context. A narrative date does not authorize a transit
calculation or a profile mutation. Multiple clauses can have different roles.
Local encrypted event/entity storage and recall are implemented in
[private memory](private-memory.md). Remote projections and linked calculations
remain later [memory slices](conversation-memory-plan.md#delivery-sequence-and-acceptance).

## Supported expressions and precision

| Input | Local resolution |
| --- | --- |
| `in two hours`, `30 minutes from now`, `two hours ago` | Elapsed UTC duration; no timezone required |
| `today`, `tomorrow`, `yesterday`, `this day last year` | Local calendar date for an event |
| `exactly nine months ago`, `in two weeks`, `next month` | Calendar offset, with month-end clamping |
| `May 1st, 2020`, `1 May 2020`, `2020-05-01` | Date-only; no invented event time |
| `May 1st, last year` | Month/day plus the ingress-relative local year |
| `around May 2020`, `May 1st` | Approximate or partial date; missing components stay absent |
| `we married this day last year at 3pm` | Event clock in the selected zone; no automatic transit |
| `May 1st, 2020 at 3pm` without a zone | Local date/time with unknown offset; a calculation asks for a timezone |
| `a week before my birthday next year` | Calendar offset from the selected anniversary occurrence |
| `between May 1st, 2020 and May 3rd, 2020` | Date interval, not a calculation covering a period |

English month names and abbreviations, ordinal day suffixes, ISO dates, weekdays
and the existing relative grammar are supported. Ambiguous numeric formats such as
`04/05/2026`, impossible dates, compound/fractional offsets and unrecognized forms
ask for clarification when used as a date request. This is not unrestricted natural
language understanding or support for every locale/calendar.

Explicit event IANA timezone names or `UTC` override the current preference for
that clause. Abbreviations such as `EST` do not silently choose an offset. Unknown
zones, competing zones and skipped/repeated DST clocks require clarification.
Local days/weeks/months/years use calendar arithmetic; hours/minutes/seconds are
elapsed UTC durations. Month/year offsets clamp month ends, including February 29.
Recurring February 29 birthdays separately ask about February 28/March 1 observance
when needed; their original historical date stays intact.

## Event anchors

An anchor is supplied by the application within the current user's scope. The
resolver accepts a label, date, recurrence and optional event UUID/revision. It
cannot select an account or grant access based on a label. Missing or ambiguous
anchors ask for the event date. Missing anniversary years ask which occurrence;
`the day I was born` means the historical date, while `my birthday next year`
means an annual recurrence. Known anchors retain their supplied revision.

The active flow can read the user's encrypted birth date for an explicit own-birth
anchor. Ordinary readings and partner dates still use only the derived natal cache.
Dates stated earlier in the same message can provisionally anchor subsequent
wedding/birth references. A clarification can supply another event's anchor date.
Same-message and supplied anchors alone are temporary inputs. [Private memory](private-memory.md)
adds saved canonical anchors for weddings, pets, businesses and other recognized events;
ambiguous stored occurrences ask for selection. Corrected/deleted anchors cannot remain
authoritative in suspended questions.

## Pending questions and privacy

Migration `0010` adds one owner-scoped `temporal_clarifications` row per user. Its
payload uses AES-GCM with user UUID, row UUID, purpose and key version as associated
data. It contains the original request/reference, consent UUID, timezone provenance,
local anchors and unresolved mention. No text or date enters broker messages or logs.
It expires 24 hours after the original arrival; answering does not extend that window.
The worker recovery scan erases expired rows. Reads also remove expired/stale-consent
state. Existing owner locks serialize clarification, withdrawal and deletion.

An IANA timezone answer, `next year`, a date, `February 28`/`March 1` or `at 3pm`
can complete the relevant pending question after restart, without repeating the
story. A timezone answer applies to that request; only `/timezone` changes the saved
preference. `/timezone Europe/Berlin` can both save the preference and resume the
pending question. New conversation abandons the previous question. Withdrawal,
account deletion and starting an own-profile edit clear pending state. Recognized
“don't remember/save/store” requests suppress this extra temporary state; ordinary
queue and transcript retention still follows the consent disclosure.

Birth-bearing clauses and obvious continuations remain local. Other clauses and
non-birth resolved temporal values can reach SecondContext as untrusted user-stated
context, not astrology facts or saved events. Raw saved birth values, birth
candidates and birthday anchor dates are not forwarded. Filtering is bounded and
cannot detect every unlabeled/encoded input. No new remote route, memory ingestion
or model-controlled mutation is introduced. Consent version `2026-11-08.4` describes
these temporary records and local own-birthday access; existing users re-consent.

## Timezone preference and calculation compatibility

Telegram supplies no current timezone. `/timezone Europe/Berlin` explicitly saves
one; `/timezone UTC` and `/timezone clear` are supported. Neither birthplace nor a
model/memory guess selects it. Migration `0009`'s nullable `users.current_timezone`
remains a private plaintext preference, shown by `/profile` and removed on account
deletion. It is not a natal-profile field or a semantic memory.

The published single-instant transit v1 conventions remain compatible: bare
`today`/`now` sample ingress, and ISO date-only targets sample noon UTC. Existing
relative calendar-offset targets preserve local wall time; named relative days
sample local noon, with existing named day-part conventions. New named/mixed or
anchored date targets sample local noon only after timezone selection. Explicit
clocks select that clock. These sampling rules never become known canonical event
times. Targets must be within 1800–2399; otherwise valid historical event dates
are not limited by the calculation range. Ranges and multiple requested targets
can be discussed, but request a single sample before invoking the current tool.

Synthetic verification and its limits are recorded in the
[slice 2 evidence](evidence/natural-date-clarification.md).
