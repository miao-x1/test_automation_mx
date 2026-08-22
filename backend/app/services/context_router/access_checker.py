"""
RAGAccessChecker - 架构合规检查器

启动时扫描 app/agent/ 和 app/agents/ 目录下所有 Python 文件，
禁止 Agent 直接导入数据层客户端：

  禁止导入：
    - app.db.milvus_client      （Milvus 直接访问）
    - app.db.neo4j_client        （Neo4j 直接访问）
    - app.rag.embedding           （Embedding 直接访问）
    - app.rag.vector_store        （向量存储直接访问）
    - app.rag.graph_store         （图谱存储直接访问）
    - app.db.database             （SessionLocal 直接访问）

  允许导入：
    - app.services.context_router   （ContextRouter / StorageRouter）
    - app.models.*                    （仅用于枚举常量，如 TaskStatus.SUCCESS）

  白名单（基础设施，非普通 Agent）：
    - app/agents/factory/models.py   （AgentRegistry 元数据存储）

使用方式：
  from app.services.context_router.access_checker import RAGAccessChecker
  violations = RAGAccessChecker.check_at_startup()
  if violations:
      # 输出违规列表，阻止或警告
      ...
"""
import ast
import os
from dataclasses import dataclass, field
from typing import List, Optional, Set

from app.core.logger import log


# ------------------------------------------------------------------
# 禁止导入的模块前缀
# ------------------------------------------------------------------

FORBIDDEN_IMPORT_PREFIXES: List[str] = [
    "app.db.milvus_client",
    "app.db.neo4j_client",
    "app.rag.embedding",
    "app.rag.vector_store",
    "app.rag.graph_store",
    "app.db.database",          # SessionLocal — 禁止 Agent 直接访问
]

# 扫描目录（相对于 backend/ 根目录）
SCAN_DIRS: List[str] = [
    "app/agent",
    "app/agents",
]

# 跳过的目录名
SKIP_DIRS: Set[str] = {"__pycache__", ".trae", "venv"}

# 白名单文件（基础设施 / 复杂 Flow Agent，允许直接 DB 访问）
# - 基础设施: 数据模型定义
# - Flow Agent: 多步骤业务编排（feedback_learning / quality_analysis / api_data_generator / api_debug）
WHITELIST_FILES: Set[str] = {
    "app/agents/factory/models.py",                  # AgentRegistry 元数据存储
    "app/agents/flows/feedback_learning_agent.py",   # 反馈学习编排（需直接查询 FeedbackLearningRecord/Optimization）
    "app/agents/flows/quality_analysis_agent.py",    # 质量分析编排（需直接查询 QualityReport/Issue/Metric）
    "app/agents/flows/api_data_generator_agent.py",  # API 数据生成编排（需直接写入 api_test_data）
    "app/agents/flows/api_debug_agent.py",           # API 调试编排（需直接查询 api_execution_record）
}


@dataclass
class Violation:
    """单条违规记录"""
    file_path: str          # 相对路径
    line: int               # 行号
    import_statement: str   # import 语句原文
    forbidden_module: str   # 匹配到的禁止模块前缀

    def __str__(self) -> str:
        return (
            f"  [{self.file_path}:{self.line}] "
            f"{self.import_statement.strip()}  "
            f"→ 禁止导入 {self.forbidden_module}"
        )


@dataclass
class CheckResult:
    """扫描结果"""
    total_files_scanned: int = 0
    violations: List[Violation] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.violations) == 0

    def summary(self) -> str:
        if self.passed:
            return f"✅ 架构检查通过 | 扫描 {self.total_files_scanned} 个文件 | 0 条违规"
        return (
            f"❌ 架构检查失败 | 扫描 {self.total_files_scanned} 个文件 | "
            f"{len(self.violations)} 条违规"
        )


class RAGAccessChecker:
    """架构合规检查器

    扫描 Agent 目录，确保没有直接导入数据层客户端。
    所有数据访问必须通过 ContextRouter（读）或 StorageRouter（写）。

    禁止层级：
      1. Milvus 客户端  (app.db.milvus_client)
      2. Neo4j 客户端  (app.db.neo4j_client)
      3. Embedding     (app.rag.embedding)
      4. 向量存储      (app.rag.vector_store)
      5. 图谱存储      (app.rag.graph_store)
      6. SQLAlchemy    (app.db.database / SessionLocal)

    所有 Agent 必须通过以下方式访问数据：
      读取: from app.services.context_router import get_context_router
      写入: from app.services.context_router.storage_router import get_storage_router
    """

    @staticmethod
    def check() -> CheckResult:
        """执行架构检查

        Returns:
            CheckResult: 扫描结果
        """
        result = CheckResult()

        # 确定 backend 根目录
        backend_root = RAGAccessChecker._find_backend_root()
        if backend_root is None:
            log.warning("RAGAccessChecker | 无法定位 backend 根目录，跳过检查")
            return result

        for scan_dir in SCAN_DIRS:
            dir_path = os.path.join(backend_root, scan_dir)
            if not os.path.isdir(dir_path):
                continue
            for py_file in RAGAccessChecker._walk_python_files(dir_path):
                result.total_files_scanned += 1
                violations = RAGAccessChecker._check_file(py_file, backend_root)
                result.violations.extend(violations)

        return result

    @staticmethod
    def check_at_startup() -> bool:
        """启动时执行架构检查

        Returns:
            True 表示通过，False 表示有违规
        """
        log.info("RAGAccessChecker | 开始架构合规检查...")
        result = RAGAccessChecker.check()

        if result.passed:
            log.info(f"RAGAccessChecker | {result.summary()}")
        else:
            log.error(f"RAGAccessChecker | {result.summary()}")
            for v in result.violations:
                log.error(f"RAGAccessChecker | 违规: {v}")
            log.error(
                "RAGAccessChecker | "
                "Agent 禁止直接导入 milvus_client / neo4j_client / SessionLocal。"
                "请通过 ContextRouter（读取）或 StorageRouter（写入）访问数据层。"
            )

        return result.passed

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _find_backend_root() -> Optional[str]:
        """定位 backend 根目录"""
        current = os.path.dirname(os.path.abspath(__file__))
        for _ in range(3):
            current = os.path.dirname(current)
        if os.path.isfile(os.path.join(current, "alembic.ini")):
            return current
        current = os.path.dirname(os.path.abspath(__file__))
        for _ in range(3):
            current = os.path.dirname(current)
            if os.path.isdir(os.path.join(current, "app")):
                return current
        return None

    @staticmethod
    def _walk_python_files(root_dir: str):
        """遍历目录下的所有 .py 文件"""
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for filename in filenames:
                if filename.endswith(".py"):
                    yield os.path.join(dirpath, filename)

    @staticmethod
    def _check_file(file_path: str, backend_root: str) -> List[Violation]:
        """检查单个文件的 import 语句"""
        violations: List[Violation] = []

        # 转为相对路径
        rel_path = os.path.relpath(file_path, backend_root).replace("\\", "/")

        # 白名单文件跳过检查
        if rel_path in WHITELIST_FILES:
            return violations

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            log.warning(f"RAGAccessChecker | 读取文件失败: {file_path}: {e}")
            return violations

        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError as e:
            log.warning(f"RAGAccessChecker | 语法错误: {file_path}: {e}")
            return violations

        # 遍历 AST 节点，查找所有 import 语句
        for node in ast.walk(tree):
            module_name = None
            import_text = ""

            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    import_text = f"import {module_name}"
                    forbidden = RAGAccessChecker._check_forbidden(module_name)
                    if forbidden:
                        violations.append(Violation(
                            file_path=rel_path,
                            line=node.lineno,
                            import_statement=import_text,
                            forbidden_module=forbidden,
                        ))

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                imported_names = ", ".join(a.name for a in node.names)
                import_text = f"from {module_name} import {imported_names}"
                forbidden = RAGAccessChecker._check_forbidden(module_name)
                if forbidden:
                    violations.append(Violation(
                        file_path=rel_path,
                        line=node.lineno,
                        import_statement=import_text,
                        forbidden_module=forbidden,
                    ))

        return violations

    @staticmethod
    def _check_forbidden(module_name: str) -> str:
        """检查模块名是否在禁止列表中"""
        for prefix in FORBIDDEN_IMPORT_PREFIXES:
            if module_name == prefix or module_name.startswith(prefix + "."):
                return prefix
        return ""
