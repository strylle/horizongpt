# eval.py
# python eval.py            search test, free
# python eval.py --answers  asks claude every question

import json
import os
import sys

import ask
import settings

import os
if not os.path.exists(settings.questions_file):
    print("No test questions yet. Copy questions.example.json to", settings.questions_file, "and write your own.")
    exit()
f = open(settings.questions_file, encoding="utf-8")
test_questions = json.load(f)
f.close()


def test_search():
    lore = ask.Lore()
    print("Lore size:", lore.total_chars, "characters, limit", ask.max_lore_chars)
    if lore.total_chars <= ask.max_lore_chars:
        print("(everything fits, so search is skipped)")

    hits = 0
    total = 0
    for item in test_questions:
        if item["expect"] is None:  # should refuse
            continue
        total = total + 1

        found_sections = lore.find_sections(item["q"])

        # where did the right section land
        position = None
        number = 1
        for section in found_sections:
            if item["expect"].lower() in section[0]["heading"].lower():
                position = number
                break
            number = number + 1

        if position is not None:
            hits = hits + 1
            print("HIT  #" + str(position).ljust(3), str(len(found_sections)).rjust(3), "sections ", item["q"])
        else:
            print("MISS     ", str(len(found_sections)).rjust(3), "sections ", item["q"])

    print()
    print("Search:", hits, "/", total, "questions got the expected section")


def test_answers():
    bot = ask.LoreBot()
    for item in test_questions:
        answer_text, found_sections, sources, covered = bot.answer(item["q"])
        if item["expect"] is None:
            kind = "SHOULD REFUSE"
        else:
            kind = "ANSWERABLE"
        print()
        print("=== [" + kind + "]", item["q"])
        print(answer_text)


if "--answers" in sys.argv:
    test_answers()
else:
    test_search()
