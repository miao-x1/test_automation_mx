"""P1-10: 所有已注册 Agent/Flow 模块必须可 import，禁止指向不存在的模块。"""
import importlib
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")

import pytest

from app.agents.factory.definitions import DEFAULT_AGENT_SPECS
from app.agent.factory.registry import _AGENT_DEFINITIONS


def _import_class(module_path: str, class_name: str):
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    assert cls is not None, f"{class_name} not in {module_path}"
    return cls


def test_default_agent_specs_importable():
    failed = []
    for spec in DEFAULT_AGENT_SPECS:
        try:
            _import_class(spec.module_path, spec.class_name)
        except Exception as exc:
            failed.append(f"{spec.name}: {spec.module_path}.{spec.class_name} -> {exc}")
    assert not failed, "DEFAULT_AGENT_SPECS import failures:\n" + "\n".join(failed)


def test_legacy_registry_definitions_importable():
    failed = []
    for name, module_path, class_name, _display, _caps in _AGENT_DEFINITIONS:
        try:
            _import_class(module_path, class_name)
        except Exception as exc:
            failed.append(f"{name}: {module_path}.{class_name} -> {exc}")
    assert not failed, "legacy registry import failures:\n" + "\n".join(failed)


def test_flow_agent_specs_aligned():
    from app.agents.flows import FLOW_AGENT_SPECS

    failed = []
    for spec in FLOW_AGENT_SPECS:
        try:
            _import_class(spec["module_path"], spec["class_name"])
        except Exception as exc:
            failed.append(f"{spec['name']}: {exc}")
    assert not failed, "FLOW_AGENT_SPECS import failures:\n" + "\n".join(failed)


def test_graph_flow_review_nodes_use_real_review_agent():
    from app.agent.case.review_agent import ReviewAgent

    src = Path(__file__).resolve().parents[1] / "app" / "runtime" / "graph_flow_manager.py"
    text = src.read_text(encoding="utf-8")
    for node_name in ("CaseReview", "SecurityReview", "PerformanceReview", "AccessibilityReview"):
        assert f'"{node_name}": ("app.agent.case.review_agent", "ReviewAgent")' in text
    _import_class("app.agent.case.review_agent", "ReviewAgent")
    assert ReviewAgent.__name__ == "ReviewAgent"


def test_removed_invalid_registrations():
    names = {spec.name for spec in DEFAULT_AGENT_SPECS}
    legacy = {row[0] for row in _AGENT_DEFINITIONS}
    assert "mock_agent" not in legacy
    assert "router_agent" not in legacy
    assert "graph_search_agent" not in legacy
    assert "flow_requirement_agent" in names
    req = next(s for s in DEFAULT_AGENT_SPECS if s.name == "flow_requirement_agent")
    assert req.module_path == "app.agent.requirement.requirement_agent"


def test_create_agent_requires_real_type():
    from app.agent.factory.agent_factory import AgentFactory

    with pytest.raises(ValueError):
        AgentFactory.create_agent()
