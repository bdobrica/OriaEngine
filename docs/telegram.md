# Local Telegram polling

## Development bot setup

1. In Telegram, open the official [@BotFather](https://t.me/BotFather), send
   `/newbot`, and follow the prompts for a name and username. This is a manual
   account step; see the [Telegram tutorial](https://core.telegram.org/bots/tutorial).
2. Run `make env` and put the token in `TELEGRAM_BOT_TOKEN` in your local `.env`.
   Never commit the token or paste it into logs, issues, or test fixtures.
3. Run `make run` with `APP_ENV=development`. Only one polling process can use
   a bot token at a time ([aiogram polling documentation](https://docs.aiogram.dev/en/latest/dispatcher/long_polling.html)).
4. Open your development bot's private chat and send `/start`, then `/help`.
   Expect a welcome and an explanation that profile setup is not available yet.
   Do not send real birth details for this smoke test.
5. Stop with Ctrl-C or SIGTERM. The polling process closes the Telegram HTTP session.

This baseline requires only the bot token and outbound Telegram access; PostgreSQL,
Redis, workers, and model services are not needed for its stateless replies.
`make api` remains a separate HTTP process. No new dependencies are introduced.
Polling rejects production configuration and bots with an active webhook. Use a
dedicated development bot; this entrypoint never deletes webhooks or drops pending
updates. An invalid token/connectivity failure produces a payload-free diagnostic;
transient polling failures use aiogram's retry behavior.

## Adapter boundary

`domain.channel.ChannelMessage` contains provider user/chat/message/update IDs as
strings, UTC ingress time, and text. Text and user/chat IDs are excluded from repr.
This is an internal Python contract, not a published wire API. Telegram metadata
and aiogram classes stay in `telegram/`; outbound plain text uses `ChannelClient`.
Explicit `parse_mode=None` prevents implicit markup interpretation.

Only ordinary private text messages from human senders are handled. Group/channel
messages, edited messages, media, callbacks, business messages, and bot senders
are ignored, including when directly replayed into the dispatcher. `/start` gives
the welcome; `/help` and other text give the placeholder help. Neither asks for
birth data, echoes input, persists messages, nor calls a model.

Each handled update has a fresh correlation ID and provider update ID. Normal logs
contain only allowlisted operational events. Handler failures emit `update_failed`
without exception contents or message text. A failed send is not retried by this
baseline; a user can send the command again. Sequential polling bounds work and
avoids detached handler tasks during shutdown.

Identity resolution and consent UI will connect to the existing repositories in
Stage 5, before any user-owned domain operation. Durable inbound deduplication and
delivery recovery remain Stage 11; duplicate updates can repeat these stateless
placeholder replies. Production webhook hosting remains a later stage.

## Verification

`make verify` includes mocked update replay, normalization, ignored update/chat
types, outbound API calls, privacy-safe logs, configuration guards, webhook refusal,
and session cleanup on success, failure, and cancellation. No live bot is contacted
by automated tests. BotFather creation and the private `/start` smoke test must be
performed manually; keep their TODO items open until verified.
