import re
from typing import Any

from app.knowledge.testing_expert.catalog import all_cards, all_playbooks

_TOKEN = re.compile(r"[a-zA-Z0-9_+#./-]+|[\u4e00-\u9fff]{2,}")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text or ""):
        item = raw.lower()
        tokens.append(item)
        if len(item) >= 2 and all("\u4e00" <= ch <= "\u9fff" for ch in item):
            for size in (2, 3, 4):
                for index in range(len(item) - size + 1):
                    tokens.append(item[index:index + size])
    return tokens


def _haystack(card: dict[str, Any]) -> str:
    parts = [card["id"], card["title"], card["domain"], card["when"], card["principle"], *card["aliases"], *card["apply"]]
    return " ".join(parts).lower()


def score_card(query: str, card: dict[str, Any]) -> float:
    tokens = tokenize(query)
    if not tokens:
        return 0.0
    blob = _haystack(card)
    score = 0.0
    title = card["title"].lower()
    aliases = [item.lower() for item in card["aliases"]]
    for token in tokens:
        if token == card["id"] or token == title:
            score += 6
        elif any(token == alias or token in alias or alias in token for alias in aliases):
            score += 4
        elif token in blob:
            score += 1
    if any(alias in (query or "").lower() for alias in aliases if len(alias) >= 2):
        score += 3
    return score


def score_playbook(query: str, book: dict[str, Any]) -> float:
    text = (query or "").lower()
    score = 0.0
    for trigger in book["triggers"]:
        if trigger.lower() in text:
            score += 8 if len(trigger) >= 2 else 3
    for token in tokenize(query):
        if token in book["title"].lower() or token in " ".join(book["techniques"]).lower():
            score += 1
    return score


def retrieve_cards(query: str, top_k: int = 6, domains: list[str] | None = None) -> list[dict[str, Any]]:
    ranked = []
    for card in all_cards():
        if domains and card["domain"] not in domains:
            continue
        score = score_card(query, card)
        if score > 0:
            ranked.append({**card, "score": round(score, 2)})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]


def retrieve_playbooks(query: str, top_k: int = 2) -> list[dict[str, Any]]:
    ranked = []
    for book in all_playbooks():
        score = score_playbook(query, book)
        if score > 0:
            ranked.append({**book, "score": round(score, 2)})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:top_k]
