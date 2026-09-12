from functools import lru_cache
from typing import Any

from app.knowledge.testing_expert.corpus_automation import CARDS as AUTOMATION
from app.knowledge.testing_expert.corpus_extra import CARDS as EXTRA
from app.knowledge.testing_expert.corpus_foundation import CARDS as FOUNDATION
from app.knowledge.testing_expert.corpus_techniques import CARDS as TECHNIQUES
from app.knowledge.testing_expert.playbooks import PLAYBOOKS

SOURCES = [
    "ISTQB CTFL 4.x / Glossary / Advanced Test Analyst / Technical Test Analyst / Test Manager",
    "ISTQB Test Automation Engineer / Agile Tester / Performance / Security / Usability / Mobile / Acceptance / Model-Based / AI Testing",
    "https://istqb.org/  https://tbok.istqb.org/",
    "Playwright / Selenium / Cypress / Appium 官方文档",
    "OWASP Top 10",
    "Postman / Newman, REST API testing, Testing Pyramid, Google Testing Blog, Microsoft Playwright best practices",
]


@lru_cache(maxsize=1)
def all_cards() -> list[dict[str, Any]]:
    items = [*FOUNDATION, *TECHNIQUES, *AUTOMATION, *EXTRA]
    seen: set[str] = set()
    unique = []
    for item in items:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        unique.append(item)
    return unique


@lru_cache(maxsize=1)
def all_playbooks() -> list[dict[str, Any]]:
    return list(PLAYBOOKS)


def domains() -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in all_cards():
        counts[item["domain"]] = counts.get(item["domain"], 0) + 1
    return counts
