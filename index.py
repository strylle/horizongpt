# index.py
# docs -> search index. rerun when docs change

import json
import os
import re

import numpy as np
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from sentence_transformers import SentenceTransformer

import settings

data_folder = settings.data_folder

max_piece_size = 1500  # chars

# skip docs with these in the name
hidden_doc_words = ["focus tree", "proposal"]
# skip sections with these in a heading
hidden_heading_words = ["tree", "trees", "mechanic", "mechanics", "path", "paths", "branch", "foci", "focus",
                        "playable content", "content", "order of battle"]
skipped_sections = 0

# skip paragraphs with these
retired_phrases = []  # e.g. "Old Country Name"
skipped_paragraphs = 0

# a short line with one of these starts game content, skipped until the next heading
hidden_block_words = ["focus tree"]
skipped_blocks = 0

all_pieces = []
section_number = 0


# docx -> [[level, text], ...], 0 = text, 1+ = heading
def read_docx(file_path):
    result = []
    doc = Document(file_path)

    # paragraphs and tables in order
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]

        if tag == "p":
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if text == "":
                continue

            style_name = ""
            if paragraph.style is not None and paragraph.style.name is not None:
                style_name = paragraph.style.name

            if style_name == "Title":
                result.append([1, text])
            elif style_name.startswith("Heading"):
                # "Heading 2" -> 3, title is 1
                number = re.search(r"\d+", style_name)
                if number:
                    result.append([int(number.group()) + 1, text])
                else:
                    result.append([2, text])
            else:
                result.append([0, text])

        elif tag == "tbl":
            table = Table(child, doc)
            rows = []
            for row in table.rows:
                cells = []
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    # skip merged cell repeats
                    if cell_text != "":
                        if len(cells) == 0 or cells[-1] != cell_text:
                            cells.append(cell_text)
                if len(cells) > 0:
                    rows.append(" | ".join(cells))
            if len(rows) > 0:
                result.append([0, "\n".join(rows)])

    return result


# md/txt, # lines are headings
def read_text_file(file_path):
    result = []
    f = open(file_path, encoding="utf-8", errors="replace")
    lines = f.read().splitlines()
    f.close()

    paragraph = []
    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading:
            if len(paragraph) > 0:
                result.append([0, "\n".join(paragraph)])
                paragraph = []
            level = len(heading.group(1))
            result.append([level, heading.group(2).strip()])
        elif line.strip() != "":
            paragraph.append(line.strip())
        else:
            # end of paragraph
            if len(paragraph) > 0:
                result.append([0, "\n".join(paragraph)])
                paragraph = []

    if len(paragraph) > 0:
        result.append([0, "\n".join(paragraph)])
    return result


# section -> pieces under max_piece_size
def split_into_pieces(paragraphs):
    pieces = []
    current = []
    current_size = 0

    for para in paragraphs:
        if len(current) > 0 and current_size + len(para) > max_piece_size:
            pieces.append("\n".join(current))
            current = []
            current_size = 0

        # chop long paragraphs at a sentence
        while len(para) > max_piece_size:
            cut = para.rfind(". ", 0, max_piece_size)
            if cut > max_piece_size // 2:
                cut = cut + 1
            else:
                cut = max_piece_size
            pieces.append(para[:cut].strip())
            para = para[cut:].strip()

        current.append(para)
        current_size = current_size + len(para)

    if len(current) > 0:
        pieces.append("\n".join(current))
    return pieces


# game content heading?
def is_hidden(heading):
    words = re.findall(r"[a-z]+", heading.lower())
    joined = " ".join(words)
    for hidden in hidden_heading_words:
        if " " in hidden:
            if hidden in joined:
                return True
        elif hidden in words:
            return True
    return False


# retconned?
def is_retired(text):
    for phrase in retired_phrases:
        if phrase.lower() in text.lower():
            return True
    return False


# short line like "Starting Focus Tree Nodes"?
def starts_hidden_block(text):
    first = text.split("\n")[0].lower()
    if len(first) > 80:
        return False
    for word in hidden_block_words:
        if word in first:
            return True
    return False


# save one section
def save_section(doc_name, headings, paragraphs):
    global section_number
    global skipped_sections

    heading_names = []
    for h in headings:
        heading_names.append(h[1])
    heading = " > ".join(heading_names)  # "Country > Leader"

    if is_hidden(heading):
        skipped_sections = skipped_sections + 1
        return 0

    pieces = split_into_pieces(paragraphs)
    for piece in pieces:
        all_pieces.append({
            "id": len(all_pieces),
            "section": section_number,
            "doc": doc_name,
            "heading": heading,
            "text": piece,
        })

    section_number = section_number + 1
    return len(pieces)


# one file -> sections
def add_file(file_path, doc_name):
    if file_path.lower().endswith(".docx"):
        blocks = read_docx(file_path)
    else:
        blocks = read_text_file(file_path)

    headings = []  # current heading stack
    paragraphs = []
    count = 0
    hiding = False

    for block in blocks:
        level = block[0]
        text = block[1]

        if level > 0:
            # new heading, save the last section
            if len(paragraphs) > 0:
                count = count + save_section(doc_name, headings, paragraphs)
                paragraphs = []

            # pop to parent, push this one
            new_headings = []
            for h in headings:
                if h[0] < level:
                    new_headings.append(h)
            new_headings.append([level, text])
            headings = new_headings
            hiding = False
        else:
            if hiding:
                continue
            if starts_hidden_block(text):
                global skipped_blocks
                skipped_blocks = skipped_blocks + 1
                hiding = True
                continue
            if is_retired(text):
                global skipped_paragraphs
                skipped_paragraphs = skipped_paragraphs + 1
                continue
            paragraphs.append(text)

    if len(paragraphs) > 0:
        count = count + save_section(doc_name, headings, paragraphs)

    print(count, "chunks", doc_name)


# ---------------- main ----------------

# find docs
files = []
for current_folder, subfolders, filenames in os.walk(data_folder):
    for name in filenames:
        if name.startswith("~$"):  # word temp files
            continue
        lower = name.lower()
        if lower.endswith(".docx") or lower.endswith(".md") or lower.endswith(".txt"):
            files.append(os.path.join(current_folder, name))
files.sort()

if len(files) == 0:
    print("No .docx, .md or .txt files found in", data_folder)
    exit()

for file_path in files:
    # "Folder/Doc"
    doc_name = os.path.relpath(file_path, data_folder)
    doc_name = os.path.splitext(doc_name)[0]
    doc_name = doc_name.replace("\\", "/")

    skip = False
    for word in hidden_doc_words:
        if word in os.path.basename(doc_name).lower():
            skip = True
    if skip:
        print("skipped (game content)", doc_name)
        continue

    add_file(file_path, doc_name)

f = open(settings.index_file, "w", encoding="utf-8")
json.dump(all_pieces, f, ensure_ascii=False, indent=1)
f.close()
print()
print(len(all_pieces), "chunks in", section_number, "sections from", len(files), "files written to index.json")
print(skipped_sections, "sections skipped because they are game content")
print(skipped_paragraphs, "paragraphs skipped because they are retconned")
print(skipped_blocks, "game content blocks skipped inside sections")

# embeddings, so search matches meaning not just words
print("Embedding with BAAI/bge-small-en-v1.5...")
embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")

texts_to_embed = []
for piece in all_pieces:
    doc_short_name = piece["doc"].split("/")[-1]
    texts_to_embed.append(doc_short_name + " / " + piece["heading"] + "\n" + piece["text"])

embeddings = embedder.encode(texts_to_embed, normalize_embeddings=True, batch_size=32, show_progress_bar=True)
np.save(settings.embeddings_file, embeddings.astype(np.float32))
print("Embeddings written to embeddings.npy")
