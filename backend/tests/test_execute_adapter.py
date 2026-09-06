"""P1-4: classifier execute(**kwargs) 必须能被 Runtime 调用。"""
import pytest

from app.runtime.execute_adapter import invoke_execute


class KwargsAgent:
    agent_name = "test_type_classifier"

    async def execute(self, **kwargs):
        return {"ok": True, "requirement": kwargs.get("requirement")}


class PayloadCtxAgent:
    agent_name = "routed"

    async def execute(self, payload, ctx):
        return {"ok": True, "payload": payload, "has_ctx": ctx is not None}


class NoExecute:
    agent_name = "broken"


@pytest.mark.asyncio
async def test_kwargs_agent_receives_payload_fields():
    result = await invoke_execute(KwargsAgent(), {"requirement": "测试登录"}, ctx="unused")
    assert result == {"ok": True, "requirement": "测试登录"}


@pytest.mark.asyncio
async def test_payload_ctx_agent_still_works():
    result = await invoke_execute(PayloadCtxAgent(), {"a": 1}, ctx="ctx")
    assert result["ok"] is True
    assert result["payload"] == {"a": 1}
    assert result["has_ctx"] is True


@pytest.mark.asyncio
async def test_missing_execute_raises():
    with pytest.raises(RuntimeError, match="没有 execute"):
        await invoke_execute(NoExecute(), {})


@pytest.mark.asyncio
async def test_real_classifier_signature():
    from app.agent.requirement.test_type_classifier_agent import TestTypeClassifierAgent

    agent = TestTypeClassifierAgent()
    result = await invoke_execute(agent, {"requirement": "打开 https://www.baidu.com 做UI自动化"}, None)
    assert result.get("test_type") in {"web", "api", "android", "performance"}
    assert "confidence" in result
