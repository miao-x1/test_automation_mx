"""P1-1: RAG 空 elements 不能冲掉 Vision 识别结果。"""
from app.runtime.task_context import TaskContext


def test_merge_input_keeps_vision_elements_when_rag_empty():
    ctx = TaskContext(payload={"requirement": "open baidu"})
    ctx.finish_step("analyze_image", {
        "status": "SUCCESS",
        "elements": [{"name": "搜索", "type": "input", "css": "#kw"}],
    })
    ctx.finish_step("rag_retrieve", {"elements": [], "cases": [], "scripts": []})
    merged = ctx.merge_input()
    assert merged["elements"]
    assert merged["elements"][0]["css"] == "#kw"
