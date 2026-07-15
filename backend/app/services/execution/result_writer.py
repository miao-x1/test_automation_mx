"""
ResultWriter - 结果写入器

职责：将执行结果持久化到数据库
"""
import json
from typing import Any, Dict, List, Optional
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.execution_record import ExecutionRecord, ExecutionStatus


class ResultWriter:
    """结果写入器"""

    @staticmethod
    def create_execution(
        task_id: int = 0,
        trigger_source: str = "api_test",
        env: str = "test",
    ) -> int:
        """
        创建执行记录

        Returns:
            execution_id
        """
        db = SessionLocal()
        try:
            record = ExecutionRecord(
                task_id=task_id,
                status=ExecutionStatus.WAITING,
                trigger_source=trigger_source,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        finally:
            db.close()

    @staticmethod
    def update_execution(
        execution_id: int,
        status: Optional[str] = None,
        success_count: Optional[int] = None,
        failed_count: Optional[int] = None,
        error_message: Optional[str] = None,
        log_content: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> None:
        """更新执行记录"""
        db = SessionLocal()
        try:
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if not record:
                return

            if status is not None:
                record.status = status
            if success_count is not None:
                record.success_count = success_count
            if failed_count is not None:
                record.failed_count = failed_count
            if error_message is not None:
                record.error_message = error_message
            if log_content is not None:
                record.log_content = log_content
            if duration is not None:
                record.duration = duration

            db.commit()
        finally:
            db.close()

    @staticmethod
    def save_case_result(
        execution_id: int,
        case_result: Dict[str, Any],
    ) -> None:
        """保存单个用例的执行结果"""
        db = SessionLocal()
        try:
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if not record:
                return

            # 追加到log_content
            existing_log = record.log_content or ""
            case_id = case_result.get("case_id", "unknown")
            status = case_result.get("status", "UNKNOWN")
            duration = case_result.get("duration_ms", 0)

            log_entry = f"\n[{status}] {case_id} ({duration}ms)"
            if case_result.get("error"):
                log_entry += f" - {case_result['error']}"

            # 断言详情
            assertion_result = case_result.get("assertion_result", {})
            if assertion_result.get("failed_count", 0) > 0:
                for ar in assertion_result.get("results", []):
                    if not ar.get("passed"):
                        log_entry += f"\n  FAIL: {ar.get('path', '')} {ar.get('type', '')} expected={ar.get('expected', '')} actual={ar.get('actual', '')}"

            record.log_content = existing_log + log_entry

            # 更新计数
            if status == "PASS":
                record.success_count = (record.success_count or 0) + 1
            else:
                record.failed_count = (record.failed_count or 0) + 1

            db.commit()
        finally:
            db.close()

    @staticmethod
    def save_all_results(
        execution_id: int,
        case_results: List[Dict[str, Any]],
        total_duration_ms: int,
    ) -> None:
        """保存所有用例执行结果"""
        db = SessionLocal()
        try:
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if not record:
                return

            passed = sum(1 for r in case_results if r.get("status") == "PASS")
            failed = len(case_results) - passed

            record.success_count = passed
            record.failed_count = failed
            record.duration = total_duration_ms / 1000.0
            record.status = ExecutionStatus.SUCCESS if failed == 0 else ExecutionStatus.FAILED

            # 生成详细日志
            log_lines = []
            for r in case_results:
                cid = r.get("case_id", "?")
                title = r.get("title", "")
                status = r.get("status", "?")
                dur = r.get("duration_ms", 0)
                line = f"[{status}] {cid}: {title} ({dur}ms)"
                if r.get("error"):
                    line += f" - {r['error']}"
                log_lines.append(line)

            record.log_content = "\n".join(log_lines)

            # 保存完整结果JSON到analysis_result
            record.analysis_result = json.dumps({
                "total": len(case_results),
                "passed": passed,
                "failed": failed,
                "duration_ms": total_duration_ms,
                "cases": [
                    {
                        "case_id": r.get("case_id"),
                        "title": r.get("title"),
                        "status": r.get("status"),
                        "duration_ms": r.get("duration_ms"),
                        "assertion_result": r.get("assertion_result"),
                        "error": r.get("error"),
                    }
                    for r in case_results
                ],
            }, ensure_ascii=False)

            db.commit()
        finally:
            db.close()
