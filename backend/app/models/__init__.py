"""
数据模型模块
"""
from app.models.base import BaseModel, OwnedModel
from app.models.user import User, UserRole, Workspace
from app.models.team import (
    Organization,
    OrganizationMember,
    Project,
    ProjectMember,
    OrganizationInvite,
    OrgRole,
    ProjectRole,
)
from app.models.test_job import (
    TestJob,
    RegressionPipeline,
    RegressionPipelineItem,
    RegressionRun,
    JobStatus,
)
from app.models.assessment import PerformanceAssessment, PerformanceAssessmentMetric
from app.models.verification_code import VerificationCode
from app.models.task import Task, TaskStatus, InputMode, TaskType
from app.models.test_asset import TestAsset, AssetType, AssetStatus, SourceType, AssetSource
from app.models.image_file import ImageFile
from app.models.analysis_result import AnalysisResult
from app.models.script import Script
from app.models.ui_element import UIElement
from app.models.page_element import PageElement
from app.models.execution_record import ExecutionRecord, ExecutionStatus
from app.models.requirement_task import RequirementTask, RequirementStatus
from app.models.requirement_input import RequirementInput
from app.models.schedule_task import ScheduleTask, ScheduleType, ScheduleStatus, ScheduleRunLog
from app.models.feedback import Feedback
from app.models.case_task import CaseTask, CaseTaskStatus
from app.models.case_content import CaseContent, CaseType, CasePriority
from app.models.case_mindmap import CaseMindmap
from app.models.case_export import CaseExport, CaseExportStatus
from app.models.knowledge_source import KnowledgeSource, KnowledgeSourceStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.retrieval_log import RetrievalLog
from app.models.case_generation import CaseGeneration, CaseGenerationStatus
from app.models.session import Session, SessionStatus, SessionContent, SessionContentType
from app.models.requirement_chunk import RequirementChunk
from app.models.test_point import TestPoint
from app.models.session_event import SessionEvent
from app.models.api_case import ApiCase, ApiCaseFolder, ApiCaseMethod, TestType, ApiCasePriority, ApiCaseStatus
from app.models.test_suite import TestSuite, SuiteExecution
from app.models.workflow_event import WorkflowEvent, WorkflowEventType
from app.models.agent_result import AgentResult
from app.models.api_metadata import ApiMetadata
from app.models.requirement_center import (
    RequirementSession,
    RequirementFile,
    RequirementContext,
    RequirementAnalysis,
    RequirementReview,
    RequirementSummary,
    RequirementQuestion,
)
from app.models.flow_result import FlowResult
from app.models.agent_event import AgentEvent
from app.models.session_artifact import SessionArtifact
from app.models.tag import Tag, TagType, KnowledgeTag
from app.models.page_knowledge import (
    PageKnowledge,
    PageKnowledgeStatus,
    PageKnowledgeElement,
)
from app.models.api_knowledge import (
    APIKnowledge,
    APISourceType,
    APIDependency,
)
from app.models.agent_log import AgentLog
from app.models.agent_execution_log import AgentExecutionLog
from app.models.agent_registry import AgentRegistry
from app.models.test_requirement import TestRequirement
from app.models.test_case_point import TestCasePoint
from app.models.test_case import TestCase
from app.models.test_case_review import TestCaseReview
from app.models.mind_map import MindMap
from app.models.agent_message import AgentMessage

# ===== API 接口管理模块(新增,与既有 api_knowledge 解耦) =====
from app.models.api_endpoint import (
    ApiEndpoint,
    ApiEndpointVersion,
    ApiHeader,
    ApiBody,
    ApiParameter,
    EndpointStatus,
    EndpointSource,
    HTTPMethod,
    AuthType as EndpointAuthType,
)

# ===== 测试资产中心模块(新增,索引层叠加在既有业务表之上) =====
from app.models.asset_registry import (
    AssetRegistry,
    AssetVersion,
    AssetRelation,
    AssetRegistryType,
    AssetRegistryStatus,
    AssetRegistrySource,
    AssetRelationType,
)

# ===== 企业级 Agent Runtime 任务记录(新增) =====
from app.models.runtime_task import (
    RuntimeTask,
    RuntimeTaskStatus,
    RuntimeTaskPriority,
)

# ===== Prompt 版本管理(新增) =====
from app.models.prompt_version import (
    PromptVersion,
    PromptStatus,
)

# ===== 测试质量分析(新增) =====
from app.models.quality_report import QualityReport

# ===== AI 测试反馈学习(新增) =====
from app.models.feedback_learning import (
    FeedbackLearningRecord,
    FeedbackOptimization,
)

# ===== 企业级安全模块(新增) =====
from app.models.security import (
    ApiKey,
    OperationLog,
    AuditEvent,
    MaskingRule,
    AuditEventType,
    AuditSeverity,
    MaskType,
)

# ===== 性能测试模块(新增) =====
from app.models.performance import (
    PerformanceTask,
    PerformanceResult,
    PerformanceMetric,
    PerformanceTestType,
    TaskStatus as PerformanceTaskStatus,
    ResultStatus,
)

__all__ = [
    "BaseModel",
    "OwnedModel",
    "User",
    "UserRole",
    "Workspace",
    "Organization",
    "OrganizationMember",
    "Project",
    "ProjectMember",
    "OrganizationInvite",
    "OrgRole",
    "ProjectRole",
    "TestJob",
    "RegressionPipeline",
    "RegressionPipelineItem",
    "RegressionRun",
    "JobStatus",
    "PerformanceAssessment",
    "PerformanceAssessmentMetric",
    "VerificationCode",
    "Task",
    "TaskStatus",
    "InputMode",
    "TaskType",
    # ===== 统一资产模型 =====
    "TestAsset",
    "AssetType",
    "AssetStatus",
    "SourceType",
    "AssetSource",
    "ApiCase",
    "ApiCaseFolder",
    "ApiCaseMethod",
    "TestType",
    "ApiCasePriority",
    "ApiCaseStatus",
    "CaseContent",
    "CaseType",
    "CasePriority",
    "CaseTask",
    "CaseTaskStatus",
    "TestSuite",
    "SuiteExecution",
    # ===== 其他模型 =====
    "ImageFile",
    "AnalysisResult",
    "Script",
    "UIElement",
    "PageElement",
    "ExecutionRecord",
    "ExecutionStatus",
    "RequirementTask",
    "RequirementStatus",
    "RequirementInput",
    "ScheduleTask",
    "ScheduleType",
    "ScheduleStatus",
    "ScheduleRunLog",
    "Feedback",
    "CaseMindmap",
    "CaseExport",
    "CaseExportStatus",
    "KnowledgeSource",
    "KnowledgeSourceStatus",
    "KnowledgeChunk",
    "RetrievalLog",
    "CaseGeneration",
    "CaseGenerationStatus",
    "Session",
    "SessionStatus",
    "SessionContent",
    "SessionContentType",
    "RequirementChunk",
    "TestPoint",
    "SessionEvent",
    # ===== 工作流模型 =====
    "ApiMetadata",
    "WorkflowEvent",
    "WorkflowEventType",
    "AgentResult",
    # ===== RequirementCenter 第二阶段 =====
    "RequirementSession",
    "RequirementFile",
    "RequirementContext",
    "RequirementAnalysis",
    "RequirementReview",
    "RequirementSummary",
    "RequirementQuestion",
    # ===== FlowResult =====
    "FlowResult",
    # ===== AgentEvent =====
    "AgentEvent",
    # ===== SessionArtifact =====
    "SessionArtifact",
    # ===== Tag =====
    "Tag",
    "TagType",
    "KnowledgeTag",
    # ===== PageKnowledge =====
    "PageKnowledge",
    "PageKnowledgeStatus",
    "PageKnowledgeElement",
    # ===== APIKnowledge =====
    "APIKnowledge",
    "APISourceType",
    "APIDependency",
    # ===== AgentLog =====
    "AgentLog",
    # ===== AgentExecutionLog =====
    "AgentExecutionLog",
    # ===== TestCase 生成模块 =====
    "TestRequirement",
    "TestCasePoint",
    "TestCase",
    "TestCaseReview",
    "MindMap",
    "AgentMessage",
    # ===== API 接口管理模块 =====
    "ApiEndpoint",
    "ApiEndpointVersion",
    "EndpointStatus",
    "EndpointSource",
    "HTTPMethod",
    "EndpointAuthType",
    # ===== 测试资产中心模块 =====
    "AssetRegistry",
    "AssetVersion",
    "AssetRelation",
    "AssetRegistryType",
    "AssetRegistryStatus",
    "AssetRegistrySource",
    "AssetRelationType",
    # ===== Runtime 任务记录 =====
    "RuntimeTask",
    "RuntimeTaskStatus",
    "RuntimeTaskPriority",
    # ===== Prompt 版本管理 =====
    "PromptVersion",
    "PromptStatus",
    # ===== AI 测试反馈学习 =====
    "FeedbackLearningRecord",
    "FeedbackOptimization",
    # ===== 企业级安全模块 =====
    "ApiKey",
    "OperationLog",
    "AuditEvent",
    "MaskingRule",
    "AuditEventType",
    "AuditSeverity",
    "MaskType",
    # ===== 性能测试模块 =====
    "PerformanceTask",
    "PerformanceResult",
    "PerformanceMetric",
    "PerformanceTestType",
    "PerformanceTaskStatus",
    "ResultStatus",
]
