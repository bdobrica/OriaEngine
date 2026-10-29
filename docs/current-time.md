# Current timezone and relative requests

Telegram supplies no current user timezone. After consent, `/timezone` explains
the optional preference; `/timezone Europe/Bucharest` saves an explicitly selected
IANA timezone from the bundled rules. `/timezone UTC` is also valid. `/profile`
shows the preference and `/timezone clear` removes it. Neither a birthplace nor a
model/retrieved memory selects this value. Users travelling to another zone can
change it without altering their birth chart or recalculating natal facts.

Migration `0009` adds nullable `users.current_timezone`. This is a plaintext account
preference in Oria's private database, separate from the encrypted birth profile.
Existing accounts remain unset. The setting command explicitly opts into storage;
it requires existing current consent, and does not change that consent or trigger
another disclosure for ordinary readings. Withdrawal stops changes and readings;
confirmed deletion clears the preference during local cleanup. It is not logged,
embedded into memory or forwarded to SecondContext. No new public HTTP endpoint,
setting, dependency or astrology wire field is introduced.

Time resolution uses the inbound message's persisted, aware UTC arrival timestamp.
Worker delay and retry do not move that reference time. The model receives this
UTC reference in instructions, alongside any calculated target facts; it receives
neither the timezone name nor raw birth inputs. Telegram replies display the
resolved target in the selected local zone as a snapshot before the interpretation.

The bounded English grammar accepts:

- `in 3 hours`, `in three hours`, `30 minutes from now`, `two hours ago`;
  seconds/minutes/hours are elapsed UTC durations and need no timezone;
- `tomorrow`, `yesterday`, `day after tomorrow`, `day before yesterday`;
  these select noon in the chosen local timezone;
- `next Friday`, `last Friday`, `this Friday`; unqualified/next weekday means
  the next occurrence, including seven days later if today has that weekday;
  `this` includes today and otherwise the next occurrence;
- `in 2 days`, `in 2 weeks`, `next week`, `next month`, `next year`, and numeric
  month/year offsets; these preserve local wall time, clamping month ends;
- `tomorrow at 15:30`, `tomorrow at 5pm`, `today at noon`;
- `tomorrow morning` (09:00), `this afternoon` (15:00), `this evening` (18:00),
  `tonight` (21:00), noon (12:00) and midnight (00:00 on the selected date).

Day/calendar/clock requests require an explicit timezone. `today`/`now` without
a clock retain the existing ingress-instant convention; an explicit `YYYY-MM-DD`
retains noon UTC for compatibility, even with a timezone preference. A snapshot
does not cover an entire day, week or month. The user sees the resolved clock time.

Ambiguous/nonexistent local times at clock changes, multiple targets, compound or
fractional offsets, unsupported phrases, explicit competing timezone abbreviations
and targets outside 1800–2399 ask for clarification. This is not unrestricted natural
language understanding. No LLM decides timestamps or authorizes tool calls.
The inbound privacy filter exempts clock text only after deterministic routing
resolves one target; other birth/identifying markers remain blocked.
