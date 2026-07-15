"""
Agent 统一异常体系
所有 Agent 相关异常统一继承 AgentError，便于上层统一捕获和处理。
"""
from typing import Optional, Any, Dict


class AgentError(Exception):
    """Agent 基础异常"""

    def __init__(self, message: str, agent_name: Optional[str] = None,
                 code: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.agent_name = agent_name
        self.code = code or "AGENT_ERROR"
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "message": self.message,
            "agent_name": self.agent_name,
            "code": self.code,
            "details": self.details,
        }


class AgentConfigError(AgentError):
    """Agent 配置异常"""
    pass


class AgentNotFoundError(AgentError):
    """Agent 未找到异常"""

    def __init__(self, agent_name: str):
        super().__init__(
            message=f"Agent '{agent_name}' not found in registry",
            agent_name=agent_name,
            code="AGENT_NOT_FOUND",
        )


class AgentAlreadyExistsError(AgentError):
    """Agent 重复注册异常"""

    def __init__(self, agent_name: str):
        super().__init__(
            message=f"Agent '{agent_name}' already registered",
            agent_name=agent_name,
            code="AGENT_ALREADY_EXISTS",
        )


class AgentExecutionError(AgentError):
    """Agent 执行异常"""

    def __init__(self, message: str, agent_name: Optional[str] = None,
                 cause: Optional[Exception] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(message=message, agent_name=agent_name, code="AGENT_EXECUTION_ERROR", details=details)
        self.cause = cause
        if cause:
            self.details["cause_type"] = type(cause).__name__
            self.details["cause_message"] = str(cause)


class AgentTimeoutError(AgentError):
    """Agent 超时异常"""

    def __init__(self, agent_name: str, timeout: int):
        super().__init__(
            message=f"Agent '{agent_name}' timed out after {timeout}s",
            agent_name=agent_name,
            code="AGENT_TIMEOUT",
            details={"timeout": timeout},
        )


class AgentValidationError(AgentError):
    """Agent 输入校验异常"""
    pass


class AgentLLMError(AgentError):
    """LLM 调用异常"""

    def __init__(self, message: str, agent_name: Optional[str] = None,
                 status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message=message, agent_name=agent_name, code="AGENT_LLM_ERROR")
        if status_code:
            self.details["status_code"] = status_code
        if response_body:
            self.details["response_body"] = response_body[:500]


class RuntimeNotFoundError(AgentError):
    """Runtime 未找到异常"""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"Runtime for session '{session_id}' not found",
            code="RUNTIME_NOT_FOUND",
            details={"session_id": session_id},
        )


class RuntimeAlreadyExistsError(AgentError):
    """Runtime 重复创建异常"""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"Runtime for session '{session_id}' already exists",
            code="RUNTIME_ALREADY_EXISTS",
            details={"session_id": session_id},
        )


class RuntimeStateError(AgentError):
    """Runtime 状态异常（如尝试操作已关闭的 Runtime）"""
    pass


class MemoryError(AgentError):
    """Memory 操作异常"""
    pass


class MessageRoutingError(AgentError):
    """消息路由异常"""
    pass
