# discord_bot.py
# the bot, answers in LORE_LISTEN_CHANNELS
# python discord_bot.py

import asyncio
import os
import time

import discord

import ask
import listen
import llm
import settings

token = os.environ.get("DISCORD_BOT_TOKEN")
cooldown_seconds = settings.cooldown_seconds  # per person
listen_channels = settings.listen_channels

shrug = "\N{SHRUG}"
hourglass = "\N{HOURGLASS WITH FLOWING SAND}"
discord_limit = 2000  # discord max
no_pings = discord.AllowedMentions.none()  # never ping


# split for discord
def split_message(text):
    parts = []
    while len(text) > discord_limit:
        cut = text.rfind("\n", 0, discord_limit)  # new line
        if cut < discord_limit // 2:
            cut = text.rfind(" ", 0, discord_limit)  # or space
        if cut <= 0:
            cut = discord_limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    if text != "":
        parts.append(text)
    return parts


class LoreDiscordBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        if len(listen_channels) > 0:
            intents.message_content = True
        super().__init__(intents=intents)

        self.lore_bot = ask.LoreBot()
        self.checker = listen.QuestionChecker()
        self.filter = listen.LoreFilter(self.lore_bot.lore)
        self.recent = listen.RecentAnswers(self.checker)
        self.counter = listen.DailyCounter()
        self.last_checked = {}  # user -> last check
        self.last_answered = {}  # user -> last answer

    # on start
    async def setup_hook(self):
        # warm up embeddings
        await asyncio.to_thread(self.lore_bot.lore.embed, "warm up")

    async def on_ready(self):
        print("Logged in as", self.user,
              "(" + str(len(self.lore_bot.lore.sections)) + " lore sections, " + ask.model_name + ",",
              "listening in", len(listen_channels), "channel(s),",
              self.counter.answers_left(), "answers left today)")

    # answer in a thread so the bot doesnt freeze
    async def get_answer(self, question):
        self.counter.count_one()
        answer_text, found_sections, sources, covered = await asyncio.to_thread(self.lore_bot.answer, question, True)
        found_something = covered and len(sources) > 0
        if found_something:
            names = []
            for n in sources:
                names.append(ask.section_name(found_sections[n - 1]))
            print("Answered from:", " | ".join(names))
        return answer_text, found_something

    # replied message or None
    async def get_replied_to(self, message):
        reference = message.reference
        if reference is None or reference.message_id is None:
            return None
        if isinstance(reference.resolved, discord.Message):
            return reference.resolved
        try:
            return await message.channel.fetch_message(reference.message_id)
        except discord.HTTPException:
            return None

    # reply chain, oldest first
    async def get_conversation(self, ella_message):
        lines = []
        current = ella_message
        while current is not None and len(lines) < 6:
            name = "Ella"
            if current.author != self.user:
                name = current.author.display_name
            lines.insert(0, name + ": " + listen.clean_text(current.content)[:600])
            current = await self.get_replied_to(current)
        return lines

    # every message
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.channel.id not in listen_channels:
            return

        # strip mentions
        text = listen.clean_text(message.content)
        mentioned = self.user in message.mentions

        # reply to the bot = follow-up
        conversation = None
        replied_to = None
        if message.reference is not None:
            replied_to = await self.get_replied_to(message)
            if replied_to is not None and replied_to.author == self.user:
                conversation = await self.get_conversation(replied_to)
            elif not mentioned:
                return  # ignore if that's someone else

        # just a ping on a reply? ask about the message it replies to
        if mentioned and len(text) < 3 and replied_to is not None and conversation is None:
            text = listen.clean_text(replied_to.content)
        if len(text) < 3:
            return

        # pinged with just a topic, like "China's lore"
        if mentioned and conversation is None and not listen.looks_like_question(text):
            text = "tell me about " + text

        # free checks unless pinged or replied to
        if not mentioned and conversation is None:
            if not listen.looks_like_question(text):
                return
            text_numbers = await asyncio.to_thread(self.lore_bot.lore.embed, text[:900])
            if not self.filter.might_be_lore(text_numbers):
                return

        # 3 sec per person
        user = message.author.id
        now = time.monotonic()
        if user in self.last_checked and now - self.last_checked[user] < 3:
            return
        self.last_checked[user] = now

        if self.counter.answers_left() <= 0:
            print("Daily cap reached, ignoring question")
            return

        try:
            # 1. ignore if not lore
            question = await asyncio.to_thread(self.checker.get_lore_question, text[:900], conversation)
            if question is None:
                return

            # 2. cooldown
            now = time.monotonic()
            if user in self.last_answered and now - self.last_answered[user] < cooldown_seconds:
                await message.add_reaction(hourglass)
                return
            self.last_answered[user] = now

            # 3. ignore if nothing found
            question_numbers = await asyncio.to_thread(self.lore_bot.lore.embed, question)
            if listen.lore_match(self.lore_bot.lore, question_numbers) < listen.shrug_below:
                await message.add_reaction(shrug)
                return

            # 4. link if answered recently (not for follow-ups)
            earlier = None
            if conversation is None:
                earlier = await asyncio.to_thread(self.recent.find, question, question_numbers)
            if earlier is not None:
                await message.reply("This was answered recently: " + earlier["url"],
                                    mention_author=False, allowed_mentions=no_pings)
                return

            # 5. answer
            async with message.channel.typing():
                answer_text, found_something = await self.get_answer(question)

        except llm.LLMError as e:
            print("API error for", repr(text), ":", e)
            return

        if not found_something:
            await message.add_reaction(shrug)
            return

        parts = split_message(answer_text)
        reply = await message.reply(parts[0], mention_author=False, allowed_mentions=no_pings)
        for part in parts[1:]:
            await message.channel.send(part, allowed_mentions=no_pings)

        self.recent.add(question, question_numbers, reply.jump_url)


if __name__ == "__main__":
    if not token:
        print("Put your DISCORD_BOT_TOKEN in .env first.")
    elif llm.missing_key() is not None:
        print(llm.missing_key())
    elif len(listen_channels) == 0:
        print("Add the channel IDs it should answer in to listen_channels in config.json.")
    else:
        LoreDiscordBot().run(token)
