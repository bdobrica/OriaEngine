# Profile and privacy commands

These commands use deterministic application code and the authenticated private-chat
sender. They never call SecondContext or ask a model to collect profile fields.

| Command | Behavior |
| --- | --- |
| `/profile` | Reads confirmed details and any unconfirmed draft, plus policy/consent and current chart availability. No calculation or profile mutation. |
| `/edit_profile` | Resumes the deterministic field editors after consent. Confirmation saves changes and recomputes the chart. |
| `/retry_profile` | Retries calculation after consent and confirmation; reuses a valid cache. |
| `/privacy` | Shows the current disclosure and Accept/Decline buttons. Displaying it never changes consent. |
| `/help` | Shows commands, AI/astrology limitations and deletion availability, before or after consent. |

Inspection shows date, local time and accuracy, normalized place name/city/region/country,
coordinates, IANA timezone and a selected clock-change occurrence when present. It
does not expose Telegram IDs, database IDs, encryption metadata or callback tokens.
Unselected candidate places are not presented as confirmed birthplaces. Unknown time
shows unavailable chart features; approximate time remains explicitly uncertain.

The confirmed profile and unfinished draft are labelled separately. Inspecting either
does not confirm edits, start collection, rotate buttons or invalidate/recompute a chart.
Missing, stale or consent-ineligible charts are reported as not current/available.
The existing repository permits owner inspection after withdrawal or a policy change;
this does not authorize edits, calculations or model calls. Deleted users remain blocked.

Correct date, time/accuracy or birthplace through `/edit_profile`. Choosing another
place updates its normalized coordinates/timezone; editing date/time/place clears the
clock-change selection and asks for clarification again if needed. These derived fields
are not arbitrary free-text inputs. Unknown birth time can be selected explicitly.

`/privacy` describes actual encrypted profile/draft and queue storage, private derived
facts, retained SecondContext/AI-provider conversations, filtering limits, Telegram
retention, and unavailable deletion. Decline stops collection and readings; it does
not erase prior data. Stage 18 supplies complete deletion. A separate `/about` adds
no necessary disclosure: `/help` and `/privacy` already identify Oria as AI and describe
the interpretive limits of astrology.

Profile replies pass through the existing encrypted worker reply envelope, delivery
consent-revision check, retry and erasure rules. Birth fields are never sent to
SecondContext or application logs. Telegram still retains displayed messages under its
own policies. See [worker queue](worker-queue.md) and [consent flow](consent-flow.md).

Deploy polling and workers with `ORIA_POLICY_VERSION=2026-10-03.1` (bump custom versions
too) and accept the updated disclosure. No database migration or new dependency is needed.
