from functools import lru_cache
from typing import Any

from app.knowledge.testing_expert.catalog import SOURCES, all_cards, all_playbooks, domains
from app.knowledge.testing_expert.retriever import retrieve_cards, retrieve_playbooks


class TestingExpertService:
    """本地测试专家知识：检索、答题、任务分析。不依赖 Milvus。"""

    def retrieve(self, query: str, top_k: int = 6, include_playbooks: bool = True) -> dict[str, Any]:
        cards = retrieve_cards(query, top_k=top_k)
        books = retrieve_playbooks(query, top_k=2) if include_playbooks else []
        return {
            "query": query,
            "cards": cards,
            "playbooks": books,
            "prompt": self.format_prompt(cards, books),
            "sources": SOURCES,
        }

    def retrieve_for_task(self, query: str, top_k: int = 5) -> dict[str, Any]:
        data = self.retrieve(query, top_k=top_k, include_playbooks=True)
        data["thinking"] = self._thinking_from(data["playbooks"], data["cards"])
        return data

    def answer(self, question: str) -> dict[str, Any]:
        data = self.retrieve(question, top_k=4, include_playbooks=False)
        cards = data["cards"]
        if not cards:
            return {
                "question": question,
                "answer": "知识库未命中直接条目。应按风险、范围和可验证预期重新描述问题。",
                "used_cards": [],
                "sources": SOURCES,
            }
        primary = cards[0]
        lines = [
            f"{primary['title']}：{primary['principle']}",
            f"适用：{primary['when']}",
            "怎么用：",
            *[f"- {item}" for item in primary["apply"][:4]],
            "避免：",
            *[f"- {item}" for item in primary["pitfalls"][:3]],
        ]
        if len(cards) > 1:
            lines.append("相关：")
            for extra in cards[1:3]:
                lines.append(f"- {extra['title']}：{extra['principle'][:80]}")
        lines.append(f"来源：{', '.join(primary['sources'])}")
        return {
            "question": question,
            "answer": "\n".join(lines),
            "used_cards": [{"id": item["id"], "title": item["title"], "score": item["score"]} for item in cards],
            "sources": primary["sources"],
        }

    def analyze_task(self, task: str) -> dict[str, Any]:
        data = self.retrieve_for_task(task, top_k=5)
        books = data["playbooks"]
        book = books[0] if books else None
        points = []
        if book:
            for item in book["must"]:
                points.append({"name": item, "priority": "P0", "source": book["title"]})
            for item in book["should"]:
                points.append({"name": item, "priority": "P1", "source": book["title"]})
        return {
            "task": task,
            "playbook": book,
            "techniques": book["techniques"] if book else [item["title"] for item in data["cards"][:3]],
            "must_test": book["must"] if book else [item["apply"][0] for item in data["cards"][:3] if item.get("apply")],
            "should_test": book["should"] if book else [],
            "skip_unless": book["skip_unless"] if book else [],
            "thinking": data["thinking"],
            "candidate_points": points,
            "knowledge": [{"id": item["id"], "title": item["title"]} for item in data["cards"]],
            "prompt": data["prompt"],
        }

    def format_prompt(self, cards: list[dict[str, Any]], books: list[dict[str, Any]] | None = None) -> str:
        sections: list[str] = []
        if books:
            for book in books[:2]:
                sections.append(
                    f"【场景手册 {book['title']}】\n"
                    f"必测：{'；'.join(book['must'][:4])}\n"
                    f"按风险补充：{'；'.join(book['should'][:3])}\n"
                    f"不要无脑全测：{'；'.join(book['skip_unless'][:2])}\n"
                    f"思维：{'；'.join(book['thinking'][:3])}"
                )
        for item in cards[:5]:
            sections.append(
                f"【{item['title']}】{item['principle']} "
                f"应用：{'；'.join(item['apply'][:3])}"
            )
        if not sections:
            return ""
        return (
            "你必须运用下列测试专家知识来分析、设计和取舍，而不是只回答定义，"
            "也不是无脑堆用例。按风险选择值得测的项。\n\n"
            + "\n\n".join(sections)
        )

    def stats(self) -> dict[str, Any]:
        return {
            "cards": len(all_cards()),
            "playbooks": len(all_playbooks()),
            "domains": domains(),
            "sources": SOURCES,
        }

    def _thinking_from(self, books: list[dict[str, Any]], cards: list[dict[str, Any]]) -> list[str]:
        lines = [
            "先识别用户目标和失败伤害，再选测试技术。",
            "覆盖正常、异常、边界、权限、会话/数据一致性，再按风险裁剪。",
            "能在接口或数据层证明的，不要只堆在UI上。",
        ]
        if books:
            lines.extend(books[0].get("thinking") or [])
        elif cards:
            lines.append(cards[0]["principle"])
        return lines[:6]


@lru_cache(maxsize=1)
def get_testing_expert() -> TestingExpertService:
    return TestingExpertService()


def expert_prompt_for(query: str, top_k: int = 5) -> str:
    try:
        return get_testing_expert().retrieve_for_task(query or "", top_k=top_k).get("prompt") or ""
    except Exception:
        return ""
