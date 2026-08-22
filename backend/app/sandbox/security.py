"""
代码安全检查器

通过 AST 静态分析, 在代码执行前拦截危险操作:
  1. 危险导入检测 (os.subprocess / socket / shutil / ctypes 等)
  2. 危险函数调用 (eval / exec / compile / __import__ / open 写模式)
  3. 危险属性访问 (__builtins__ / __globals__ / __subclasses__)
  4. 网络访问检测 (socket / urllib / http.client)
  5. 文件系统写入检测 (open with 'w' / 'a' / 'x')
  6. 进程操作检测 (os.system / subprocess.Popen / os.exec)

安全级别:
  SAFE      — 安全, 允许执行
  WARNING   — 警告, 允许执行但记录
  DANGEROUS — 危险, 禁止执行

设计约束:
  - 纯静态分析, 不执行代码
  - 基于 AST, 不依赖正则 (避免误判)
  - 白名单优先, 默认拒绝未知危险模式
"""
import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class SecurityLevel(str, Enum):
    """安全级别"""
    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"


@dataclass
class SecurityReport:
    """安全检查报告"""
    level: SecurityLevel = SecurityLevel.SAFE
    issues: List[Dict[str, Any]] = field(default_factory=list)
    allowed_imports: List[str] = field(default_factory=list)
    blocked_imports: List[str] = field(default_factory=list)
    code_lines: int = 0
    ast_valid: bool = True
    parse_error: str = ""

    @property
    def is_allowed(self) -> bool:
        """是否允许执行 (SAFE 和 WARNING 允许, DANGEROUS 禁止)"""
        return self.level != SecurityLevel.DANGEROUS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "is_allowed": self.is_allowed,
            "issues": self.issues,
            "allowed_imports": self.allowed_imports,
            "blocked_imports": self.blocked_imports,
            "code_lines": self.code_lines,
            "ast_valid": self.ast_valid,
            "parse_error": self.parse_error,
        }


class SecurityPolicy:
    """安全策略配置"""

    # 允许导入的模块白名单
    ALLOWED_MODULES: Set[str] = {
        # 标准库 - 数据处理
        "json", "csv", "math", "statistics", "random",
        "itertools", "collections", "functools", "operator",
        "decimal", "fractions", "numbers",
        # 标准库 - 数据结构
        "array", "heapq", "bisect", "queue", "enum",
        # 标准库 - 文本处理
        "re", "string", "textwrap", "unicodedata", "codecs",
        # 标准库 - 日期时间
        "datetime", "calendar", "time",
        # 标准库 - 类型/工具
        "typing", "dataclasses", "copy", "pprint",
        "pathlib",  # 只读路径操作
        # 标准库 - 解析
        "ast", "html", "xml.etree.ElementTree", "xml.dom",
        "configparser", "tomllib",
        # 标准库 - 压缩 (只读解压)
        "zipfile", "tarfile", "gzip",
        # 第三方 - 数据分析
        "pandas", "numpy", "scipy", "sklearn",
        "openpyxl", "xlrd", "xlwt",
        "matplotlib", "seaborn",
        # 第三方 - 工具
        "PIL", "PIL.Image",
    }

    # 绝对禁止的模块 (即使 import 也拦截)
    BLOCKED_MODULES: Set[str] = {
        "os", "sys", "subprocess", "socket", "signal",
        "shutil", "ctypes", "multiprocessing",
        "threading", "asyncio.subprocess",
        "importlib", "builtins",
        "pdb", "bdb", "framehack",
        "pickle", "shelve",  # 反序列化风险
        "marshal", "code", "codeop",
        "commands", "popen2", "pty",
        "tempfile",  # 沙箱内由执行器管理临时目录
    }

    # 禁止的函数调用 (全限定名模式)
    BLOCKED_CALLS: Set[str] = {
        "eval", "exec", "compile",
        "__import__", "globals", "locals",
        "vars", "dir", "getattr", "setattr", "delattr",
        "exit", "quit", "input",
        "breakpoint", "help",
        "memoryview",
    }

    # 禁止的属性访问模式
    BLOCKED_ATTRS: Set[str] = {
        "__builtins__", "__globals__", "__locals__",
        "__subclasses__", "__bases__", "__mro__",
        "__class__", "__dict__",
        "f_globals", "f_locals", "f_builtins",
        "gi_frame", "cr_frame",
    }

    # 允许 open() 但仅限只读模式
    ALLOW_OPEN_READ: bool = True

    # 最大代码行数
    MAX_CODE_LINES: int = 500

    # 最大代码字符数
    MAX_CODE_CHARS: int = 50000

    @classmethod
    def is_module_allowed(cls, module_name: str) -> Optional[bool]:
        """检查模块是否在白名单中"""
        # 检查完整模块名
        if module_name in cls.BLOCKED_MODULES:
            return False

        # 检查顶层模块
        top_level = module_name.split(".")[0]
        if top_level in cls.BLOCKED_MODULES:
            return False

        # 白名单检查 (支持前缀匹配, 如 PIL.Image)
        for allowed in cls.ALLOWED_MODULES:
            if module_name == allowed or module_name.startswith(allowed + "."):
                return True

        # 不在白名单但也不在黑名单 → WARNING
        return None  # type: ignore


class CodeSecurityChecker:
    """代码安全检查器

    使用 AST 静态分析检测代码中的危险操作。

    使用方式:
        checker = CodeSecurityChecker()
        report = checker.check(code_string)
        if not report.is_allowed:
            raise SecurityError(report)
    """

    def __init__(self, policy: Optional[SecurityPolicy] = None) -> None:
        self.policy = policy or SecurityPolicy()

    def check(self, code: str) -> SecurityReport:
        """执行完整安全检查

        Args:
            code: Python 源代码字符串

        Returns:
            SecurityReport 安全检查报告
        """
        report = SecurityReport()
        report.code_lines = len(code.splitlines())

        # 1. 代码长度检查
        if len(code) > self.policy.MAX_CODE_CHARS:
            report.level = SecurityLevel.DANGEROUS
            report.issues.append({
                "type": "code_too_long",
                "message": f"代码超过最大长度限制 ({self.policy.MAX_CODE_CHARS} 字符)",
                "severity": "dangerous",
            })
            return report

        if report.code_lines > self.policy.MAX_CODE_LINES:
            report.level = SecurityLevel.DANGEROUS
            report.issues.append({
                "type": "code_too_many_lines",
                "message": f"代码超过最大行数限制 ({self.policy.MAX_CODE_LINES} 行)",
                "severity": "dangerous",
            })
            return report

        # 2. AST 解析
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            report.ast_valid = False
            report.parse_error = str(e)
            report.level = SecurityLevel.DANGEROUS
            report.issues.append({
                "type": "syntax_error",
                "message": f"语法错误: {e}",
                "severity": "dangerous",
                "line": e.lineno,
            })
            return report

        # 3. 遍历 AST 检测危险模式
        visitor = _SecurityVisitor(self.policy)
        visitor.visit(tree)

        # 汇总结果
        report.issues = visitor.issues
        report.allowed_imports = visitor.allowed_imports
        report.blocked_imports = visitor.blocked_imports

        # 根据问题严重度确定最终级别
        if visitor.has_dangerous:
            report.level = SecurityLevel.DANGEROUS
        elif visitor.has_warning:
            report.level = SecurityLevel.WARNING
        else:
            report.level = SecurityLevel.SAFE

        return report


class _SecurityVisitor(ast.NodeVisitor):
    """AST 访问器, 检测危险模式"""

    def __init__(self, policy: SecurityPolicy) -> None:
        self.policy = policy
        self.issues: List[Dict[str, Any]] = []
        self.allowed_imports: List[str] = []
        self.blocked_imports: List[str] = []
        self.has_dangerous = False
        self.has_warning = False

    def _add_issue(self, issue_type: str, message: str, severity: str,
                   lineno: int = 0, detail: str = "") -> None:
        self.issues.append({
            "type": issue_type,
            "message": message,
            "severity": severity,
            "line": lineno,
            "detail": detail,
        })
        if severity == "dangerous":
            self.has_dangerous = True
        elif severity == "warning":
            self.has_warning = True

    def visit_Import(self, node: ast.Import) -> None:
        """检查 import 语句"""
        for alias in node.names:
            module_name = alias.name
            allowed = self.policy.is_module_allowed(module_name)

            if allowed is False:
                self.blocked_imports.append(module_name)
                self._add_issue(
                    "blocked_import",
                    f"禁止导入模块: {module_name}",
                    "dangerous",
                    lineno=node.lineno,
                    detail=f"模块 '{module_name}' 在黑名单中",
                )
            elif allowed is True:
                self.allowed_imports.append(module_name)
            else:
                # None = 不在白名单也不在黑名单 → WARNING
                self.allowed_imports.append(module_name)
                self._add_issue(
                    "unknown_import",
                    f"非白名单模块: {module_name}",
                    "warning",
                    lineno=node.lineno,
                    detail=f"模块 '{module_name}' 不在白名单中, 允许但需关注",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """检查 from ... import 语句"""
        module_name = node.module or ""
        if module_name:
            allowed = self.policy.is_module_allowed(module_name)

            if allowed is False:
                self.blocked_imports.append(module_name)
                self._add_issue(
                    "blocked_import",
                    f"禁止导入模块: {module_name}",
                    "dangerous",
                    lineno=node.lineno,
                    detail=f"模块 '{module_name}' 在黑名单中",
                )
            elif allowed is True:
                self.allowed_imports.append(module_name)
            else:
                self.allowed_imports.append(module_name)
                self._add_issue(
                    "unknown_import",
                    f"非白名单模块: {module_name}",
                    "warning",
                    lineno=node.lineno,
                )

        # 检查导入的具体名称
        for alias in node.names:
            if alias.name in self.policy.BLOCKED_CALLS:
                self._add_issue(
                    "blocked_import_name",
                    f"禁止导入: {alias.name}",
                    "dangerous",
                    lineno=node.lineno,
                    detail=f"'{alias.name}' 在禁止函数列表中",
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """检查函数调用"""
        call_name = self._get_call_name(node)

        if call_name:
            # 检查禁止的函数调用
            if call_name in self.policy.BLOCKED_CALLS:
                self._add_issue(
                    "blocked_call",
                    f"禁止调用函数: {call_name}()",
                    "dangerous",
                    lineno=node.lineno,
                )

            # 检查 open() 写模式
            if call_name == "open" and self._is_write_open(node):
                self._add_issue(
                    "file_write",
                    f"禁止文件写入: open() 写模式",
                    "dangerous",
                    lineno=node.lineno,
                    detail="沙箱内禁止写入文件系统 (仅允许只读 open)",
                )

            # 检查 os.*/subprocess.* 调用
            if call_name.startswith("os.") or call_name.startswith("subprocess."):
                self._add_issue(
                    "system_call",
                    f"禁止系统调用: {call_name}()",
                    "dangerous",
                    lineno=node.lineno,
                )

            # 检查 socket 调用
            if call_name.startswith("socket.") or "socket" in call_name:
                self._add_issue(
                    "network_access",
                    f"禁止网络访问: {call_name}()",
                    "dangerous",
                    lineno=node.lineno,
                )

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """检查属性访问"""
        attr_name = node.attr

        if attr_name in self.policy.BLOCKED_ATTRS:
            self._add_issue(
                "blocked_attribute",
                f"禁止访问属性: .{attr_name}",
                "dangerous",
                lineno=node.lineno,
                detail=f"访问 '{attr_name}' 可能导致沙箱逃逸",
            )

        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """检查变量名引用"""
        if node.id in self.policy.BLOCKED_CALLS and isinstance(node.ctx, ast.Load):
            # 仅检查作为函数调用使用的名称 (这里只能检测引用, 调用在 visit_Call 中处理)
            pass
        self.generic_visit(node)

    @staticmethod
    def _get_call_name(node: ast.Call) -> str:
        """获取函数调用的名称 (支持 a.b.c 形式)"""
        func = node.func

        if isinstance(func, ast.Name):
            return func.id

        if isinstance(func, ast.Attribute):
            # 递归获取属性链: a.b.c
            parts = []
            current = func
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            parts.reverse()
            return ".".join(parts)

        return ""

    def _is_write_open(self, node: ast.Call) -> bool:
        """检查 open() 是否为写模式"""
        if len(node.args) < 2 and not node.keywords:
            # open(file) 默认只读
            return False

        # 检查位置参数 (第二个参数是 mode)
        if len(node.args) >= 2:
            mode_arg = node.args[1]
            if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
                mode = mode_arg.value
                return any(m in mode for m in ("w", "a", "x", "+"))

        # 检查关键字参数
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
                if isinstance(mode, str):
                    return any(m in mode for m in ("w", "a", "x", "+"))

        return False
