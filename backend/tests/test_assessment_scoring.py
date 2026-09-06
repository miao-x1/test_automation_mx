"""效能评分：只对真实指标打分，不编造分数。"""
from app.services.assessment_scoring import (
    job_score,
    network_score,
    overall_score,
    page_score,
    regression_score,
    resource_score,
)


def test_page_score_uses_thresholds():
    score, issues = page_score({
        "ttfb_ms": 100,
        "dom_ready_ms": 800,
        "load_complete_ms": 1200,
        "fcp_ms": 900,
        "lcp_ms": 1400,
    })
    assert score == 100
    assert issues == []

    score, issues = page_score({"ttfb_ms": 2000, "dom_ready_ms": 5000})
    assert score == 40
    assert any(item["metric"] == "ttfb_ms" for item in issues)


def test_missing_metrics_are_skipped():
    score, issues = page_score({"ttfb_ms": 0, "fcp_ms": None})
    assert score is None
    assert issues == []


def test_network_unsupported_without_xhr():
    score, issues, supported = network_score({
        "total_requests": 8,
        "by_resource_type": {"script": {"count": 3}},
        "slowest_requests": [{"resource_type": "script", "duration_ms": 200}],
    })
    assert supported is False
    assert score is None
    assert issues == []


def test_network_supported_with_fetch():
    score, issues, supported = network_score({
        "avg_duration_ms": 100,
        "by_resource_type": {"fetch": {"count": 2}},
        "slowest_requests": [{"resource_type": "fetch", "duration_ms": 120, "status": 200, "url": "/api"}],
    })
    assert supported is True
    assert score == 100


def test_overall_renormalizes_missing_dimensions():
    assert overall_score({"page": 90, "resource": 80, "network": None, "job": None, "regression": None}) == 86
    assert overall_score({"page": None, "resource": None, "network": None, "job": None, "regression": None}) is None


def test_job_and_regression_scores():
    score, issues = job_score([{"status": "SUCCESS"}, {"status": "FAILED"}])
    assert score == 50
    assert issues
    score, _ = regression_score([{"passed_count": 8, "failed_count": 2}])
    assert score == 80


def test_resource_fail_rate():
    score, issues = resource_score({
        "total_requests": 10,
        "failed_requests": [{}],
        "avg_duration_ms": 100,
        "by_resource_type": {},
    })
    assert score == 70
    assert any(item["metric"] == "failed_requests" for item in issues)
