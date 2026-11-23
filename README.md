![HorizonGPT logo](horizongpt.png)

HorizonGPT is a RAG Discord chatbot that answers questions about a mod's lore from your own docs! Pretty cool, huh?

Originally built for the Hearts of Iron IV mod Over the Horizon, you can probably use it for really any project Discord that has extensive lore. I made this as like a project for school & because I wanted to learn more about ML stuff. 

The way it works:
1. When a user sends something in a channel the bot listens to, the bot will look for keywords (or if it's pinged) to determine if you're asking it a lore related question. (there is also an experimental filter model but it's only trained on over the horizon soooo ymmv, you can turn it on if you want.)
2. If the bot decides your query is lore related, it will then use keyword search plus a [local embedding model](https://huggingface.co/BAAI/bge-small-en-v1.5) to find the sections of your docs that match the question.
3. Then, a LLM (currently, only supports Google, OpenAI or Anthropic models with the whole thing mainly tested using Claude Haiku 5.5) will read only those sections (not your whole docs, so it doesn't fill its context) and formulate a response.

## Features
- Will react with 🤷 if it can't find an answer
- Does not reply to all queries, irrelevant prompts will be discarded to avoid burning your API credits
- Is tuned to only answer lore questions, and won't talk about content ingame
- Continues the conversation if you reply to its message
- Links to a previous response

## Setup

Requires Python 3.11 or newer.

```
python -m pip install -r requirements.txt
```

```
python discord_bot.py
```

Three files will be made for you:

- `.env`: your secrets, where you'll paste in your API key and bot token.
- `private/config.json`: you'll have to add the channels you want the bot to listen to
- `private/SOUL.md`: how the bot talks & system prompt

Then:

1. Put your lore docs in `private/data/` as `.docx`, `.md` or `.txt`. Subfolders are fine and show up in the doc names. From Google Drive, download the folder (or use File > Download > Microsoft Word on each doc); headings in the docs become sections.

2. Build the index, and again whenever the docs change:

   ```
   python index.py
   ```

3. Try it! 

   ```
   python ask.py "Who was the first person on the Moon?"
   ```

### Discord

1. Make a bot at https://discord.com/developers/applications. Under **Bot**, copy the token and turn on **Message Content Intent** (it can't read messages without this!).
2. Under **OAuth2 > URL Generator**, tick `bot`, then **View Channels**, **Read Message History**, **Send Messages** and **Add Reactions**. Open the link to add it to your server.
3. Put your bot token in `.env` as `DISCORD_BOT_TOKEN`. In your config, set `server_id` and `listen_channels` (turn on Developer Mode in Discord to copy IDs with a right-click).
4. Run it!

   ```
   python discord_bot.py
   ```

### Config

`private/config.json` holds the settings:

| Section | What's in it |
|---|---|
| `discord` | `server_id`, `listen_channels` (where it answers), `cooldown_seconds` between answers for one person, `daily_cap` answers per day |
| `models` | `provider` (`anthropic`, `openai` or `gemini`), `answer_effort` (`low`, `medium` or `high`), and for each provider the `answer` model (writes answers) and `checks` model (the AI check and repeat check) |
| `tuning` | `local_filter` (turn the starter filter on or off), `lore_chars_per_question`, `filter_cutoff` (lower lets more reach the AI check), `shrug_below` (shrug when no lore is this close), `remember_answers_days`, `repeat_threshold` |

### SOUL.md

`private/SOUL.md` is who the bot is and how it talks. Each `##` heading is one prompt and is sent to the AI word for word; `#` headings and the text under them are just notes for you. The shipped one works for most alternate-history mods. `SOUL.over-the-horizon.md` shows one tuned to our own mod.

| Heading | Used for |
|---|---|
| `## Answer` | writing answers |
| `## Discord voice` | added to the answer prompt in Discord: short, casual, no spoilers |
| `## Is it a lore question` | the AI check |
| `## Follow-ups` | added to that for replies to the bot |
| `## Same question` | spotting repeat questions |

You do need to keep these headings.

## Local filter

I got curious on how to better filter out irrelevant prompts, and trained a small filter model that was trained on the Over the Horizon discord server. For the most part, this toggle is experimental and may or may not work well for your uses!

Set `local_filter` to `true` to use it if you want. It is disabled by default.