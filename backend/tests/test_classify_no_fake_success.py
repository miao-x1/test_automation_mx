"""P0-4: classify 失败必须是失败，不能返回默认 web 假成功。"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")

import pytest
from fastapi import HTTPException

from app.api.requirement import classify_test_type, ClassifyRequest


@pytest.mark.asyncio
async def test_empty_requirement_is_invalid():
    with pytest.raises(HTTPException) as exc:
        await classify_test_type(ClassifyRequest(requirement=""), user=SimpleNamespace(id=1))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_runtime_failure_is_not_fake_success():
    fake_dispatcher = SimpleNamespace(
        submit=AsyncMock(return_value="t1"),
        wait_for_result=AsyncMock(return_value=SimpleNamespace(status="failed", error="LLM timeout", result=None)),
    )
    with patch("app.runtime.enterprise.get_task_dispatcher", return_value=fake_dispatcher):
        with pytest.raises(HTTPException) as exc:
            await classify_test_type(
                ClassifyRequest(requirement="登录页面输入用户名和密码并点击登录。"),
                user=SimpleNamespace(id=1),
            )
    assert exc.value.status_code == 502
    assert "web" not in str(exc.value.detail).lower() or "LLM" in str(exc.value.detail)
    assert "默认为Web" not in str(exc.value.detail)
