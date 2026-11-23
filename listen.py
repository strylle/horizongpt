# listen.py
# deciding what to answer: free checks, filter, haiku check, repeats, daily cap

import json
import os
import re
import time
from datetime import date

import numpy as np

import llm
import settings

recent_file = settings.recent_file
usage_file = settings.usage_file

checker_model = settings.check_model
recent_days = settings.recent_days
shortlist_score = settings.shortlist_score
daily_cap = settings.daily_cap
filter_file = settings.filter_file
filter_cutoff = settings.filter_cutoff
shrug_below = settings.shrug_below

# question openers
question_starts = ["who", "what", "when", "where", "why", "how", "which", "whose", "whom", "is", "are",
                   "was", "were", "did", "does", "do", "can", "could", "would", "will", "has", "have",
                   "had", "should", "any", "anyone", "tell me", "explain", "describe", "give me", "talk about",
                   "what's", "whats", "who's", "whos", "how's", "hows"]

lore_question_prompt = settings.prompt("is_lore_question")

# only for replies to the bot
followup_prompt = settings.prompt("is_lore_followup")

same_question_prompt = settings.prompt("same_question")


# strip mentions, channels, custom emojis
def clean_text(text):
    return re.sub(r"<(a?:\w+:|[@#][!&]?)\d+>", "", text).strip()


# filter input: embedding + closest lore score
def filter_features(lore, text_numbers):
    closest = float(np.max(np.dot(lore.embeddings, text_numbers)))
    return np.append(text_numbers, closest)


# local filter
class LoreFilter:
    def __init__(self, lore):
        self.lore = lore
        self.weights = None
        path = filter_file
        if not os.path.exists(path):
            path = settings.starter_filter_file
            if settings.use_filter:
                print("Using the starter filter. It was trained on another mod's server, so results may vary.")
        if os.path.exists(path):
            saved = np.load(path)
            self.weights = saved["weights"]
            self.bias = float(saved["bias"])

    # true if maybe lore
    def might_be_lore(self, text_numbers):
        if self.weights is None or not settings.use_filter:
            return True  # no filter yet, or turned off
        features = filter_features(self.lore, text_numbers)
        chance = 1 / (1 + np.exp(-(np.dot(self.weights, features) + self.bias)))
        return chance >= filter_cutoff


# closest lore score (0 to 1)
def lore_match(lore, question_numbers):
    return float(np.max(np.dot(lore.embeddings, question_numbers)))


# free question check
def looks_like_question(text):
    text = clean_text(text)
    if len(text) < 8 or len(text) > 1000:
        return False
    # ignore if just links or emojis
    if re.fullmatch(r"(<[^>]+>|https?://\S+|\s)+", text):
        return False
    if "?" in text:
        return True
    lower = text.lower()
    for word in question_starts:
        if lower == word or lower.startswith(word + " "):
            return True
    return False


# json or default
def load_json(path, default):
    try:
        f = open(path, encoding="utf-8")
        data = json.load(f)
        f.close()
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    f = open(path, "w", encoding="utf-8")
    json.dump(data, f)
    f.close()


# small cheap checks
class QuestionChecker:
    # prompt -> json
    def ask_for_json(self, instructions, message, schema):
        return llm.write_json(instructions, message, schema, checker_model)

    # rewritten question, or None if not lore
    # conversation = earlier lines for replies, oldest first
    def get_lore_question(self, message_text, conversation=None):
        schema = {
            "type": "object",
            "properties": {
                "lore_question": {"type": "boolean"},
                "question": {"type": "string"},
            },
            "required": ["lore_question", "question"],
            "additionalProperties": False,
        }
        instructions = lore_question_prompt
        message = "Message:\n" + message_text
        if conversation:
            instructions = lore_question_prompt + "\n\n" + followup_prompt
            message = ("Conversation before it (this message is a reply to Ella's last line):\n" +
                       "\n".join(conversation) + "\n\n" + message)
        data = self.ask_for_json(instructions, message, schema)
        if data is None:
            return None
        if data["lore_question"] == False:
            return None
        if data["question"].strip() == "":
            return None
        return data["question"].strip()

    # index of the same earlier question, or None
    def find_same_question(self, question, earlier_questions):
        listing = ""
        number = 1
        for q in earlier_questions:
            listing = listing + str(number) + ". " + q + "\n"
            number = number + 1

        schema = {
            "type": "object",
            "properties": {"match": {"type": "integer"}},
            "required": ["match"],
            "additionalProperties": False,
        }
        data = self.ask_for_json(same_question_prompt,
                                 "New question: " + question + "\n\nEarlier questions:\n" + listing, schema)
        if data is None:
            return None
        match = data["match"]
        if match >= 1 and match <= len(earlier_questions):
            return match - 1
        return None


# recent answers
class RecentAnswers:
    def __init__(self, checker):
        self.checker = checker
        self.items = load_json(recent_file, [])
        self.forget_old()

    def forget_old(self):
        cutoff = time.time() - recent_days * 24 * 60 * 60
        kept = []
        for item in self.items:
            if item["time"] >= cutoff:
                kept.append(item)
        self.items = kept

    # shortlist by embedding, haiku confirms. earlier answer or None
    def find(self, question, question_numbers):
        self.forget_old()
        if len(self.items) == 0:
            return None

        similar = []
        for item in self.items:
            score = float(np.dot(item["vector"], question_numbers))
            if score >= shortlist_score:
                similar.append([score, item])
        if len(similar) == 0:
            return None

        # top 5
        similar.sort(key=lambda pair: pair[0], reverse=True)
        similar = similar[:5]

        earlier_questions = []
        for pair in similar:
            earlier_questions.append(pair[1]["question"])

        position = self.checker.find_same_question(question, earlier_questions)
        if position is None:
            return None
        return similar[position][1]

    def add(self, question, question_numbers, url):
        self.forget_old()
        vector = []
        for x in question_numbers:
            vector.append(round(float(x), 5))
        self.items.append({"question": question, "vector": vector, "url": url, "time": time.time()})
        save_json(recent_file, self.items)


# answers today
class DailyCounter:
    def __init__(self):
        self.counts = load_json(usage_file, {})

    def answers_left(self):
        today = date.today().isoformat()
        used = self.counts.get(today, 0)
        return daily_cap - used

    def count_one(self):
        today = date.today().isoformat()
        used = self.counts.get(today, 0)
        self.counts = {today: used + 1}  # only today
        save_json(usage_file, self.counts)
