# settings.py
# file paths, .env, config.json and SOUL.md
# first run makes any that are missing, then stops so you can fill them in
# secrets in .env, private stuff in private/ (never in git)

import json
import os
import shutil

from dotenv import load_dotenv

folder = os.path.dirname(os.path.abspath(__file__))

env_template = """# secrets for the bot. never put this in git

# from console.anthropic.com
ANTHROPIC_API_KEY=
# from discord.com/developers, Bot > Reset Token
DISCORD_BOT_TOKEN=

# only if your Anthropic key isn't tied to a workspace
ANTHROPIC_WORKSPACE_ID=
# only if you switch provider in config.json
OPENAI_API_KEY=
GEMINI_API_KEY=
# only if private/ lives somewhere else
LORE_PRIVATE_DIR=
"""

made = []
env_file = os.path.join(folder, ".env")
if not os.path.exists(env_file):
    f = open(env_file, "w", encoding="utf-8")
    f.write(env_template)
    f.close()
    made.append(env_file)
load_dotenv(env_file)

private_folder = os.environ.get("LORE_PRIVATE_DIR") or os.path.join(folder, "private")
os.makedirs(os.path.join(private_folder, "data"), exist_ok=True)
for name, example in [["config.json", "config.example.json"], ["SOUL.md", "SOUL.example.md"]]:
    path = os.path.join(private_folder, name)
    if not os.path.exists(path):
        shutil.copy(os.path.join(folder, example), path)
        made.append(path)

if len(made) > 0:
    print("First run, made these for you:")
    for path in made:
        print("  " + path)
    print("Fill them in (see README), put your lore docs in " + os.path.join(private_folder, "data") + ", then run this again.")
    exit()


def private_path(*parts):
    return os.path.join(private_folder, *parts)


# lore docs (.docx .md .txt)
data_folder = private_path("data")

# from index.py
index_file = private_path("index.json")
embeddings_file = private_path("embeddings.npy")

# from the bot
recent_file = private_path("recent_answers.json")
usage_file = private_path("usage.json")

# local filter: private/filter.npz if there is one, else the starter
filter_file = private_path("filter.npz")
starter_filter_file = os.path.join(folder, "starter_filter.npz")  # ships with the repo
filter_weights_file = private_path("filter_weights.txt")

# eval.py questions
questions_file = private_path("questions.json")


# ---------------- config.json ----------------

config_file = private_path("config.json")
f = open(config_file, encoding="utf-8")
config = json.load(f)
f.close()

discord_config = config["discord"]
server_id = int(discord_config["server_id"] or 0)
listen_channels = []
for channel in discord_config["listen_channels"]:
    listen_channels.append(int(channel))
cooldown_seconds = discord_config["cooldown_seconds"]
daily_cap = discord_config["daily_cap"]

models = config["models"]
provider = models["provider"]  # anthropic, openai or gemini
answer_model = models[provider]["answer"]
answer_effort = models["answer_effort"]
check_model = models[provider]["checks"]

tuning = config["tuning"]
use_filter = tuning["local_filter"]
max_lore_chars = tuning["lore_chars_per_question"]
filter_cutoff = tuning["filter_cutoff"]  # lower = more reach haiku
shrug_below = tuning["shrug_below"]
recent_days = tuning["remember_answers_days"]
shortlist_score = tuning["repeat_threshold"]


# ---------------- SOUL.md ----------------

soul_file = private_path("SOUL.md")
# ## heading -> prompt name
soul_headings = {
    "Answer": "answer",
    "Discord voice": "answer_discord",
    "Is it a lore question": "is_lore_question",
    "Follow-ups": "is_lore_followup",
    "Same question": "same_question",
}

# each ## section is one prompt. # headings and text before them are just notes
# extra ## sections are kept under their title
prompts = {}
current = None
f = open(soul_file, encoding="utf-8")
for line in f.read().split("\n"):
    if line.startswith("## "):
        title = line[3:].strip()
        current = soul_headings.get(title, title)
        prompts[current] = []
    elif line.startswith("# "):
        current = None
    elif current is not None:
        prompts[current].append(line)
f.close()

# the bot needs these
for name in ["answer", "answer_discord", "is_lore_question", "is_lore_followup", "same_question"]:
    if name not in prompts:
        heading = [t for t in soul_headings if soul_headings[t] == name][0]
        print("SOUL.md is missing its ## " + heading + " section.")
        exit()


def prompt(name):
    return "\n".join(prompts[name]).strip("\n")
