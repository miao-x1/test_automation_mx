"""
FlowParser - 多页面业务流解析器

职责：将自然语言多步骤需求解析为页面流转图

输入：
    "打开首页 → 登录 → 进入商品 → 加入购物车"

输出：
    FlowGraph:
        pages: [首页, 登录页, 商品页, 购物车页]
        transitions: [首页→登录页, 登录页→商品页, 商品页→购物车页]
        variables: [login_username, login_password, product_name]

支持：
- 跨页面流转
- 页面状态保存
- 变量传递
"""
import json
import re
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class PageNode:
    """页面节点"""

    def __init__(self, page_id: str, title: str, url: str = "", page_type: str = "unknown"):
        self.page_id = page_id
        self.title = title
        self.url = url
        self.page_type = page_type
        self.actions: List[Dict[str, Any]] = []  # 在此页面上执行的操作
        self.state_vars: Dict[str, str] = {}  # 需要保存的状态变量

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "url": self.url,
            "page_type": self.page_type,
            "actions": self.actions,
            "state_vars": self.state_vars,
        }


class PageTransition:
    """页面跳转"""

    def __init__(
        self,
        from_page: str,
        to_page: str,
        trigger: str = "",
        trigger_locator: str = "",
        wait_strategy: str = "domcontentloaded",
    ):
        self.from_page = from_page
        self.to_page = to_page
        self.trigger = trigger  # 触发跳转的操作描述
        self.trigger_locator = trigger_locator  # 触发元素的定位器
        self.wait_strategy = wait_strategy  # 等待策略
        self.variables_out: List[str] = []  # 跳转时需要传递的变量

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_page": self.from_page,
            "to_page": self.to_page,
            "trigger": self.trigger,
            "trigger_locator": self.trigger_locator,
            "wait_strategy": self.wait_strategy,
            "variables_out": self.variables_out,
        }


class FlowGraph:
    """页面流转图"""

    def __init__(self):
        self.pages: List[PageNode] = []
        self.transitions: List[PageTransition] = []
        self.variables: Dict[str, str] = {}  # 全局变量 {name: default_value}
        self.entry_url: str = ""

    def add_page(self, page: PageNode) -> None:
        if not any(p.page_id == page.page_id for p in self.pages):
            self.pages.append(page)

    def add_transition(self, transition: PageTransition) -> None:
        self.transitions.append(transition)

    def get_page(self, page_id: str) -> Optional[PageNode]:
        for p in self.pages:
            if p.page_id == page_id:
                return p
        return None

    def get_transitions_from(self, page_id: str) -> List[PageTransition]:
        return [t for t in self.transitions if t.from_page == page_id]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pages": [p.to_dict() for p in self.pages],
            "transitions": [t.to_dict() for t in self.transitions],
            "variables": self.variables,
            "entry_url": self.entry_url,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class FlowParser(NewBaseAgent):
    """
    多页面业务流解析器

    将自然语言步骤序列解析为FlowGraph，支持：
    1. 步骤→页面映射
    2. 页面跳转推理
    3. 变量提取与传递
    4. 页面状态保存
    """

    agent_name = "flow_parser"
    display_name = "Flow Parser"
    description = "多页面业务流解析器 - 将自然语言多步骤需求解析为页面流转图"
    capabilities = [AgentCapability.FLOW_PARSE]

    # 页面类型关键词映射
    PAGE_TYPE_MAP = {
        "首页": {"page_type": "home", "url_pattern": "/$|/home|/index"},
        "登录": {"page_type": "login", "url_pattern": "/login|/signin|/auth"},
        "注册": {"page_type": "register", "url_pattern": "/register|/signup"},
        "搜索": {"page_type": "search", "url_pattern": "/search"},
        "商品": {"page_type": "product", "url_pattern": "/product|/item|/detail"},
        "购物车": {"page_type": "cart", "url_pattern": "/cart"},
        "订单": {"page_type": "order", "url_pattern": "/order|/checkout"},
        "支付": {"page_type": "payment", "url_pattern": "/pay|/payment|/checkout"},
        "个人": {"page_type": "profile", "url_pattern": "/profile|/user|/account"},
        "设置": {"page_type": "settings", "url_pattern": "/settings|/config"},
        "列表": {"page_type": "list", "url_pattern": "/list"},
        "详情": {"page_type": "detail", "url_pattern": "/detail"},
    }

    # 操作类型关键词映射
    ACTION_TYPE_MAP = {
        "打开": "goto",
        "访问": "goto",
        "进入": "navigate",
        "跳转": "navigate",
        "点击": "click",
        "选择": "select",
        "输入": "fill",
        "填写": "fill",
        "勾选": "check",
        "取消勾选": "uncheck",
        "上传": "upload",
        "下载": "download",
        "提交": "submit",
        "登录": "login",
        "注册": "register",
        "搜索": "search",
        "加入": "add",
        "添加": "add",
        "删除": "delete",
        "修改": "modify",
        "保存": "save",
        "验证": "verify",
        "检查": "verify",
        "确认": "confirm",
        "等待": "wait",
    }

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_name = "flow_parser"

    def parse(self, requirement: str, steps: List[str] = None, target_url: str = "") -> FlowGraph:
        """
        解析多步骤需求为页面流转图

        Args:
            requirement: 自然语言需求
            steps: 已解析的步骤列表（可选）
            target_url: 目标网站URL

        Returns:
            FlowGraph 页面流转图
        """
        log.info(f"FlowParser | 开始解析 | requirement={requirement[:80]}")

        # 如果没有提供steps，从requirement中提取
        if not steps:
            steps = self._extract_steps(requirement)

        graph = FlowGraph()
        graph.entry_url = target_url

        # 1. 将步骤映射到页面
        page_sequence = self._map_steps_to_pages(steps, target_url)

        # 2. 构建页面节点
        for i, page_info in enumerate(page_sequence):
            page = PageNode(
                page_id=page_info["page_id"],
                title=page_info["title"],
                url=page_info.get("url", ""),
                page_type=page_info.get("page_type", "unknown"),
            )
            page.actions = page_info.get("actions", [])
            page.state_vars = page_info.get("state_vars", {})
            graph.add_page(page)

        # 3. 构建页面跳转
        for i in range(len(page_sequence) - 1):
            current = page_sequence[i]
            next_page = page_sequence[i + 1]

            # 找到触发跳转的操作
            trigger = ""
            trigger_locator = ""
            for action in current.get("actions", []):
                if action.get("action") in ("click", "navigate", "submit", "login"):
                    trigger = action.get("description", "")
                    trigger_locator = action.get("locator", "")
                    break

            transition = PageTransition(
                from_page=current["page_id"],
                to_page=next_page["page_id"],
                trigger=trigger,
                trigger_locator=trigger_locator,
                wait_strategy="domcontentloaded",
            )

            # 传递变量
            vars_out = list(current.get("state_vars", {}).keys())
            transition.variables_out = vars_out

            graph.add_transition(transition)

        # 4. 提取全局变量
        graph.variables = self._extract_variables(steps, page_sequence)

        log.info(
            f"FlowParser | 解析完成 | "
            f"pages={len(graph.pages)}, transitions={len(graph.transitions)}, "
            f"variables={len(graph.variables)}"
        )

        return graph

    def _extract_steps(self, requirement: str) -> List[str]:
        """从需求文本中提取步骤"""
        # 尝试按分隔符拆分
        separators = ["→", "->", "=>", "，然后", "，接着", "，再", "；", "\n"]
        steps = [requirement]

        for sep in separators:
            if sep in requirement:
                parts = [s.strip() for s in requirement.split(sep) if s.strip()]
                if len(parts) > 1:
                    steps = parts
                    break

        return steps

    def _map_steps_to_pages(self, steps: List[str], target_url: str) -> List[Dict[str, Any]]:
        """将步骤映射到页面序列"""
        pages = []
        current_page_id = None
        page_counter = 0

        for i, step in enumerate(steps):
            step = step.strip()
            if not step:
                continue

            # 判断此步骤是否触发页面跳转
            page_info = self._infer_page_for_step(step, page_counter, target_url)

            if page_info["page_id"] != current_page_id:
                # 新页面
                current_page_id = page_info["page_id"]
                page_counter += 1
                page_info["actions"] = [self._step_to_action(step, i)]
                page_info["state_vars"] = self._extract_step_variables(step)
                pages.append(page_info)
            else:
                # 同一页面的额外操作
                if pages:
                    pages[-1]["actions"].append(self._step_to_action(step, i))
                    pages[-1]["state_vars"].update(self._extract_step_variables(step))

        return pages

    def _infer_page_for_step(self, step: str, page_counter: int, target_url: str) -> Dict[str, Any]:
        """推理步骤所属的页面"""
        step_lower = step.lower()

        # 匹配页面类型
        for keyword, config in self.PAGE_TYPE_MAP.items():
            if keyword in step:
                page_id = f"page_{config['page_type']}_{page_counter}"
                return {
                    "page_id": page_id,
                    "title": f"{keyword}页",
                    "url": "",
                    "page_type": config["page_type"],
                }

        # 默认：根据步骤序号生成页面
        page_id = f"page_{page_counter}"
        return {
            "page_id": page_id,
            "title": f"页面{page_counter + 1}",
            "url": "",
            "page_type": "unknown",
        }

    def _step_to_action(self, step: str, step_index: int) -> Dict[str, Any]:
        """将步骤转换为操作"""
        action_type = "click"  # 默认
        for keyword, atype in self.ACTION_TYPE_MAP.items():
            if keyword in step:
                action_type = atype
                break

        return {
            "step_index": step_index,
            "description": step,
            "action": action_type,
            "locator": "",
            "value": self._extract_action_value(step),
            "target": "",
        }

    def _extract_action_value(self, step: str) -> str:
        """提取操作值（如输入框的值）"""
        # 匹配引号内的值
        patterns = [
            r'[""「」『』](.+?)[""「」『』]',  # 中文引号
            r'"(.+?)"',  # 英文引号
            r"'(.+?)'",  # 单引号
        ]
        for pattern in patterns:
            match = re.search(pattern, step)
            if match:
                return match.group(1)

        # 匹配"输入XXX"格式
        match = re.search(r'(?:输入|填写|搜索)(.+?)(?:$|，|,|然后|接着)', step)
        if match:
            return match.group(1).strip()

        return ""

    def _extract_step_variables(self, step: str) -> Dict[str, str]:
        """提取步骤中的变量"""
        variables = {}

        # 常见变量模式
        var_patterns = {
            "username": r'(?:用户名|账号|邮箱|手机号)',
            "password": r'(?:密码|口令)',
            "product_name": r'(?:商品|产品|物品)\s*(?:名|名称)?',
            "search_keyword": r'(?:搜索|查询|关键词)\s*(?:词)?',
            "price": r'(?:价格|金额|费用)',
            "quantity": r'(?:数量|个数|件数)',
        }

        for var_name, pattern in var_patterns.items():
            if re.search(pattern, step):
                variables[var_name] = f"${{{var_name}}}"

        return variables

    def _extract_variables(self, steps: List[str], page_sequence: List[Dict]) -> Dict[str, str]:
        """提取全局变量"""
        variables = {}

        # 从所有页面收集变量
        for page in page_sequence:
            for var_name, var_value in page.get("state_vars", {}).items():
                if var_name not in variables:
                    # 设置默认值
                    default_values = {
                        "username": "test_user",
                        "password": "Test@123456",
                        "product_name": "测试商品",
                        "search_keyword": "测试搜索",
                        "price": "0",
                        "quantity": "1",
                    }
                    variables[var_name] = default_values.get(var_name, var_value)

        return variables

    def enhance_with_graph(self, graph: FlowGraph, graph_result: Dict[str, Any]) -> FlowGraph:
        """
        使用Graph推理结果增强FlowGraph

        补充页面URL、元素定位器、跳转触发器等信息
        """
        graph_pages = graph_result.get("pages", [])
        graph_elements = graph_result.get("elements", [])
        graph_flows = graph_result.get("business_flow", [])

        # 匹配Graph页面到FlowGraph页面
        for page in graph.pages:
            # 按页面类型匹配
            for gp in graph_pages:
                gp_type = gp.get("page_type", "")
                if gp_type == page.page_type or self._page_type_match(page.title, gp.get("title", "")):
                    if not page.url and gp.get("url"):
                        page.url = gp["url"]
                    break

            # 匹配元素到操作
            page_elements = [
                e for e in graph_elements
                if e.get("page_id") == page.page_id or self._element_match_page(e, page)
            ]
            for action in page.actions:
                if not action.get("locator"):
                    action["locator"] = self._find_locator_for_action(action, page_elements)

        # 匹配跳转触发器
        for transition in graph.transitions:
            if not transition.trigger_locator:
                from_page = graph.get_page(transition.from_page)
                if from_page:
                    for flow in graph_flows:
                        nav_targets = flow.get("navigation_targets", [])
                        for nav in nav_targets:
                            if self._page_type_match(
                                transition.to_page.split("_")[1] if "_" in transition.to_page else "",
                                nav.get("target_page_title", ""),
                            ):
                                transition.trigger = nav.get("trigger_element", transition.trigger)
                                # 找到触发元素的定位器
                                for elem in graph_elements:
                                    if elem.get("name") == nav.get("trigger_element"):
                                        transition.trigger_locator = elem.get("locator", "")
                                        break
                                break

        # 如果entry_url为空，尝试从Graph获取
        if not graph.entry_url and graph_pages:
            home_page = next((p for p in graph_pages if p.get("page_type") == "home"), None)
            if home_page:
                graph.entry_url = home_page.get("url", "")
            elif graph_pages:
                graph.entry_url = graph_pages[0].get("url", "")

        return graph

    def _page_type_match(self, title1: str, title2: str) -> bool:
        """判断两个页面标题是否匹配"""
        if not title1 or not title2:
            return False
        t1 = title1.lower().replace("页", "")
        t2 = title2.lower().replace("页", "")
        return t1 in t2 or t2 in t1

    def _element_match_page(self, element: Dict, page: PageNode) -> bool:
        """判断元素是否属于某页面"""
        elem_page_title = element.get("page_title", "")
        return self._page_type_match(page.title, elem_page_title)

    def _find_locator_for_action(self, action: Dict, elements: List[Dict]) -> str:
        """为操作查找元素定位器"""
        action_desc = action.get("description", "").lower()
        action_type = action.get("action", "")

        for elem in elements:
            elem_name = (elem.get("name", "") or elem.get("element_name", "")).lower()
            elem_type = (elem.get("type", "") or elem.get("element_type", "")).lower()

            # 按操作类型匹配元素
            if action_type == "fill" and elem_type in ("input", "searchbox", "textarea"):
                if any(kw in elem_name for kw in action_desc.split()):
                    return elem.get("locator", "")

            if action_type == "click" and elem_type in ("button", "link"):
                if any(kw in elem_name for kw in action_desc.split()):
                    return elem.get("locator", "")

            if action_type == "select" and elem_type == "select":
                if any(kw in elem_name for kw in action_desc.split()):
                    return elem.get("locator", "")

        return ""
