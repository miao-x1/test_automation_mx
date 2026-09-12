from typing import Any


def card(
    id: str,
    title: str,
    domain: str,
    aliases: list[str],
    when: str,
    principle: str,
    apply: list[str],
    pitfalls: list[str],
    sources: list[str],
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "domain": domain,
        "aliases": aliases,
        "when": when,
        "principle": principle,
        "apply": apply,
        "pitfalls": pitfalls,
        "sources": sources,
    }


def playbook(
    id: str,
    title: str,
    triggers: list[str],
    techniques: list[str],
    must: list[str],
    should: list[str],
    skip_unless: list[str],
    thinking: list[str],
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "triggers": triggers,
        "techniques": techniques,
        "must": must,
        "should": should,
        "skip_unless": skip_unless,
        "thinking": thinking,
    }
