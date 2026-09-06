"""效能评分：只对真实采集到的指标打分，缺失维度不参与总分。"""
from __future__ import annotations

from typing import Any, Optional


def _score_lower_better(value: Optional[float], good: float, warn: float) -> Optional[int]:
    if value is None or value <= 0:
        return None
    if value <= good:
        return 100
    if value <= warn:
        return 70
    return 40


def page_score(page: dict) -> tuple[Optional[int], list[dict]]:
    parts = []
    issues = []
    mapping = [
        ("ttfb_ms", 200, 800, "首字节时间偏高", "建议检查服务端响应和网络"),
        ("dom_ready_ms", 1500, 3000, "DOM 就绪偏慢", "减少阻塞脚本，优化关键渲染路径"),
        ("load_complete_ms", 3000, 6000, "页面完全加载偏慢", "压缩资源、延迟非关键请求"),
        ("fcp_ms", 1800, 3000, "首次内容绘制偏慢", "优先加载首屏内容"),
        ("lcp_ms", 2500, 4000, "最大内容绘制偏慢", "优化主图/主文本加载"),
    ]
    for key, good, warn, title, advice in mapping:
        raw = page.get(key)
        scored = _score_lower_better(raw, good, warn)
        if scored is None:
            continue
        parts.append(scored)
        if scored <= 70:
            issues.append({
                "problem": title,
                "metric": key,
                "actual": raw,
                "reference": f"≤{good}ms 优秀，≤{warn}ms 可接受",
                "impact": "影响用户打开页面的等待感受",
                "advice": advice,
            })
    if not parts:
        return None, issues
    return int(round(sum(parts) / len(parts))), issues


def resource_score(network: dict) -> tuple[Optional[int], list[dict]]:
    total = network.get("total_requests") or network.get("request_count") or 0
    if not total:
        return None, []
    failed = len(network.get("failed_requests") or [])
    avg = network.get("avg_duration_ms") or 0
    fail_rate = failed / total
    score = 100
    issues = []
    if fail_rate > 0.05:
        score -= 30
        issues.append({
            "problem": "存在失败资源",
            "metric": "failed_requests",
            "actual": failed,
            "reference": "失败率应低于 5%",
            "impact": "页面功能或样式可能不完整",
            "advice": "检查失败的 JS/CSS/图片地址和权限",
        })
    if avg > 500:
        score -= 20
        issues.append({
            "problem": "资源平均加载时间偏高",
            "metric": "avg_duration_ms",
            "actual": avg,
            "reference": "≤300ms 较好，≤500ms 可接受",
            "impact": "拖慢整体打开速度",
            "advice": "合并压缩静态资源，启用缓存",
        })
    by_type = network.get("by_resource_type") or {}
    for key in ("script", "javascript", "js"):
        bucket = by_type.get(key) or {}
        dur = bucket.get("duration_ms") or bucket.get("avg_duration_ms")
        if dur and dur > 800:
            score -= 10
            issues.append({
                "problem": "JS 资源加载时间较高",
                "metric": f"{key}_duration_ms",
                "actual": dur,
                "reference": "≤800ms",
                "impact": "阻塞交互",
                "advice": "拆分或延迟非首屏脚本",
            })
            break
    return max(40, min(100, score)), issues


def network_score(network: dict) -> tuple[Optional[int], list[dict], bool]:
    """接口响应：仅当存在 xhr/fetch 请求时计分。"""
    by_type = network.get("by_resource_type") or {}
    api_keys = ("xhr", "fetch", "XHR", "Fetch")
    api_count = 0
    api_fail = 0
    slowest = None
    for key in api_keys:
        bucket = by_type.get(key) or {}
        api_count += int(bucket.get("count") or bucket.get("requests") or 0)
    requests = network.get("slowest_requests") or []
    api_reqs = [r for r in requests if str(r.get("resource_type") or "").lower() in {"xhr", "fetch"}]
    if api_reqs:
        api_count = max(api_count, len(api_reqs))
        api_fail = sum(1 for r in api_reqs if int(r.get("status") or 0) >= 400 or int(r.get("status") or 0) == 0)
        slowest = max(api_reqs, key=lambda r: r.get("duration_ms") or 0)
    if api_count <= 0 and not api_reqs:
        return None, [], False
    score = 100
    issues = []
    avg = network.get("avg_duration_ms") or 0
    if avg > 800:
        score -= 20
    if api_fail:
        score -= 20
        issues.append({
            "problem": "接口请求存在失败",
            "metric": "api_failed",
            "actual": api_fail,
            "reference": "失败数为 0",
            "impact": "页面数据可能不完整",
            "advice": "检查失败接口的状态码和耗时",
        })
    if slowest and (slowest.get("duration_ms") or 0) > 1000:
        score -= 15
        issues.append({
            "problem": "最慢接口响应偏高",
            "metric": "slowest_api_ms",
            "actual": slowest.get("duration_ms"),
            "reference": "≤1000ms",
            "impact": "拖慢交互",
            "advice": f"优化 {slowest.get('url')}",
        })
    return max(40, min(100, score)), issues, True


def job_score(jobs: list[dict]) -> tuple[Optional[int], list[dict]]:
    if not jobs:
        return None, []
    success = sum(1 for j in jobs if j.get("status") == "SUCCESS")
    failed = sum(1 for j in jobs if j.get("status") == "FAILED")
    total = len(jobs)
    rate = success / total if total else 0
    score = int(round(rate * 100))
    issues = []
    if failed:
        issues.append({
            "problem": "存在失败的测试任务",
            "metric": "job_failed",
            "actual": failed,
            "reference": "失败数为 0",
            "impact": "回归质量下降",
            "advice": "优先修复失败任务后再看效能",
        })
    return max(40, score) if total else None, issues


def regression_score(runs: list[dict]) -> tuple[Optional[int], list[dict]]:
    if not runs:
        return None, []
    last = runs[0]
    passed = last.get("passed_count") or 0
    failed = last.get("failed_count") or 0
    total = passed + failed
    if total <= 0:
        return None, []
    score = int(round(passed * 100 / total))
    issues = []
    if failed:
        issues.append({
            "problem": "最近一次回归存在失败",
            "metric": "regression_failed",
            "actual": failed,
            "reference": "失败数为 0",
            "impact": "发布风险上升",
            "advice": "查看回归详情并修复失败 Job",
        })
    return max(40, score), issues


def overall_score(parts: dict[str, Optional[int]]) -> Optional[int]:
    weights = {
        "page": 0.3,
        "resource": 0.2,
        "network": 0.15,
        "job": 0.2,
        "regression": 0.15,
    }
    used = [(weights[k], v) for k, v in parts.items() if v is not None and k in weights]
    if not used:
        return None
    total_w = sum(w for w, _ in used)
    return int(round(sum(w * v for w, v in used) / total_w))


def summarize_advice(issues: list[dict], scores: dict) -> str:
    if not issues:
        return "本次测评未发现明显效能问题。继续保持当前页面和回归稳定性。"
    lines = ["根据真实采集指标，建议优先处理："]
    for item in issues[:5]:
        lines.append(f"- {item['problem']}（{item['metric']}={item['actual']}）：{item['advice']}")
    missing = [k for k, v in scores.items() if v is None]
    if missing:
        lines.append("以下维度因缺少真实数据未计入总分：" + "、".join(missing))
    return "\n".join(lines)
