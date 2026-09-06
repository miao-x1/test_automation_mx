"""generateCasesSSE 后端链路：空需求拒绝；真实 Agent 可实例化。"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.case import _case_agents, router


def test_case_agents_are_real():
    selector, generator = _case_agents()
    assert callable(selector.parse)
    assert callable(generator.generate_rag_cases)
    assert generator.agent_name == "case_agent"


def test_generate_rejects_empty_input():
    app = FastAPI()
    app.include_router(router, prefix="/case")
    client = TestClient(app)
    resp = client.post("/case/generate", data={"source_type": "text", "raw_text": "", "url": ""})
    assert resp.status_code == 400
    assert "需求" in resp.json()["detail"]
