"""
查询处理器实现

完整查询处理流程：
1. 查询扩展（同义词扩展 + LLM 重写）
2. 关键词提取
3. 过滤条件组装（source_types -> filter）

查询扩展策略：
  - 同义词扩展：内置测试领域同义词表（如"登录" -> login/认证/鉴权）
  - LLM 重写：当 LLM 可用时，让 LLM 对查询进行改写与扩展
  - 规则扩展：LLM 不可用时使用同义词表拼接

说明：
  RAGQuery 模型无 expanded_query 字段，因此扩展后的查询文本存放于
  query.filters["_expanded_query"]，原始 query.query 保持不变，
  供检索器 / 上层服务读取使用。
"""
import logging
import os
import re
from typing import Dict, List, Optional, Set

from app.rag.models import RAGQuery
from app.rag.query.base import BaseQueryProcessor

logger = logging.getLogger(__name__)

# 存放扩展查询的保留键（位于 filters 中）
EXPANDED_QUERY_KEY = "_expanded_query"
# 存放提取关键词的保留键
KEYWORDS_KEY = "_keywords"

# ----------------------------------------------------------------------
# 测试领域同义词表
# 键为中文术语，值为同义 / 等价表达（中英文混合）
# ----------------------------------------------------------------------
SYNONYMS: Dict[str, List[str]] = {
    "登录": ["login", "登入", "认证", "鉴权", "signin", "sign in", "授权登录"],
    "登出": ["logout", "登出", "注销", "退出登录", "signout", "sign out"],
    "注册": ["register", "signup", "sign up", "创建账号", "账号注册"],
    "搜索": ["search", "查询", "检索", "查找", "filter", "筛选"],
    "上传": ["upload", "导入", "import", "上传文件"],
    "下载": ["download", "导出", "export", "下载文件"],
    "提交": ["submit", "保存", "save", "确认提交"],
    "删除": ["delete", "remove", "移除", "删除操作"],
    "编辑": ["edit", "修改", "update", "更新", "modify"],
    "新增": ["add", "create", "新建", "创建", "新增操作"],
    "列表": ["list", "表格", "table", "数据列表", "列表页"],
    "详情": ["detail", "详细信息", "info", "查看详情"],
    "分页": ["pagination", "翻页", "page", "page size", "分页器"],
    "弹窗": ["dialog", "modal", "弹框", "对话框", "popup", "提示框"],
    "表单": ["form", "表单提交", "输入表单", "form表单"],
    "按钮": ["button", "btn", "操作按钮", "点击按钮"],
    "输入框": ["input", "文本框", "输入", "textfield", "输入控件"],
    "下拉框": ["select", "dropdown", "下拉选择", "选择器"],
    "复选框": ["checkbox", "多选框", "勾选框"],
    "单选框": ["radio", "单选", "radiobutton", "单选按钮"],
    "开关": ["switch", "toggle", "切换", "开关组件"],
    "标签页": ["tab", "标签", "选项卡", "tab页", "tab选项卡"],
    "菜单": ["menu", "导航", "navigation", "nav", "菜单栏"],
    "面包屑": ["breadcrumb", "导航路径", "面包屑导航"],
    "侧边栏": ["sidebar", "侧栏", "侧边菜单", "侧边导航"],
    "表格组件": ["table", "datatable", "数据表格", "grid"],
    "树形": ["tree", "树", "树形结构", "treeview", "树节点"],
    "异常": ["exception", "error", "错误", "报错", "异常处理"],
    "校验": ["validate", "validation", "验证", "校验规则", "表单校验"],
    "权限": ["permission", "authority", "角色", "role", "rbac", "访问控制"],
    "接口": ["api", "接口", "endpoint", "rest", "接口文档"],
    "用例": ["testcase", "test case", "测试用例", "用例"],
    "断言": ["assert", "assertion", "断言", "期望结果"],
    "截图": ["screenshot", "snapshot", "页面截图", "截屏"],
    "加载": ["loading", "加载中", "loading状态", "骨架屏"],
    "提示": ["toast", "message", "提示信息", "通知", "notification", "snackbar"],
    "导入导出": ["importexport", "导入导出", "excel", "excel导入"],
    "工作流": ["workflow", "流程", "审批流", "工作流引擎"],
    "仪表盘": ["dashboard", "概览", "首页", "首页看板"],
}


class QueryProcessor(BaseQueryProcessor):
    """查询处理器"""

    # 反向同义词索引：term -> [原始术语...]，便于英文/同义检索
    _REVERSE_INDEX: Dict[str, List[str]] = {}

    def __init__(self):
        self._build_reverse_index()
        self._llm_config: Optional[Dict] = None
        self._llm_config_inited = False

    # ------------------------------------------------------------------
    # 同义词索引
    # ------------------------------------------------------------------
    def _build_reverse_index(self) -> None:
        """构建反向索引：任一同义表达 -> 对应原始术语集合"""
        index: Dict[str, List[str]] = {}
        for term, syns in SYNONYMS.items():
            # 原始术语本身
            key = term.lower()
            index.setdefault(key, []).append(term)
            for syn in syns:
                k = syn.lower()
                index.setdefault(k, []).append(term)
        self._REVERSE_INDEX = index

    def _get_synonyms(self, token: str) -> List[str]:
        """获取某个 token 的同义词（含自身原始术语集合）"""
        if not token:
            return []
        key = token.lower()
        # 命中原始术语
        if key in SYNONYMS:
            return list(SYNONYMS[key])
        # 命中反向索引（作为同义表达）
        if key in self._REVERSE_INDEX:
            results: Set[str] = set()
            for term in self._REVERSE_INDEX[key]:
                results.add(term)
                results.update(SYNONYMS.get(term, []))
            results.discard(token)
            return list(results)
        return []

    # ------------------------------------------------------------------
    # LLM 配置检测（惰性）
    # ------------------------------------------------------------------
    def _get_llm_config(self) -> Optional[Dict]:
        """检测可用的 LLM 配置"""
        if self._llm_config_inited:
            return self._llm_config
        self._llm_config_inited = True

        try:
            from app.core.config import settings  # noqa: F401
        except Exception:
            settings = None  # type: ignore

        dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
        if not dashscope_key and settings is not None:
            dashscope_key = getattr(settings, "QWEN_API_KEY", "") or ""
        if dashscope_key:
            self._llm_config = {
                "provider": "dashscope",
                "api_key": dashscope_key,
                "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                "model": os.getenv("LLM_MODEL", "qwen-plus"),
            }
            return self._llm_config

        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        if not deepseek_key and settings is not None:
            deepseek_key = getattr(settings, "DEEPSEEK_API_KEY", "") or ""
        if deepseek_key:
            self._llm_config = {
                "provider": "deepseek",
                "api_key": deepseek_key,
                "url": "https://api.deepseek.com/v1/chat/completions",
                "model": os.getenv("LLM_MODEL", "deepseek-chat"),
            }
            return self._llm_config

        self._llm_config = None
        return self._llm_config

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    async def process(self, query: RAGQuery) -> RAGQuery:
        """完整查询处理流程

        步骤：
          1. 关键词提取
          2. 查询扩展（同义词 + LLM）
          3. 过滤条件组装
        """
        if not query.query or not query.query.strip():
            return query

        # 1. 关键词提取
        keywords = self.extract_keywords(query.query)
        if keywords:
            query.filters[KEYWORDS_KEY] = keywords

        # 2. 查询扩展
        if query.expand_query:
            expanded = await self.expand_query(query.query)
            query.filters[EXPANDED_QUERY_KEY] = expanded
            logger.info(
                f"[QueryProcessor] 查询扩展完成: 原始='{query.query[:50]}' -> "
                f"扩展='{expanded[:80]}'"
            )

        # 3. 过滤条件组装
        filter_expr = self.build_filter(query.source_types)
        if filter_expr:
            # 仅在未显式设置 source_type 时写入，避免覆盖用户自定义
            if "source_type" not in query.filters:
                query.filters["source_type"] = filter_expr["source_type"]

        return query

    async def expand_query(self, query: str) -> str:
        """查询扩展

        优先使用 LLM 重写；不可用时使用同义词规则扩展。
        """
        if not query or not query.strip():
            return query

        # 尝试 LLM 扩展
        config = self._get_llm_config()
        if config is not None:
            try:
                llm_expanded = await self._llm_expand(query, config)
                if llm_expanded:
                    return llm_expanded
            except Exception as e:
                logger.warning(f"[QueryProcessor] LLM 查询扩展失败，降级规则扩展: {e}")

        # 规则扩展（同义词）
        return self._rule_expand(query)

    # ------------------------------------------------------------------
    # 关键词提取
    # ------------------------------------------------------------------
    def extract_keywords(self, query: str) -> List[str]:
        """关键词提取

        使用与 KeywordReranker 一致的分词策略，去除停用词。
        """
        if not query:
            return []
        try:
            from app.rag.reranker.keyword_reranker import tokenize

            tokens = tokenize(query)
        except Exception:
            # 退化：简单按空白与标点切分
            tokens = re.findall(r"[\w]+", query)
        return tokens

    # ------------------------------------------------------------------
    # 过滤条件构建
    # ------------------------------------------------------------------
    def build_filter(self, source_types: List[str]) -> dict:
        """根据 source_types 构建过滤表达式

        Returns:
            {"source_type": [...]}；无 source_types 时返回空字典
        """
        if not source_types:
            return {}
        return {"source_type": list(source_types)}

    # ------------------------------------------------------------------
    # 规则扩展（同义词）
    # ------------------------------------------------------------------
    def _rule_expand(self, query: str) -> str:
        """基于同义词表的查询扩展

        对查询中命中的术语，追加其同义表达，去重后拼接。
        """
        tokens = self.extract_keywords(query)
        if not tokens:
            return query

        extras: List[str] = []
        seen: Set[str] = {query.lower()}
        for token in tokens:
            for syn in self._get_synonyms(token):
                syn_lower = syn.lower()
                # 不重复添加，且不添加已出现在原查询中的
                if syn_lower not in seen and syn not in query:
                    extras.append(syn)
                    seen.add(syn_lower)

        if not extras:
            return query
        # 原查询 + 同义词
        return f"{query} {' '.join(extras)}"

    # ------------------------------------------------------------------
    # LLM 查询扩展
    # ------------------------------------------------------------------
    async def _llm_expand(self, query: str, config: Dict) -> str:
        """使用 LLM 对查询进行重写与扩展"""
        import httpx

        system_prompt = (
            "你是 RAG 系统的查询扩展专家，熟悉软件测试领域。"
            "请对用户查询进行扩展改写，补充同义词、相关术语与可能的表述方式，"
            "使其更利于知识库检索。保持原意，不要回答查询本身，"
            "只输出扩展后的查询文本（一段话），不要输出多余解释。"
        )
        user_prompt = (
            f"原始查询：{query}\n\n"
            "请输出扩展后的查询文本（中文，包含原词与同义词/相关术语）。"
        )

        headers = {"Content-Type": "application/json"}
        headers["Authorization"] = f"Bearer {config['api_key']}"

        body = {
            "model": config["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 256,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(config["url"], json=body, headers=headers)
            resp.raise_for_status()
            result = resp.json()

        content = result["choices"][0]["message"]["content"].strip()
        # 简单清洗：去除可能的首尾引号与多余换行
        content = content.strip("\"'` \n")
        return content
