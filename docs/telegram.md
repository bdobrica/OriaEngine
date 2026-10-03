# Local Telegram polling

## Development bot setup

1. In Telegram, open the official [@BotFather](https://t.me/BotFather), send
   `/newbot`, and follow the prompts for a name and username. This is a manual
   account step; see the [Telegram tutorial](https://core.telegram.org/bots/tutorial).
2. Run `make env` and put the token in `TELEGRAM_BOT_TOKEN` in your local `.env`.
   Never commit the token or paste it into logs, issues, or test fixtures.
3. Configure `DATABASE_URL`, a stable `PROFILE_ENCRYPTION_KEY`, and
   `ORIA_POLICY_VERSION=2026-10-03` (bump custom versions too). Run `make infra-up`
   and `make migrate` to apply revision `0007`, run `make mcp-local`, then
   `make worker` in one terminal and `make run` in another with `APP_ENV=development`. Only one polling process can use
   a bot token at a time ([aiogram polling documentation](https://docs.aiogram.dev/en/latest/dispatcher/long_polling.html)).
4. Open your development bot's private chat and send `/start`, then `/help`.
   Expect the versioned disclosure with **I'm 18+ and agree** and **Decline** buttons.
   Decline stops onboarding; `/start` offers the choice again. Accept records consent
   and asks for a birth date. Use synthetic `1990-04-13`, then `approximate 03:42`
   (or `unknown`). Enter `Cluj-Napoca, RO`, select the candidate, and review the
   profile summary and UTC conversion. Try editing a field before confirming.
   Confirmation saves the encrypted profile and calculates the chart. `/profile` reports
   cached chart status; `/edit_profile` starts corrections and `/retry_profile` retries
   a failed or outdated calculation. Set `ASTROLOGY_MCP_URL=http://localhost:8000/mcp`
   for the default loopback port.
   Active interpretation also needs SecondContext configured as described in
   [conversation worker setup](conversation-worker.md).
   For a separate synthetic user, try `2020-11-01`, `01:30`, `New York City, US`:
   selecting the city should ask for the first/second occurrence or unknown time.
   `/privacy` lets you decline even after acceptance.
   Use synthetic data for this smoke test; deletion is not implemented yet.
5. Restart the process and send `/start`: consent and collected fields should survive. Changing
   `ORIA_POLICY_VERSION` and restarting should require fresh consent; an old policy's
   button should show the current disclosure without accepting it.
6. Stop with Ctrl-C or SIGTERM. The process closes the database pool and Telegram session.

Polling requires the bot token, encryption key, outbound Telegram access and migrated PostgreSQL.
Redis and a running worker are required for replies; no model service is called.
See [queue recovery](worker-queue.md). Use the same configuration in both processes.
`make api` remains a separate HTTP process. No new dependencies are introduced.
Polling rejects production configuration and bots with an active webhook. Use a
dedicated development bot; this entrypoint never deletes webhooks or drops pending
updates. An invalid token/connectivity failure produces a payload-free diagnostic;
transient polling failures use aiogram's retry behavior.

## Adapter boundary

`domain.channel.ChannelMessage` contains provider user/chat/message/update IDs as
strings, UTC ingress time, text and optional callback data. Text, callback data and
user/chat IDs are excluded from repr. Callback events have empty text.
This is an internal Python contract, not a published wire API. Telegram metadata
and aiogram classes stay in `telegram/`; outbound plain text uses `ChannelClient`.
Explicit `parse_mode=None` prevents implicit markup interpretation.

Only ordinary private text messages and private button callbacks from humans are
handled. A callback must refer to an accessible message from this bot in the
clicker's own private chat. Identity comes from the clicking user, never the
bot-authored message or callback payload. Inline callbacks, group/channel messages,
edited messages, media, business messages and bot senders are ignored. Buttons use
the [aiogram inline keyboard API](https://docs.aiogram.dev/en/latest/api/types/inline_keyboard_button.html);
handled callbacks are [acknowledged](https://docs.aiogram.dev/en/latest/api/types/callback_query.html),
including after handler failure. Replies remain plain text.

`/start` and arbitrary text show consent when needed. After decline, text keeps
onboarding stopped; `/start` or `/privacy` reoffers the disclosure without changing
the decision. After acceptance, `/help` describes commands and `/start` resumes the
current birth-field prompt. Validated birth values enter encrypted drafts; pre-consent free text is discarded. After consent, input is temporarily encrypted
until processing finishes or expires; no model is called. Confirmation summaries show
only the allowed fields back to their owner. See [onboarding](onboarding.md).

Each handled update has a fresh correlation ID and provider update ID. Normal logs
contain only allowlisted operational events. Handler failures emit `update_failed`
without exception contents or message text. Polling waits for durable PostgreSQL acceptance,
then enqueues the internal UUID. Redis failure does not lose the event: worker scans
recover it. Database failure keeps the update in flight, retrying until acceptance or
shutdown; this avoids aiogram advancing the polling offset after a failed insert.
Callbacks are acknowledged after persistence/enqueue, before slow computation.

The worker commits domain changes and an encrypted pending reply together, then sends.
Retries do not repeat consent/profile mutations. Replies can duplicate if a process dies
after Telegram accepts a send but before PostgreSQL records it. See [worker queue](worker-queue.md)
for ordering, bounded retries, dead-letter visibility and encrypted payload retention.
Production webhook hosting remains a later stage.

## Verification

`make verify` includes mocked update replay, normalization, ignored update/chat
types, outbound API calls, privacy-safe logs, configuration guards, webhook refusal,
and session cleanup on success, failure, and cancellation. PostgreSQL integration
tests cover consent transitions, re-consent, cross-user isolation and failed delivery.
No live bot is contacted by automated tests. The Stage 4 text-only smoke test was
operator-confirmed; the consent-button smoke test above remains a manual check.
