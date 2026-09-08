# tg-rich-bot

Personal Telegram bot that turns Markdown into Bot API 10.1 **RichMessages**.

## Quick start

```bash
cd ~/tg-rich-bot
cp .env.example .env        # fill BOT_TOKEN, OWNER_ID, CHANNEL_ID
uv sync                     # or: pip install -e .[dev]
uv run python -m bot
```

## Usage

In a DM with the bot:

1. Send a Markdown message.
2. Reference images with public HTTP(S) URLs:
   `![alt](https://example.com/x.png)`.
   To turn an image into a custom-emoji mosaic, specify the grid:
   `![[emoji:5x3]](https://example.com/logo.png)`.
   Optional lines prefixed with `|` are placed beside the corresponding
   mosaic rows:
   ```markdown
   ![[emoji:5x3]](https://example.com/person.png)
   | *Илья Полосухин*
   | NEAR
   | CoFounder
   ```
3. The bot replies with a rich preview and `[✅ Publish] [✏️ Redo] [🗑 Drop]`.
4. Publish sends the same `InputRichMessage` payload into `CHANNEL_ID`.

## Layout

See `bot/` — `handlers/` (compose, preview, publish) and `api.py`
(thin Bot API wrapper).

## Constraints

- One owner only (`OWNER_ID`) — others are silently ignored.
- Telegram RichMessage media blocks accept only public HTTP(S) URLs.
- Custom emoji require Telegram Premium on the bot owner's account.
