# Local Telegram polling

## Development bot setup

1. In Telegram, open the official [@BotFather](https://t.me/BotFather), send
   `/newbot`, and follow the prompts for a name and username. This is a manual
   account step; see the [Telegram tutorial](https://core.telegram.org/bots/tutorial).
2. Run `make env` and put the token in `TELEGRAM_BOT_TOKEN` in your local `.env`.
   Never commit the token or paste it into logs, issues, or test fixtures.
3. Configure `DATABASE_URL`, run `make infra-up` and `make migrate`, then
   `make run` with `APP_ENV=development`. Only one polling process can use
   a bot token at a time ([aiogram polling documentation](https://docs.aiogram.dev/en/latest/dispatcher/long_polling.html)).
4. Open your development bot's private chat and send `/start`, then `/help`.
   Expect the versioned disclosure with **I'm 18+ and agree** and **Decline** buttons.
   Decline stops onboarding; `/start` offers the choice again. Accept records consent
   and explains that profile setup is not available yet. `/privacy` shows the disclosure
   and lets you decline even after acceptance. Do not send real birth details.
5. Restart the process and send `/start`: accepted consent should survive. Changing
   `ORIA_POLICY_VERSION` and restarting should require fresh consent; an old policy's
   button should show the current disclosure without accepting it.
6. Stop with Ctrl-C or SIGTERM. The process closes the database pool and Telegram session.

Polling requires the bot token, outbound Telegram access and migrated PostgreSQL.
Redis, workers and model services are not used by the consent flow.
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
the decision. After acceptance, `/help` describes available commands and other text
reports the paused profile step. No handler asks for birth data, echoes input,
persists message text or calls a model. See [consent flow](consent-flow.md).

Each handled update has a fresh correlation ID and provider update ID. Normal logs
contain only allowlisted operational events. Handler failures emit `update_failed`
without exception contents or message text. A failed send is not retried by this
baseline; a user can send the command again. Sequential polling bounds work and
avoids detached handler tasks during shutdown.

Identity resolution and consent decisions use one database transaction per update,
committed before delivery. An unavailable database fails closed with `update_failed`;
check database connectivity and migrations if the bot stops replying.
Durable inbound deduplication and delivery recovery remain Stage 11. Consecutive
identical decisions are idempotent, but an old same-policy button can still change
a later decision and duplicate updates can repeat replies. Production webhook
hosting remains a later stage.

## Verification

`make verify` includes mocked update replay, normalization, ignored update/chat
types, outbound API calls, privacy-safe logs, configuration guards, webhook refusal,
and session cleanup on success, failure, and cancellation. PostgreSQL integration
tests cover consent transitions, re-consent, cross-user isolation and failed delivery.
No live bot is contacted by automated tests. The Stage 4 text-only smoke test was
operator-confirmed; the consent-button smoke test above remains a manual check.
