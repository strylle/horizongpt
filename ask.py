# ask.py
# search the lore + answer
# python ask.py "question"   or   python ask.py   (empty line quits)

import json
import os
import re

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

import llm
import settings

# env settings
model_name = settings.answer_model
effort = settings.answer_effort
max_lore_chars = settings.max_lore_chars

system_prompt = settings.prompt("answer")

# discord voice
### I USED CLAUDE TO HELP TUNE THE OUTPUTS!!!!!!!
casual_prompt = settings.prompt("answer_discord")

# skip these in keyword search
stop_words = ["a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does", "for", "from",
              "had", "has", "have", "how", "in", "is", "it", "its", "of", "on", "or", "that", "the",
              "their", "there", "this", "to", "was", "were", "what", "when", "where", "which",
              "who", "whom", "why", "will", "with"]


# "Who signed the treaty?" -> ["signed", "treaty"]
def get_words(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    good_words = []
    for w in words:
        if w not in stop_words:
            good_words.append(w)
    return good_words


# the lore + search
class Lore:
    def __init__(self):
        index_file = settings.index_file
        embeddings_file = settings.embeddings_file
        if not os.path.exists(index_file) or not os.path.exists(embeddings_file):
            print("Index not found. Run: python index.py")
            exit()

        f = open(index_file, encoding="utf-8")
        self.pieces = json.load(f)
        f.close()

        self.embeddings = np.load(embeddings_file)
        if len(self.embeddings) != len(self.pieces):
            print("index.json and embeddings.npy don't match. Run: python index.py")
            exit()

        # keyword search
        word_lists = []
        for p in self.pieces:
            word_lists.append(get_words(p["doc"] + " " + p["heading"] + " " + p["text"]))
        self.keyword_search = BM25Okapi(word_lists)

        # section number -> pieces
        self.sections = {}
        self.total_chars = 0
        for p in self.pieces:
            if p["section"] not in self.sections:
                self.sections[p["section"]] = []
            self.sections[p["section"]].append(p)
            self.total_chars = self.total_chars + len(p["text"])

        # embedding model
        self.embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")

    # question -> numbers
    def embed(self, text):
        return self.embedder.encode("Represent this sentence for searching relevant passages: " + text,
                                    normalize_embeddings=True)

    # best sections for a question
    def find_sections(self, question):
        # send everything if it fits
        if self.total_chars <= max_lore_chars:
            all_sections = []
            for section_id in self.sections:
                all_sections.append(self.sections[section_id])
            return all_sections

        # score by words and meaning
        keyword_scores = self.keyword_search.get_scores(get_words(question))
        meaning_scores = np.dot(self.embeddings, self.embed(question))

        # merge both rankings
        points = {}
        for scores in [keyword_scores, meaning_scores]:
            top_40 = np.argsort(-scores)[:40]
            rank = 0
            for i in top_40:
                i = int(i)
                if scores[i] > 0:
                    if i not in points:
                        points[i] = 0
                    points[i] = points[i] + 1 / (60 + rank)
                rank = rank + 1

        # best first
        ranking = []
        for i in points:
            ranking.append([points[i], i])
        ranking.sort(reverse=True)

        # add whole sections until full
        picked = []
        used = 0
        for item in ranking:
            piece_number = item[1]
            section_id = self.pieces[piece_number]["section"]
            if section_id in picked:
                continue

            size = 0
            for p in self.sections[section_id]:
                size = size + len(p["text"])

            # skip if too big (unless first)
            if used > 0 and used + size > max_lore_chars:
                continue

            picked.append(section_id)
            used = used + size
            if used >= max_lore_chars * 0.95:
                break

        result = []
        for section_id in picked:
            result.append(self.sections[section_id])
        return result


# "Doc / Heading > Subheading"
def section_name(section):
    first = section[0]
    name = first["doc"].split("/")[-1]
    if first["heading"] != "":
        name = name + " / " + first["heading"]
    return name


# numbered sections + question
def make_prompt(question, found_sections):
    text = "Source sections:\n\n"
    room_left = max_lore_chars
    number = 1
    for section in found_sections:
        section_text = ""
        for p in section:
            section_text = section_text + p["text"] + "\n"
        section_text = section_text.strip()

        # cut if way too long
        limit = max(room_left, 2000)
        if len(section_text) > limit:
            section_text = section_text[:limit] + " [...]"
        room_left = room_left - len(section_text)

        text = text + "[" + str(number) + "] (" + section_name(section) + ")\n" + section_text + "\n\n"
        number = number + 1

    text = text + "Question: " + question
    return text


# what the answer comes back as
answer_schema = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "integer"}},
        "covered": {"type": "boolean"},
    },
    "required": ["answer", "sources", "covered"],
    "additionalProperties": False,
}


# asks the ai
class LoreBot:
    def __init__(self):
        self.lore = Lore()

    # casual=True for discord
    # returns (answer, sections it was given, numbers of the ones it used, whether the lore covers it)
    def answer(self, question, casual=False):
        found_sections = self.lore.find_sections(question)
        if len(found_sections) == 0:
            return "The lore docs don't mention anything matching that question.", [], [], False

        instructions = system_prompt
        if casual:
            instructions = system_prompt + "\n\n" + casual_prompt

        data = llm.write_json(instructions, make_prompt(question, found_sections), answer_schema,
                              model_name, effort, 16000)
        if data is None:
            return "No answer this time (refused or cut off).", found_sections, [], False
        sources = []
        for n in data["sources"]:
            if n >= 1 and n <= len(found_sections) and n not in sources:
                sources.append(n)
        sources.sort()
        return data["answer"].strip(), found_sections, sources, data["covered"]


# terminal mode
if __name__ == "__main__":
    import sys

    bot = LoreBot()

    if len(sys.argv) > 1:
        questions = [" ".join(sys.argv[1:])]
    else:
        questions = None
        print("Lore bot (" + str(len(bot.lore.sections)) + " sections, " + model_name + "). Empty line to quit.")

    while True:
        if questions is not None:
            if len(questions) == 0:
                break
            question = questions.pop(0)
        else:
            print()
            question = input("> ").strip()
            if question == "":
                break

        try:
            answer_text, found_sections, numbers, covered = bot.answer(question)
        except llm.LLMError as e:
            print("API error:", e)
            continue

        print()
        print(answer_text)

        if covered and len(numbers) > 0:
            print()
            print("Sources:")
            for n in numbers:
                print("  [" + str(n) + "]", section_name(found_sections[n - 1]))
