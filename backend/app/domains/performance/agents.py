"""
性能测试 Agent 实现

四个 Agent:
  1. PerformancePlanAgent       — 输入: 接口+业务量 → 输出: 并发/持续时间/TPS目标
  2. PerformanceScriptAgent     — 输入: 测试方案 → 输出: Locust脚本/JMeter配置
  3. PerformanceAnalysisAgent   — 输入: 实时指标 → 输出: LLM分析结论
  4. PerformanceDiagnosticAgent — 输入: jstack/日志/监控数据 → 输出: 问题定位

设计约束:
  - 不使用 RAG 分析实时性能数据
  - 实时指标 + LLM 直接分析
  - Agent 从 ApplicationContainer 获取 LLM Gateway
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.runtime.base_agent import BaseRoutedAgent, action_handler

logger = logging.getLogger(__name__)


# ================================================================
# PerformancePlanAgent — 生成性能测试方案
# ================================================================

class PerformancePlanAgent(BaseRoutedAgent):
    """性能测试方案 Agent

    输入:
        - target_url:    目标接口 URL
        - method:        HTTP 方法
        - business_volume: 预期日业务量 (次/天)
        - headers:       请求头
        - body:          请求体

    输出:
        - concurrency:     并发用户数
        - duration_seconds: 持续时间 (秒)
        - tps_target:       目标 TPS
        - ramp_up:          预热时间
        - scenarios:        测试场景列表
    """

    SYSTEM_PROMPT = """你是一位资深的性能测试工程师。
根据用户提供的接口信息和业务量数据，制定性能测试方案。

输出 JSON 格式:
{
  "concurrency": <并发用户数>,
  "duration_seconds": <持续时间秒数>,
  "tps_target": <目标TPS>,
  "ramp_up": <预热时间秒数>,
  "scenarios": [
    {"name": "基准测试", "description": "...", "weight": 100}
  ],
  "reasoning": "方案制定依据"
}

规则:
1. 并发用户数 = 日业务量 / 86400 * 峰值因子(3-5) * 安全系数(1.5)
2. 持续时间: 小规模测试 60s, 中规模 180s, 大规模 600s
3. TPS目标 = 并发数 / 期望平均RT(秒)
4. 预热时间 = 并发数的 1/3 或 10s 取大值"""

    def __init__(self) -> None:
        super().__init__(
            description="性能测试方案Agent, 根据接口和业务量生成并发/持续时间/TPS目标",
            display_name="PerformancePlanAgent",
            capabilities=["performance_planning", "concurrency_estimation"],
        )

    @action_handler("plan")
    async def handle_plan(self, payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """生成性能测试方案"""
        target_url = payload.get("target_url", "")
        method = payload.get("method", "GET")
        business_volume = payload.get("business_volume", 10000)
        headers = payload.get("headers", {})
        body = payload.get("body", {})
        test_type = payload.get("test_type", "api")

        # 基于业务量的初步估算 (不依赖 LLM, 作为基准)
        base_concurrency = max(1, int(business_volume / 86400 * 4 * 1.5))
        base_concurrency = min(max(base_concurrency, 5), 500)

        # 调用 LLM 生成优化方案
        user_prompt = json.dumps({
            "target_url": target_url,
            "method": method,
            "business_volume_per_day": business_volume,
            "headers": headers,
            "body": body,
            "test_type": test_type,
            "base_concurrency_estimate": base_concurrency,
        }, ensure_ascii=False, indent=2)

        try:
            result = await self.call_llm_json(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=2048,
            )

            plan = {
                "concurrency": result.get("concurrency", base_concurrency),
                "duration_seconds": result.get("duration_seconds", 60),
                "tps_target": result.get("tps_target", float(base_concurrency)),
                "ramp_up": result.get("ramp_up", 10),
                "scenarios": result.get("scenarios", []),
                "reasoning": result.get("reasoning", ""),
            }
        except Exception as e:
            logger.warning(f"PerformancePlanAgent LLM 调用失败, 使用基准估算: {e}")
            plan = {
                "concurrency": base_concurrency,
                "duration_seconds": 60 if base_concurrency < 50 else 180,
                "tps_target": float(base_concurrency),
                "ramp_up": max(10, base_concurrency // 3),
                "scenarios": [{"name": "基准测试", "description": "常规负载测试", "weight": 100}],
                "reasoning": f"基准估算 (LLM不可用): 并发={base_concurrency}, 基于日业务量{business_volume}",
            }

        logger.info(f"[PerformancePlanAgent] 方案生成完成: 并发={plan['concurrency']}, TPS目标={plan['tps_target']}")
        return {"status": "success", "plan": plan}


# ================================================================
# PerformanceScriptAgent — 生成 Locust/JMeter 脚本
# ================================================================

class PerformanceScriptAgent(BaseRoutedAgent):
    """性能测试脚本 Agent

    输入:
        - plan:           PerformancePlanAgent 输出
        - target_url:     目标 URL
        - method:         HTTP 方法
        - headers:        请求头
        - body:           请求体
        - script_type:    locust / jmeter
        - test_type:      api / web (决定脚本生成策略)

    输出:
        - script_content:  脚本内容
        - script_format:   locust | jmeter_xml
        - jmeter_config:   JMeter XML 配置 (当 script_type=jmeter)
    """

    SYSTEM_PROMPT = """你是一位 Locust 性能测试脚本专家。
根据测试方案和接口信息，生成可运行的 Locust Python 脚本。

要求:
1. 继承 HttpUser 类
2. 使用 @task 装饰器定义测试任务
3. 设置 wait_time
4. 包含请求头和请求体
5. 包含响应验证
6. 代码完整可直接运行

只输出 Python 代码,不要 markdown 包裹。"""

    WEB_SYSTEM_PROMPT = """你是一位 Web 性能测试脚本专家。
根据测试方案和页面信息，生成模拟真实用户浏览行为的 Locust Python 脚本。

要求:
1. 继承 HttpUser 类
2. 使用 @task 装饰器定义多个页面访问任务 (首页、列表页、详情页等)
3. 模拟真实用户浏览路径: 首页 → 列表 → 详情 → 提交表单
4. 设置 wait_time 模拟用户思考时间 (between(2, 5))
5. 包含页面资源加载验证 (检查 status_code 和关键内容)
6. 使用 @task(weight) 控制不同页面的访问比例
7. 使用 catch_response=True 进行自定义成功/失败判断
8. 代码完整可直接运行

只输出 Python 代码,不要 markdown 包裹。"""

    JMETER_PROMPT = """你是一位 JMeter 测试脚本专家。
根据测试方案和接口信息，生成可导入 JMeter 的 XML 配置。

要求:
1. 标准 JMeter TestPlan XML 格式
2. 包含 ThreadGroup (并发数、循环次数、预热)
3. 包含 HTTPSampler (URL、方法、 headers、body)
4. 包含结果收集器

只输出 XML 代码,不要 markdown 包裹。"""

    def __init__(self) -> None:
        super().__init__(
            description="性能测试脚本Agent, 生成 Locust 脚本和 JMeter 配置 (支持 API/Web)",
            display_name="PerformanceScriptAgent",
            capabilities=["script_generation", "locust", "jmeter", "web_performance"],
        )

    @action_handler("generate")
    async def handle_generate(self, payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """生成性能测试脚本

        根据 test_type 和 script_type 选择生成策略:
          - test_type=api  + script_type=locust  → API Locust 脚本
          - test_type=web  + script_type=locust  → Web 浏览模拟 Locust 脚本
          - test_type=api  + script_type=jmeter  → JMeter XML 配置
          - test_type=web  + script_type=jmeter  → JMeter XML 配置 (含多页面)
        """
        plan = payload.get("plan", {})
        target_url = payload.get("target_url", "")
        method = payload.get("method", "GET")
        headers = payload.get("headers", {})
        body = payload.get("body", {})
        script_type = payload.get("script_type", "locust")
        test_type = payload.get("test_type", "api")

        concurrency = plan.get("concurrency", 10)
        duration = plan.get("duration_seconds", 60)
        ramp_up = plan.get("ramp_up", 10)
        tps_target = plan.get("tps_target", 0)

        if script_type == "jmeter":
            return await self._generate_jmeter(
                target_url, method, headers, body,
                concurrency, duration, ramp_up,
            )
        elif test_type == "web":
            return await self._generate_web_locust(
                target_url, method, headers, body,
                concurrency, duration, ramp_up, tps_target,
            )
        else:
            return await self._generate_locust(
                target_url, method, headers, body,
                concurrency, duration, ramp_up, tps_target,
            )

    async def _generate_locust(
        self, url: str, method: str, headers: Dict, body: Any,
        concurrency: int, duration: int, ramp_up: int, tps_target: float,
    ) -> Dict[str, Any]:
        """生成 Locust 脚本"""
        # 解析 URL
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"

        # 优先使用 LLM 生成, 降级到模板
        user_prompt = json.dumps({
            "host": host,
            "path": path,
            "method": method,
            "headers": headers,
            "body": body,
            "concurrency": concurrency,
            "duration_seconds": duration,
            "ramp_up": ramp_up,
            "tps_target": tps_target,
        }, ensure_ascii=False, indent=2)

        try:
            script = await self.call_llm(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            # 清理 markdown 包裹
            script = script.strip()
            if script.startswith("```"):
                lines = script.split("\n")
                script = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        except Exception as e:
            logger.warning(f"PerformanceScriptAgent LLM 调用失败, 使用模板: {e}")
            script = self._locust_template(
                host, path, method, headers, body,
                concurrency, duration, ramp_up,
            )

        return {
            "status": "success",
            "script_content": script,
            "script_format": "locust",
        }

    def _locust_template(
        self, host: str, path: str, method: str,
        headers: Dict, body: Any, concurrency: int, duration: int, ramp_up: int,
    ) -> str:
        """Locust 脚本模板 (降级方案)"""
        headers_str = json.dumps(headers, ensure_ascii=False, indent=8)
        body_str = json.dumps(body, ensure_ascii=False) if body else "None"
        method_lower = method.lower()

        return f'''"""Locust 性能测试脚本 — 自动生成"""
from locust import HttpUser, task, between
import json

HEADERS = {headers_str}
BODY = {body_str}


class PerformanceTestUser(HttpUser):
    """性能测试用户 — 并发{concurrency}, 持续{duration}秒, 预热{ramp_up}秒"""
    host = "{host}"
    wait_time = between(1, 3)

    @task
    def test_api(self):
        """测试接口: {method} {path}"""
        with self.client.{method_lower}(
            "{path}",
            headers=HEADERS,
            json=BODY if BODY else None,
            catch_response=True,
        ) as response:
            if response.status_code < 400:
                response.success()
            else:
                response.failure(f"HTTP {{response.status_code}}")
'''

    async def _generate_web_locust(
        self, url: str, method: str, headers: Dict, body: Any,
        concurrency: int, duration: int, ramp_up: int, tps_target: float,
    ) -> Dict[str, Any]:
        """生成 Web 性能测试 Locust 脚本 (模拟真实用户浏览行为)"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"

        user_prompt = json.dumps({
            "host": host,
            "entry_path": path,
            "method": method,
            "headers": headers,
            "body": body,
            "concurrency": concurrency,
            "duration_seconds": duration,
            "ramp_up": ramp_up,
            "tps_target": tps_target,
            "test_type": "web",
        }, ensure_ascii=False, indent=2)

        try:
            script = await self.call_llm(
                system_prompt=self.WEB_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )
            script = script.strip()
            if script.startswith("```"):
                lines = script.split("\n")
                script = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        except Exception as e:
            logger.warning(f"PerformanceScriptAgent Web LLM 调用失败, 使用模板: {e}")
            script = self._web_locust_template(host, path, headers, concurrency, duration, ramp_up)

        return {
            "status": "success",
            "script_content": script,
            "script_format": "locust",
        }

    def _web_locust_template(
        self, host: str, path: str, headers: Dict,
        concurrency: int, duration: int, ramp_up: int,
    ) -> str:
        """Web 性能测试 Locust 脚本模板 (降级方案)"""
        headers_str = json.dumps(headers, ensure_ascii=False, indent=8) if headers else "{}"

        return f'''"""Locust Web 性能测试脚本 — 自动生成 (模拟真实用户浏览)"""
from locust import HttpUser, task, between
import random

HEADERS = {headers_str}


class WebBrowsingUser(HttpUser):
    """Web 性能测试用户 — 并发{concurrency}, 持续{duration}秒, 预热{ramp_up}秒

    模拟真实用户浏览路径:
      首页 → 列表页 → 详情页 → 返回 → 随机浏览
    """
    host = "{host}"
    wait_time = between(2, 5)  # 模拟用户思考时间

    def on_start(self):
        """用户启动时访问首页"""
        self.client.get("/", headers=HEADERS)

    @task(3)
    def visit_homepage(self):
        """访问首页 (权重 3)"""
        with self.client.get("/", headers=HEADERS, catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"首页返回 {{resp.status_code}}")

    @task(5)
    def browse_list(self):
        """浏览列表页 (权重 5)"""
        list_paths = ["/list", "/products", "/articles", "/api/items"]
        target = random.choice(list_paths)
        with self.client.get(target, headers=HEADERS, catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 404:
                resp.failure(f"列表页 {{target}} 不存在")
            else:
                resp.failure(f"列表页 {{target}} 返回 {{resp.status_code}}")

    @task(4)
    def view_detail(self):
        """查看详情页 (权重 4)"""
        detail_id = random.randint(1, 1000)
        detail_paths = [f"/detail/{{detail_id}}", f"/product/{{detail_id}}", f"/article/{{detail_id}}"]
        target = random.choice(detail_paths)
        with self.client.get(target, headers=HEADERS, catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 404:
                resp.failure(f"详情页 {{target}} 不存在")
            else:
                resp.failure(f"详情页 {{target}} 返回 {{resp.status_code}}")

    @task(2)
    def search(self):
        """搜索功能 (权重 2)"""
        keywords = ["test", "performance", "load", "api", "web"]
        keyword = random.choice(keywords)
        with self.client.get(
            f"/search?q={{keyword}}", headers=HEADERS, catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"搜索返回 {{resp.status_code}}")

    @task(1)
    def submit_form(self):
        """提交表单 (权重 1)"""
        with self.client.post(
            "{path}",
            headers=HEADERS,
            json={{"query": "load_test"}},
            catch_response=True,
        ) as resp:
            if resp.status_code < 400:
                resp.success()
            else:
                resp.failure(f"表单提交返回 {{resp.status_code}}")
'''

    async def _generate_jmeter(
        self, url: str, method: str, headers: Dict, body: Any,
        concurrency: int, duration: int, ramp_up: int,
    ) -> Dict[str, Any]:
        """生成 JMeter XML 配置"""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        scheme = parsed.scheme or "http"

        # 使用模板生成 JMeter XML
        xml = self._jmeter_template(
            host, port, scheme, path, method, headers, body,
            concurrency, duration, ramp_up,
        )

        return {
            "status": "success",
            "script_content": xml,
            "script_format": "jmeter_xml",
            "jmeter_config": xml,
        }

    def _jmeter_template(
        self, host: str, port: int, scheme: str, path: str,
        method: str, headers: Dict, body: Any,
        concurrency: int, duration: int, ramp_up: int,
    ) -> str:
        """JMeter XML 模板"""
        header_entries = "\n".join(
            f'            <HeaderManager guiclass="HeaderPanel" testclass="HeaderManager" testname="HTTP Header Manager">'
            f'<collectionProp name="HeaderManager.headers">'
            f'<elementProp name="{k}" elementType="Header">'
            f'<stringProp name="Header.name">{k}</stringProp>'
            f'<stringProp name="Header.value">{v}</stringProp>'
            f'</elementProp>'
            for k, v in (headers or {}).items()
        ) if headers else ""

        body_data = json.dumps(body) if body else ""

        return f'''<?xml version="1.0" encoding="UTF-8"?>
<jmeterTestPlan version="1.2" properties="5.0">
  <hashTree>
    <TestPlan guiclass="TestPlanGui" testclass="TestPlan" testname="性能测试计划" enabled="true">
      <stringProp name="TestPlan.comments">并发{concurrency}, 持续{duration}秒</stringProp>
      <boolProp name="TestPlan.functional_mode">false</boolProp>
    </TestPlan>
    <hashTree>
      <ThreadGroup guiclass="ThreadGroupGui" testclass="ThreadGroup" testname="用户组" enabled="true">
        <intProp name="ThreadGroup.num_threads">{concurrency}</intProp>
        <intProp name="ThreadGroup.ramp_time">{ramp_up}</intProp>
        <stringProp name="ThreadGroup.duration">{duration}</stringProp>
        <stringProp name="ThreadGroup.on_sample_error">continue</stringProp>
        <boolProp name="ThreadGroup.scheduler">true</boolProp>
      </ThreadGroup>
      <hashTree>
        <HTTPSamplerProxy guiclass="HttpTestSampleGui" testclass="HTTPSamplerProxy" testname="HTTP请求" enabled="true">
          <stringProp name="HTTPSampler.domain">{host}</stringProp>
          <stringProp name="HTTPSampler.port">{port}</stringProp>
          <stringProp name="HTTPSampler.protocol">{scheme}</stringProp>
          <stringProp name="HTTPSampler.path">{path}</stringProp>
          <stringProp name="HTTPSampler.method">{method}</stringProp>
          <boolProp name="HTTPSampler.use_keepalive">true</boolProp>
          <stringProp name="HTTPSampler.postBodyRawData">{body_data}</stringProp>
        </HTTPSamplerProxy>
        <hashTree/>
      </hashTree>
    </hashTree>
  </hashTree>
</jmeterTestPlan>'''


# ================================================================
# PerformanceAnalysisAgent — 分析实时性能指标
# ================================================================

class PerformanceAnalysisAgent(BaseRoutedAgent):
    """性能测试分析 Agent

    输入:
        - result_summary: 结果汇总 (TPS/RT/错误率等)
        - metrics:        实时指标列表 (按时间切片)
        - target_plan:    目标方案 (用于对比)
        - logs:           应用日志列表 (可选, 用于日志分析)

    输出:
        - analysis:       LLM 分析结论
        - bottlenecks:    瓶颈点
        - recommendations: 优化建议
        - score:          性能评分

    设计约束:
        - 不使用 RAG 分析实时性能数据
        - 使用实时指标 + 日志 + LLM 直接分析
    """

    SYSTEM_PROMPT = """你是一位资深的性能测试分析专家。
根据实时性能指标数据和应用日志，分析系统性能状况并给出专业结论。

分析维度:
1. TPS 分析: 是否达到目标, 波动情况, 趋势
2. 响应时间分析: P50/P90/P95/P99, 是否达标
3. 错误率分析: 错误类型, 错误趋势, 根因推测
4. 资源分析: CPU/内存使用趋势 (如有)
5. 日志分析: 从应用日志中识别异常、警告、错误堆栈, 关联性能指标变化
6. 瓶颈识别: CPU密集/IO密集/网络/连接池/数据库/日志异常等
7. 优化建议: 具体可操作的建议

输出 JSON:
{
  "summary": "整体评价 (1-2句)",
  "score": <0-100>,
  "tps_analysis": "TPS分析结论",
  "rt_analysis": "响应时间分析结论",
  "error_analysis": "错误分析结论",
  "resource_analysis": "资源分析结论",
  "log_analysis": "日志分析结论 (从日志中发现的异常和线索)",
  "bottlenecks": ["瓶颈1", "瓶颈2"],
  "recommendations": ["建议1", "建议2"],
  "verdict": "PASS/FAIL/CONDITIONAL"
}"""

    BROWSER_SYSTEM_PROMPT = """你是一位资深的Web前端性能分析专家。
根据浏览器性能采集数据 (Chrome DevTools Protocol), 分析页面性能状况。

分析维度:
1. 页面加载: DNS/TCP/SSL/TTFB/DOM解析/加载完成各阶段耗时是否正常
2. Core Web Vitals: FCP(首次内容绘制)/LCP(最大内容绘制)/CLS(布局偏移) 是否达标
3. 网络性能: 请求总数/资源大小/按类型分组/缓存命中率/失败请求
4. JS执行: 长任务数量/总阻塞时间/布局重计算/样式重计算
5. DOM复杂度: 节点数量/树深度/JS堆内存
6. 瓶颈识别: 慢请求/大资源/渲染阻塞/过多DOM/长任务等
7. 优化建议: 具体可操作的前端优化建议

Web Vitals 达标标准:
- FCP < 1800ms (良好) / < 3000ms (需改进)
- LCP < 2500ms (良好) / < 4000ms (需改进)
- CLS < 0.1 (良好) / < 0.25 (需改进)
- TBT < 200ms (良好) / < 600ms (需改进)

输出 JSON:
{
  "summary": "整体评价 (1-2句)",
  "score": <0-100>,
  "page_load_analysis": "页面加载分析结论",
  "web_vitals_analysis": "Core Web Vitals 分析结论",
  "network_analysis": "网络性能分析结论",
  "js_analysis": "JS执行分析结论",
  "bottlenecks": ["瓶颈1", "瓶颈2"],
  "recommendations": ["建议1", "建议2"],
  "verdict": "PASS/FAIL/CONDITIONAL"
}"""

    def __init__(self) -> None:
        super().__init__(
            description="性能测试分析Agent, 基于实时指标+日志+LLM分析TPS/RT/CPU/Memory",
            display_name="PerformanceAnalysisAgent",
            capabilities=["performance_analysis", "bottleneck_detection", "log_analysis"],
        )

    @action_handler("analyze")
    async def handle_analyze(self, payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """分析性能测试结果

        使用实时指标 + 日志 + LLM 直接分析, 不使用 RAG。
        """
        result_summary = payload.get("result_summary", {})
        metrics = payload.get("metrics", [])
        target_plan = payload.get("target_plan", {})
        logs = payload.get("logs", [])

        # 基于实时指标的统计分析 (不依赖 LLM)
        stats = self._compute_statistics(result_summary, metrics, target_plan, logs)

        # 使用 LLM 进行深度分析 (实时指标 + 日志 + LLM, 不使用 RAG)
        user_prompt = self._build_analysis_prompt(stats, metrics, target_plan, logs)

        try:
            analysis = await self.call_llm_json(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
            )
        except Exception as e:
            logger.warning(f"PerformanceAnalysisAgent LLM 调用失败, 使用统计分析: {e}")
            analysis = self._fallback_analysis(stats, logs)

        # 如果检测到性能问题, 自动调用诊断 Agent 进行深度问题定位
        diagnosis = None
        verdict = analysis.get("verdict", "PASS") if isinstance(analysis, dict) else "PASS"
        if verdict in ("FAIL", "CONDITIONAL") or stats.get("error_rate_pct", 0) > 5:
            diagnosis = await self._run_diagnosis(stats, metrics, logs, payload)

        return {
            "status": "success",
            "analysis": analysis,
            "statistics": stats,
            "diagnosis": diagnosis,
        }

    async def _run_diagnosis(
        self,
        stats: Dict[str, Any],
        metrics: List[Dict[str, Any]],
        logs: List[Any],
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """调用 PerformanceDiagnosticAgent 进行深度问题定位

        当性能分析发现 FAIL/CONDITIONAL 或错误率 > 5% 时自动触发。
        通过 send_request 调用诊断 Agent (遵守域模块间通信规则)。
        """
        try:
            # 构建监控数据 (从统计指标转换)
            monitoring_data = {
                "avg_tps": stats.get("avg_tps", 0),
                "peak_tps": stats.get("peak_tps", 0),
                "avg_rt": stats.get("avg_rt_ms", 0),
                "p95_rt": stats.get("p95_rt_ms", 0),
                "p99_rt": stats.get("p99_rt_ms", 0),
                "error_rate": stats.get("error_rate_pct", 0),
                "cpu_peak_pct": stats.get("cpu_peak_pct"),
                "mem_peak_mb": stats.get("mem_peak_mb"),
                "metrics": metrics,
            }

            # 通过 send_request 调用诊断 Agent
            response = await self.send_request(
                target_agent_type="PerformanceDiagnosticAgent",
                action="diagnose",
                payload={
                    "jstack_dump": payload.get("jstack_dump", ""),
                    "logs": logs,
                    "monitoring_data": monitoring_data,
                },
            )

            if response and response.success:
                return response.data

        except Exception as e:
            logger.warning(f"PerformanceAnalysisAgent 调用诊断Agent失败: {e}")

        return None

    @action_handler("browser_analyze")
    async def handle_browser_analyze(self, payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """分析浏览器性能数据 (来自 CDP 采集器)

        输入:
            - browser_report: CDP 采集器输出的完整性能报告 (dict)
            - url: 目标页面 URL (可选, 从 report 中提取)

        流程:
            1. 从 browser_report 提取 page/network/js 指标
            2. 调用 LLM 使用 BROWSER_SYSTEM_PROMPT 进行前端性能分析
            3. 降级到规则分析 (LLM 不可用时)
        """
        report = payload.get("browser_report", {})
        url = payload.get("url", report.get("page", {}).get("url", ""))

        page = report.get("page", {})
        network = report.get("network", {})
        js = report.get("js", {})

        # 构建浏览器性能分析 prompt
        user_prompt = self._build_browser_prompt(page, network, js, url)

        try:
            analysis = await self.call_llm_json(
                system_prompt=self.BROWSER_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
            )
        except Exception as e:
            logger.warning(f"PerformanceAnalysisAgent browser_analyze LLM 调用失败, 使用规则分析: {e}")
            analysis = self._fallback_browser_analysis(page, network, js)

        return {
            "status": "success",
            "analysis": analysis,
            "url": url,
        }

    def _build_browser_prompt(
        self, page: Dict[str, Any], network: Dict[str, Any],
        js: Dict[str, Any], url: str,
    ) -> str:
        """构建浏览器性能 LLM 分析 prompt"""
        return json.dumps({
            "url": url,
            "page_metrics": {
                "dns_lookup_ms": page.get("dns_lookup_ms", 0),
                "tcp_connect_ms": page.get("tcp_connect_ms", 0),
                "ssl_handshake_ms": page.get("ssl_handshake_ms", 0),
                "ttfb_ms": page.get("ttfb_ms", 0),
                "dom_parse_ms": page.get("dom_parse_ms", 0),
                "dom_ready_ms": page.get("dom_ready_ms", 0),
                "load_complete_ms": page.get("load_complete_ms", 0),
                "fcp_ms": page.get("fcp_ms", 0),
                "lcp_ms": page.get("lcp_ms", 0),
                "cls": page.get("cls", 0),
                "dom_nodes": page.get("dom_nodes", 0),
                "dom_depth": page.get("dom_depth", 0),
                "js_heap_mb": page.get("js_heap_mb", 0),
            },
            "network_metrics": {
                "total_requests": network.get("total_requests", 0),
                "total_size_mb": network.get("total_size_mb", 0),
                "by_resource_type": network.get("by_resource_type", {}),
                "by_status": network.get("by_status", {}),
                "cache_hit_rate": network.get("cache_hit_rate", 0),
                "avg_duration_ms": network.get("avg_duration_ms", 0),
                "failed_requests_count": len(network.get("failed_requests", [])),
                "slowest_top5": network.get("slowest_requests", [])[:5],
                "largest_top5": network.get("largest_requests", [])[:5],
            },
            "js_metrics": {
                "long_tasks_count": js.get("long_tasks_count", 0),
                "long_tasks_total_ms": js.get("long_tasks_total_ms", 0),
                "longest_task_ms": js.get("longest_task_ms", 0),
                "tbt_ms": js.get("tbt_ms", 0),
                "layout_recalc_count": js.get("layout_recalc_count", 0),
                "style_recalc_count": js.get("style_recalc_count", 0),
            },
        }, ensure_ascii=False, indent=2)

    def _fallback_browser_analysis(
        self, page: Dict, network: Dict, js: Dict,
    ) -> Dict[str, Any]:
        """浏览器性能降级分析 (LLM 不可用时, 基于规则)"""
        problems: List[str] = []
        recs: List[str] = []
        score = 100

        # 页面加载时间
        load_time = page.get("load_complete_ms", 0)
        if load_time > 5000:
            score -= 25
            problems.append(f"页面加载时间过长: {load_time:.0f}ms (建议<3000ms)")
            recs.append("优化服务端响应、减少渲染阻塞资源、使用CDN加速")
        elif load_time > 3000:
            score -= 10
            problems.append(f"页面加载时间偏慢: {load_time:.0f}ms")

        # TTFB
        ttfb = page.get("ttfb_ms", 0)
        if ttfb > 1000:
            score -= 15
            problems.append(f"TTFB过高: {ttfb:.0f}ms (建议<600ms)")
            recs.append("优化服务端响应时间: 使用CDN、启用缓存、优化数据库查询")

        # LCP
        lcp = page.get("lcp_ms", 0)
        if lcp > 4000:
            score -= 20
            problems.append(f"LCP过慢: {lcp:.0f}ms (建议<2500ms)")
            recs.append("优化LCP: 压缩首屏图片、预加载关键资源、减少渲染阻塞资源")
        elif lcp > 2500:
            score -= 10
            problems.append(f"LCP偏慢: {lcp:.0f}ms")

        # CLS
        cls = page.get("cls", 0)
        if cls > 0.25:
            score -= 15
            problems.append(f"CLS严重: {cls} (建议<0.1)")
            recs.append("优化CLS: 为图片/视频设置尺寸属性、避免动态插入内容")
        elif cls > 0.1:
            score -= 5

        # DOM 数量
        dom_nodes = page.get("dom_nodes", 0)
        if dom_nodes > 2000:
            score -= 15
            problems.append(f"DOM节点过多: {dom_nodes} (建议<1500)")
            recs.append("精简DOM结构: 减少嵌套、使用虚拟滚动、延迟渲染非可视内容")
        elif dom_nodes > 1500:
            score -= 5

        # 网络请求
        total_req = network.get("total_requests", 0)
        if total_req > 100:
            score -= 10
            problems.append(f"网络请求过多: {total_req} (建议<80)")
            recs.append("减少网络请求: 合并CSS/JS文件、使用雪碧图、内联关键资源")

        total_size_mb = network.get("total_size_mb", 0)
        if total_size_mb > 5:
            score -= 15
            problems.append(f"资源总大小过大: {total_size_mb}MB (建议<3MB)")
            recs.append("减小资源体积: 启用Gzip/Brotli压缩、压缩图片、使用WebP格式")
        elif total_size_mb > 3:
            score -= 5

        failed = network.get("failed_requests", [])
        if failed:
            score -= 10
            problems.append(f"失败请求: {len(failed)}个")

        # 长任务
        long_tasks = js.get("long_tasks_count", 0)
        if long_tasks > 10:
            score -= 15
            problems.append(f"长任务过多: {long_tasks}个 (建议<5)")
            recs.append("优化长任务: 拆分大块JS执行、使用requestIdleCallback、代码分割")
        elif long_tasks > 5:
            score -= 5

        tbt = js.get("tbt_ms", 0)
        if tbt > 600:
            score -= 15
            problems.append(f"总阻塞时间过长: {tbt:.0f}ms (建议<300ms)")

        score = max(0, score)
        verdict = "PASS" if score >= 80 else ("CONDITIONAL" if score >= 60 else "FAIL")

        if not recs:
            recs.append("页面性能良好, 建议持续监控")

        return {
            "summary": f"浏览器性能评分: {score}/100, {'良好' if verdict == 'PASS' else '需优化'}",
            "score": score,
            "page_load_analysis": f"加载完成={load_time:.0f}ms, TTFB={ttfb:.0f}ms",
            "web_vitals_analysis": f"FCP={page.get('fcp_ms', 0):.0f}ms, LCP={lcp:.0f}ms, CLS={cls}",
            "network_analysis": f"请求={total_req}, 总大小={total_size_mb}MB, 缓存命中率={network.get('cache_hit_rate', 0)}%",
            "js_analysis": f"长任务={long_tasks}个, TBT={tbt:.0f}ms",
            "bottlenecks": problems[:5],
            "recommendations": recs,
            "verdict": verdict,
        }

    def _compute_statistics(
        self, result: Dict[str, Any], metrics: List[Dict[str, Any]],
        plan: Dict[str, Any], logs: List[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """计算统计指标"""
        avg_tps = result.get("avg_tps", 0)
        peak_tps = result.get("peak_tps", 0)
        avg_rt = result.get("avg_rt", 0)
        p95_rt = result.get("p95_rt", 0)
        p99_rt = result.get("p99_rt", 0)
        error_rate = result.get("error_rate", 0)
        total_requests = result.get("total_requests", 0)
        total_errors = result.get("total_errors", 0)
        concurrency = result.get("concurrency", 0)
        duration = result.get("duration_seconds", 0)

        tps_target = plan.get("tps_target", 0)

        # TPS 达标率
        tps_achievement = (avg_tps / tps_target * 100) if tps_target > 0 else 100

        # TPS 波动率 (标准差/均值)
        tps_values = [m.get("tps", 0) for m in metrics] if metrics else []
        if tps_values and avg_tps > 0:
            tps_std = (sum((t - avg_tps) ** 2 for t in tps_values) / len(tps_values)) ** 0.5
            tps_cv = tps_std / avg_tps * 100
        else:
            tps_cv = 0

        # CPU/内存趋势
        cpu_values = [m.get("cpu_percent") for m in metrics if m.get("cpu_percent") is not None]
        mem_values = [m.get("memory_mb") for m in metrics if m.get("memory_mb") is not None]

        cpu_avg = sum(cpu_values) / len(cpu_values) if cpu_values else None
        cpu_peak = max(cpu_values) if cpu_values else None
        mem_avg = sum(mem_values) / len(mem_values) if mem_values else None
        mem_peak = max(mem_values) if mem_values else None

        # 日志统计
        logs = logs or []
        error_logs = [l for l in logs if self._get_log_level(l) in ("ERROR", "FATAL", "CRITICAL")]
        warn_logs = [l for l in logs if self._get_log_level(l) == "WARN"]
        log_error_count = len(error_logs)
        log_warn_count = len(warn_logs)

        return {
            "avg_tps": round(avg_tps, 2),
            "peak_tps": round(peak_tps, 2),
            "tps_target": tps_target,
            "tps_achievement_pct": round(tps_achievement, 1),
            "tps_cv_pct": round(tps_cv, 1),
            "avg_rt_ms": round(avg_rt, 2),
            "p95_rt_ms": p95_rt,
            "p99_rt_ms": p99_rt,
            "error_rate_pct": round(error_rate, 2),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "concurrency": concurrency,
            "duration_seconds": duration,
            "cpu_avg_pct": round(cpu_avg, 1) if cpu_avg else None,
            "cpu_peak_pct": round(cpu_peak, 1) if cpu_peak else None,
            "mem_avg_mb": round(mem_avg, 1) if mem_avg else None,
            "mem_peak_mb": round(mem_peak, 1) if mem_peak else None,
            "metric_count": len(metrics),
            "log_total": len(logs),
            "log_error_count": log_error_count,
            "log_warn_count": log_warn_count,
        }

    @staticmethod
    def _get_log_level(log_entry: Any) -> str:
        """从日志条目中提取级别"""
        if isinstance(log_entry, dict):
            level = log_entry.get("level", log_entry.get("severity", ""))
            return str(level).upper()
        if isinstance(log_entry, str):
            upper = log_entry.upper()
            for lvl in ("ERROR", "FATAL", "CRITICAL", "WARN", "INFO", "DEBUG"):
                if lvl in upper:
                    return lvl
        return "UNKNOWN"

    def _build_analysis_prompt(
        self, stats: Dict[str, Any], metrics: List[Dict], plan: Dict[str, Any],
        logs: List[Dict[str, Any]] = None,
    ) -> str:
        """构建 LLM 分析 prompt (实时指标 + 日志直接传入, 不走 RAG)"""
        # 取关键时间点的指标 (避免 prompt 过长)
        if len(metrics) > 20:
            step = len(metrics) // 20
            sampled = metrics[::step][:20]
        else:
            sampled = metrics

        # 提取关键日志 (最多 30 条, 优先 ERROR/WARN)
        logs = logs or []
        error_logs = [l for l in logs if self._get_log_level(l) in ("ERROR", "FATAL", "CRITICAL")]
        warn_logs = [l for l in logs if self._get_log_level(l) == "WARN"]
        key_logs = error_logs[:20] + warn_logs[:10]
        if len(key_logs) < 30:
            other_logs = [l for l in logs if l not in key_logs]
            key_logs.extend(other_logs[:30 - len(key_logs)])

        # 序列化日志条目
        serialized_logs = []
        for log in key_logs[:30]:
            if isinstance(log, dict):
                serialized_logs.append({
                    "timestamp": log.get("timestamp", log.get("time", "")),
                    "level": log.get("level", log.get("severity", "")),
                    "message": str(log.get("message", log.get("msg", log.get("text", ""))))[:500],
                    "source": log.get("source", log.get("logger", "")),
                })
            elif isinstance(log, str):
                serialized_logs.append({"raw": log[:500]})

        return json.dumps({
            "statistics": stats,
            "sampled_metrics": [
                {
                    "elapsed_s": round(m.get("elapsed", 0), 1),
                    "tps": round(m.get("tps", 0), 1),
                    "avg_rt_ms": round(m.get("avg_rt", 0), 1),
                    "concurrent_users": m.get("concurrent_users", 0),
                    "errors": m.get("error_count", 0),
                    "cpu_pct": m.get("cpu_percent"),
                    "memory_mb": m.get("memory_mb"),
                }
                for m in sampled
            ],
            "logs": serialized_logs,
            "target_plan": {
                "tps_target": plan.get("tps_target", 0),
                "concurrency": plan.get("concurrency", 0),
                "duration_seconds": plan.get("duration_seconds", 0),
            },
        }, ensure_ascii=False, indent=2)

    def _fallback_analysis(self, stats: Dict[str, Any], logs: List = None) -> Dict[str, Any]:
        """降级分析 (LLM 不可用时)"""
        score = 100
        bottlenecks = []
        recommendations = []

        # TPS 达标率评分
        tps_ach = stats.get("tps_achievement_pct", 100)
        if tps_ach < 80:
            score -= 30
            bottlenecks.append(f"TPS达标率仅{tps_ach}%, 未达到目标")
            recommendations.append("检查应用层处理能力, 考虑增加实例或优化代码")
        elif tps_ach < 95:
            score -= 10

        # 响应时间评分
        p95 = stats.get("p95_rt_ms", 0)
        if p95 > 2000:
            score -= 25
            bottlenecks.append(f"P95响应时间{p95}ms, 超过2秒阈值")
            recommendations.append("排查慢SQL、外部调用超时、锁竞争")
        elif p95 > 1000:
            score -= 10

        # 错误率评分
        err_rate = stats.get("error_rate_pct", 0)
        if err_rate > 5:
            score -= 30
            bottlenecks.append(f"错误率{err_rate}%, 超过5%阈值")
            recommendations.append("检查应用日志, 定位错误根因")
        elif err_rate > 1:
            score -= 10

        # CPU 评分
        cpu_peak = stats.get("cpu_peak_pct")
        if cpu_peak and cpu_peak > 80:
            score -= 15
            bottlenecks.append(f"CPU峰值{cpu_peak}%, 资源瓶颈")
            recommendations.append("考虑水平扩容或优化CPU密集型操作")

        # 日志分析评分
        log_err = stats.get("log_error_count", 0)
        log_warn = stats.get("log_warn_count", 0)
        if log_err > 10:
            score -= 15
            bottlenecks.append(f"日志中发现{log_err}条ERROR级别异常")
            recommendations.append("检查应用日志中的ERROR堆栈, 修复异常代码路径")
        elif log_err > 0:
            score -= 5

        score = max(0, score)
        verdict = "PASS" if score >= 80 else ("CONDITIONAL" if score >= 60 else "FAIL")

        log_summary = f"日志共{stats.get('log_total', 0)}条, ERROR={log_err}, WARN={log_warn}"

        return {
            "summary": f"性能评分{score}/100, {'达标' if verdict == 'PASS' else '需优化'}",
            "score": score,
            "tps_analysis": f"平均TPS={stats.get('avg_tps')}, 达标率={tps_ach}%",
            "rt_analysis": f"P95={p95}ms, P99={stats.get('p99_rt_ms')}ms",
            "error_analysis": f"错误率={err_rate}%, 总错误={stats.get('total_errors')}",
            "resource_analysis": f"CPU峰值={cpu_peak}%, 内存峰值={stats.get('mem_peak_mb')}MB",
            "log_analysis": log_summary,
            "bottlenecks": bottlenecks,
            "recommendations": recommendations,
            "verdict": verdict,
        }


# ================================================================
# 4. PerformanceDiagnosticAgent — 性能诊断 Agent
# ================================================================

class PerformanceDiagnosticAgent(BaseRoutedAgent):
    """性能诊断 Agent

    输入:
        - jstack_dump:      Java 线程转储文本 (jstack 输出)
        - logs:             应用日志列表
        - monitoring_data:  监控指标 (TPS/RT/CPU/Memory/metrics 等)
        - task_id:          关联的任务 ID (可选)

    输出:
        - diagnosis:        诊断报告 (问题列表 + 关联分析 + 严重度)
        - problems:         检测到的问题列表
        - correlations:     多源关联分析结果
        - llm_analysis:     LLM 深度分析 (问题定位 + 修复建议)

    分析能力:
        1. jstack 分析: 线程阻塞 / 死锁 / CPU 热点
        2. 日志分析:   错误聚类 / 慢操作 / 错误突增
        3. 监控分析:   高错误率 / CPU 过高 / 高延迟
        4. 关联分析:   多源问题关联 (如: 线程阻塞 + 高 RT)

    设计约束:
        - 不使用 RAG, 使用 dump 解析 + LLM 直接分析
        - 解析模块 (analyzer) 提供确定性分析
        - LLM 提供深度问题定位和修复建议
    """

    SYSTEM_PROMPT = """你是一位资深的 Java 性能诊断专家。
根据线程转储 (jstack) 分析报告、日志分析报告和监控指标, 进行深度问题定位。

你的任务:
1. 综合三个数据源的分析结果, 判断问题的根因
2. 对每个检测到的问题, 给出精确的代码定位 (类名/方法名/行号)
3. 分析问题之间的因果关系 (如: 死锁 → 线程阻塞 → 高 RT → TPS 下降)
4. 给出具体可操作的修复建议 (代码级别)

输出 JSON:
{
  "root_cause": "根因分析 (1-3句话)",
  "causal_chain": ["原因1 → 结果1", "原因2 → 结果2"],
  "problem_details": [
    {
      "problem": "问题描述",
      "root_cause": "根因",
      "code_location": "类名.方法名:行号",
      "fix_suggestion": "修复建议 (具体到代码)",
      "confidence": "high/medium/low"
    }
  ],
  "priority_fixes": ["最优先修复项1", "最优先修复项2"],
  "risk_assessment": "如果不及修复的风险评估"
}"""

    def __init__(self) -> None:
        super().__init__(
            description="性能诊断Agent, 解析jstack/日志/监控数据, 定位性能问题根因",
            display_name="PerformanceDiagnosticAgent",
            capabilities=["performance_diagnosis", "jstack_analysis", "deadlock_detection",
                         "thread_analysis", "cpu_hotspot", "log_analysis"],
        )

    @action_handler("diagnose")
    async def handle_diagnose(self, payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """执行性能诊断

        流程:
          1. 调用 DiagnosticReportBuilder 进行确定性分析 (解析模块)
          2. 调用 LLM 进行深度问题定位和修复建议
          3. 合并结果返回
        """
        from app.domains.performance.analyzer import build_diagnostic_report, DiagnosticReportBuilder

        jstack_dump = payload.get("jstack_dump", "")
        logs = payload.get("logs", [])
        monitoring_data = payload.get("monitoring_data", {})

        # 1. 确定性分析 (解析模块, 不依赖 LLM)
        builder = DiagnosticReportBuilder()
        diag_report = builder.build(jstack_dump, logs, monitoring_data)
        report_dict = diag_report.to_dict()

        # 2. LLM 深度分析 (将解析结果交给 LLM 做根因定位)
        llm_analysis = None
        if diag_report.problems:
            try:
                llm_analysis = await self.call_llm_json(
                    system_prompt=self.SYSTEM_PROMPT,
                    user_prompt=diag_report.to_llm_prompt(),
                    temperature=0.3,
                    max_tokens=4096,
                )
            except Exception as e:
                logger.warning(f"PerformanceDiagnosticAgent LLM 调用失败, 使用确定性分析: {e}")
                llm_analysis = self._fallback_llm_analysis(diag_report)
        else:
            llm_analysis = {
                "root_cause": "未检测到明显性能问题",
                "causal_chain": [],
                "problem_details": [],
                "priority_fixes": [],
                "risk_assessment": "低风险",
            }

        return {
            "status": "success",
            "diagnosis": report_dict,
            "problems": [p.to_dict() for p in diag_report.problems],
            "correlations": diag_report.correlations,
            "overall_severity": diag_report.overall_severity,
            "llm_analysis": llm_analysis,
        }

    async def execute(self, payload: Dict, ctx: Any = None) -> Dict:
        """默认 execute 入口 → 路由到 diagnose"""
        return await self.handle_diagnose(payload, ctx)

    def _fallback_llm_analysis(self, report: "DiagnosticReport") -> Dict[str, Any]:
        """降级 LLM 分析 (LLM 不可用时, 基于规则生成)"""
        problems = report.problems
        if not problems:
            return {
                "root_cause": "未检测到明显性能问题",
                "causal_chain": [],
                "problem_details": [],
                "priority_fixes": [],
                "risk_assessment": "低风险",
            }

        # 按严重度排序
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        sorted_problems = sorted(
            problems,
            key=lambda p: severity_order.get(p.severity, 1),
            reverse=True,
        )

        root = sorted_problems[0]
        causal_chain = []
        for corr in report.correlations:
            causal_chain.append(corr.get("description", ""))

        problem_details = []
        for p in sorted_problems[:5]:
            problem_details.append({
                "problem": p.title,
                "root_cause": p.description,
                "code_location": p.location,
                "fix_suggestion": "; ".join(p.recommendations[:2]),
                "confidence": "high" if p.severity in ("critical", "high") else "medium",
            })

        priority_fixes = [p.title for p in sorted_problems[:3]]

        risk = "高风险" if report.overall_severity == "critical" else \
               "中风险" if report.overall_severity == "high" else "低风险"

        return {
            "root_cause": root.description,
            "causal_chain": causal_chain,
            "problem_details": problem_details,
            "priority_fixes": priority_fixes,
            "risk_assessment": risk,
        }
