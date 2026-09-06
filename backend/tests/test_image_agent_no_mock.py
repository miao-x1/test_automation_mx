"""ImageAgent / ElementAgent：无输入必须 INVALID_INPUT，禁止 mock 元素冒充 SUCCESS。"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")

from app.agents.flows.image_agent import (
    STATUS_FAILED,
    STATUS_INVALID_INPUT,
    STATUS_SUCCESS,
    decide_image_source,
)
from app.agent.vision.element_agent import ElementAgent


def test_decide_image_source():
    assert decide_image_source([], []) == "invalid"
    assert decide_image_source([""], ["  "]) == "invalid"
    assert decide_image_source(["https://example.com/login"], []) == "url"
    assert decide_image_source([], ["C:/shot.png"]) == "upload"
    assert decide_image_source(["https://example.com"], ["C:/shot.png"]) == "upload"


def test_element_agent_no_image_is_invalid_input():
    agent = ElementAgent()
    result = agent.execute()
    assert result["status"] == STATUS_INVALID_INPUT
    assert result["elements"] == []
    assert "登录按钮" not in str(result)


def test_element_agent_analyze_no_image():
    agent = ElementAgent()
    result = agent.analyze({})
    assert result["status"] == STATUS_INVALID_INPUT
    assert result["elements"] == []


def test_status_constants_distinct():
    assert STATUS_SUCCESS != STATUS_FAILED != STATUS_INVALID_INPUT
    assert {STATUS_SUCCESS, STATUS_FAILED, STATUS_INVALID_INPUT} == {"SUCCESS", "FAILED", "INVALID_INPUT"}
