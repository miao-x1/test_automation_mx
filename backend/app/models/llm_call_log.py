"""
LLM 调用日志模型

记录每一次通过 LLMGateway 的大模型调用,用于:
- Token 用量统计
- 费用统计与预算监控
- 失败切换链路追踪
- Agent 维度的调用分析
"""
from sqlalchemy import Column, String, Integer, Float, Text, Index
from app.models.base import BaseModel


class LLMCallLog(BaseModel):
    """
    LLM 调用日志表

    每次 LLMGateway.chat() 调用(无论成功失败)都会写入一条记录。
    """
    __tablename__ = "llm_call_log"

    # ===== 调用来源 =====
    agent_name = Column(String(64), nullable=False, index=True, comment="调用方 Agent 名称")
    task_id = Column(String(64), nullable=True, index=True, comment="任务 ID(关联执行任务)")
    step = Column(String(64), nullable=True, comment="执行步骤标识")
    session_key = Column(String(128), nullable=True, comment="会话 key")

    # ===== 供应商与模型 =====
    provider = Column(String(32), nullable=False, index=True, comment="供应商:qwen/deepseek/openai/ollama/mock")
    model = Column(String(64), nullable=False, comment="实际命中的模型名")
    requested_model = Column(String(64), nullable=True, comment="原始请求的模型名(可能与 model 不同)")

    # ===== Token 用量 =====
    prompt_tokens = Column(Integer, default=0, nullable=False, comment="输入 token 数")
    completion_tokens = Column(Integer, default=0, nullable=False, comment="输出 token 数")
    total_tokens = Column(Integer, default=0, nullable=False, comment="总 token 数")

    # ===== 费用 =====
    cost = Column(Float, default=0.0, nullable=False, comment="本次调用费用(元)")
    currency = Column(String(8), default="CNY", nullable=False, comment="币种")

    # ===== 性能 =====
    duration = Column(Float, default=0.0, nullable=False, comment="耗时(秒)")

    # ===== 状态 =====
    status = Column(String(16), default="success", nullable=False, index=True,
                    comment="状态:success/failed")
    error_message = Column(Text, nullable=True, comment="错误信息(失败时)")
    error_type = Column(String(32), nullable=True, comment="错误类型:timeout/auth/rate_limit/network/server_error")

    # ===== 切换追踪 =====
    fallback_used = Column(Integer, default=0, nullable=False,
                           comment="是否触发了失败切换:0=否,1=是")
    fallback_chain = Column(Text, nullable=True, comment="切换链(JSON 数组)")
    attempt_index = Column(Integer, default=0, nullable=False, comment="第几次尝试(0=首次)")

    # ===== Prompt 摘要(截断存储,用于排查) =====
    prompt_preview = Column(Text, nullable=True, comment="system prompt 摘要(前500字)")

    def to_dict(self):
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "task_id": self.task_id,
            "step": self.step,
            "session_key": self.session_key,
            "provider": self.provider,
            "model": self.model,
            "requested_model": self.requested_model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": round(self.cost or 0, 6),
            "currency": self.currency,
            "duration": round(self.duration or 0, 3),
            "status": self.status,
            "error_message": (self.error_message or "")[:200] if self.error_message else None,
            "error_type": self.error_type,
            "fallback_used": bool(self.fallback_used),
            "fallback_chain": self.fallback_chain,
            "attempt_index": self.attempt_index,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return (f"<LLMCallLog(id={self.id}, agent={self.agent_name}, "
                f"provider={self.provider}, model={self.model}, "
                f"tokens={self.total_tokens}, cost={self.cost}, "
                f"status={self.status})>")


# 索引(复合索引提升查询性能)
Index("idx_llm_log_agent_time", LLMCallLog.agent_name, LLMCallLog.created_at)
Index("idx_llm_log_provider_time", LLMCallLog.provider, LLMCallLog.created_at)
Index("idx_llm_log_task", LLMCallLog.task_id, LLMCallLog.created_at)
Index("idx_llm_log_status_time", LLMCallLog.status, LLMCallLog.created_at)
