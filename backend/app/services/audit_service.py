"""
审计日志服务

功能:
  1. 记录操作日志(OperationLog): 所有 API 调用记录
  2. 记录审计事件(AuditEvent): 安全相关事件
  3. 查询/过滤操作日志和审计事件
  4. 安全仪表盘(聚合统计 + 告警)
  5. 安全事件检测(异常登录/暴力破解/敏感数据访问)

设计:
  - log_operation() 高频写入,异步可选
  - log_event() 安全事件,立即写入
  - 请求体入库前自动脱敏(调用 MaskingService)
  - 审计事件支持 severity 分级,便于告警
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.security import (
    OperationLog,
    AuditEvent,
    AuditEventType,
    AuditSeverity,
)

logger = logging.getLogger(__name__)


class AuditService:
    """审计日志服务"""

    # 不记录日志的路径(避免噪音)
    _EXCLUDE_PATHS = {
        "/api/health", "/docs", "/redoc", "/openapi.json",
        "/api/health/", "/favicon.ico",
    }

    # 不记录请求体的字段(避免泄露)
    _NO_BODY_PATHS = {"/api/auth/login", "/api/auth/register"}

    def log_operation(
        self,
        *,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        action: str,
        method: str,
        path: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_body: Optional[str] = None,
        response_status: Optional[int] = None,
        duration: Optional[float] = None,
        error_message: Optional[str] = None,
        async_write: bool = False,
    ) -> None:
        """记录操作日志

        Args:
            action: 动作(create/update/delete/login/logout等)
            method: HTTP方法
            path: API路径
            request_body: 请求体(会自动脱敏)
            async_write: 是否异步写入
        """
        if path in self._EXCLUDE_PATHS:
            return

        # 请求体脱敏
        masked_body = None
        if request_body and path not in self._NO_BODY_PATHS:
            try:
                from app.services.masking_service import get_masking_service
                masking = get_masking_service()
                masked_body = masking.mask_json_string(request_body)
                # 限制长度
                if len(masked_body) > 5000:
                    masked_body = masked_body[:5000] + "...[truncated]"
            except Exception as e:
                logger.warning(f"[AuditService] 请求体脱敏失败: {e}")
                masked_body = "[masking_failed]"

        def _write():
            db = SessionLocal()
            try:
                log = OperationLog(
                    user_id=user_id,
                    created_by=user_id,
                    username=username,
                    action=action,
                    method=method,
                    path=path,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    ip_address=ip_address,
                    user_agent=user_agent[:500] if user_agent else None,
                    request_body=masked_body,
                    response_status=response_status,
                    duration=duration,
                    error_message=error_message,
                )
                db.add(log)
                db.commit()
            except Exception as e:
                logger.error(f"[AuditService] 写入操作日志失败: {e}")
                db.rollback()
            finally:
                db.close()

        if async_write:
            try:
                asyncio.create_task(asyncio.to_thread(_write))
            except RuntimeError:
                _write()
        else:
            _write()

    def log_event(
        self,
        *,
        event_type: str,
        severity: str = AuditSeverity.INFO.value,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        """记录审计事件

        Args:
            event_type: 事件类型(permission_change/api_key_operation/data_access/security_alert等)
            severity: 严重级别(info/warning/critical)
            action: 动作描述
            target_type: 目标资源类型
            target_id: 目标资源ID
            details: 详细信息(会脱敏)
        """
        # details 脱敏
        masked_details = None
        if details:
            try:
                from app.services.masking_service import get_masking_service
                masking = get_masking_service()
                masked_details = masking.mask_dict(details)
            except Exception:
                masked_details = details

        db = SessionLocal()
        try:
            event = AuditEvent(
                event_type=event_type,
                severity=severity,
                user_id=user_id,
                created_by=user_id,
                username=username,
                action=action,
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                details=json.dumps(masked_details, ensure_ascii=False) if masked_details else None,
                ip_address=ip_address,
            )
            db.add(event)
            db.commit()
            db.refresh(event)

            # 如果是严重事件,记录告警
            if severity == AuditSeverity.CRITICAL.value:
                logger.warning(
                    f"[AuditService] 严重安全事件: type={event_type} "
                    f"action={action} user={username} ip={ip_address}"
                )

            return event.to_dict()
        except Exception as e:
            logger.error(f"[AuditService] 写入审计事件失败: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    # ============================================================
    # 查询
    # ============================================================

    def list_operation_logs(
        self,
        *,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        ip_address: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """操作日志列表(分页,支持多条件筛选)"""
        db = SessionLocal()
        try:
            q = db.query(OperationLog)
            if user_id is not None:
                q = q.filter(OperationLog.user_id == user_id)
            if username:
                q = q.filter(OperationLog.username == username)
            if action:
                q = q.filter(OperationLog.action == action)
            if resource_type:
                q = q.filter(OperationLog.resource_type == resource_type)
            if ip_address:
                q = q.filter(OperationLog.ip_address == ip_address)
            if start_time:
                q = q.filter(OperationLog.created_at >= start_time)
            if end_time:
                q = q.filter(OperationLog.created_at <= end_time)

            total = q.count()
            items = (
                q.order_by(desc(OperationLog.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [log.to_dict() for log in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def list_audit_events(
        self,
        *,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        target_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """审计事件列表(分页,支持多条件筛选)"""
        db = SessionLocal()
        try:
            q = db.query(AuditEvent)
            if event_type:
                q = q.filter(AuditEvent.event_type == event_type)
            if severity:
                q = q.filter(AuditEvent.severity == severity)
            if user_id is not None:
                q = q.filter(AuditEvent.user_id == user_id)
            if username:
                q = q.filter(AuditEvent.username == username)
            if target_type:
                q = q.filter(AuditEvent.target_type == target_type)
            if start_time:
                q = q.filter(AuditEvent.created_at >= start_time)
            if end_time:
                q = q.filter(AuditEvent.created_at <= end_time)

            total = q.count()
            items = (
                q.order_by(desc(AuditEvent.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [e.to_dict() for e in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def get_operation_log(self, log_id: int) -> Optional[Dict[str, Any]]:
        """获取操作日志详情"""
        db = SessionLocal()
        try:
            log = db.query(OperationLog).filter(
                OperationLog.id == log_id
            ).first()
            return None if log is None else log.to_dict()
        finally:
            db.close()

    def get_audit_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        """获取审计事件详情"""
        db = SessionLocal()
        try:
            event = db.query(AuditEvent).filter(
                AuditEvent.id == event_id
            ).first()
            return None if event is None else event.to_dict()
        finally:
            db.close()

    # ============================================================
    # 安全仪表盘
    # ============================================================

    def get_dashboard(
        self,
        *,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """安全仪表盘

        Args:
            hours: 统计时间范围(小时)
        """
        since = datetime.now() - timedelta(hours=hours)
        db = SessionLocal()
        try:
            # 操作日志统计
            op_logs = db.query(OperationLog).filter(
                OperationLog.created_at >= since
            ).all()

            op_by_action: Dict[str, int] = {}
            op_by_status = {"success": 0, "error": 0, "other": 0}
            op_by_user: Dict[str, int] = {}
            op_by_ip: Dict[str, int] = {}
            failed_ops = []

            for log in op_logs:
                action = log.action or "unknown"
                op_by_action[action] = op_by_action.get(action, 0) + 1

                status = log.response_status or 0
                if 200 <= status < 300:
                    op_by_status["success"] += 1
                elif status >= 400:
                    op_by_status["error"] += 1
                    if status >= 500:
                        failed_ops.append({
                            "action": log.action,
                            "path": log.path,
                            "status": status,
                            "error": (log.error_message or "")[:200],
                            "time": log.created_at.isoformat() if log.created_at else None,
                        })
                else:
                    op_by_status["other"] += 1

                if log.username:
                    op_by_user[log.username] = op_by_user.get(log.username, 0) + 1
                if log.ip_address:
                    op_by_ip[log.ip_address] = op_by_ip.get(log.ip_address, 0) + 1

            # 审计事件统计
            audit_events = db.query(AuditEvent).filter(
                AuditEvent.created_at >= since
            ).all()

            audit_by_type: Dict[str, int] = {}
            audit_by_severity: Dict[str, int] = {"info": 0, "warning": 0, "critical": 0}
            critical_events = []

            for event in audit_events:
                etype = event.event_type or "unknown"
                audit_by_type[etype] = audit_by_type.get(etype, 0) + 1
                sev = event.severity or "info"
                audit_by_severity[sev] = audit_by_severity.get(sev, 0) + 1
                if sev == AuditSeverity.CRITICAL.value:
                    critical_events.append(event.to_dict())

            # 异常检测: 同IP高频访问(>100次/小时)
            suspicious_ips = [
                {"ip": ip, "count": count}
                for ip, count in op_by_ip.items()
                if count > 100
            ]

            # 异常检测: 错误率过高
            error_rate = 0.0
            if op_logs:
                error_rate = round(op_by_status["error"] / len(op_logs) * 100, 2)

            return {
                "time_range_hours": hours,
                "operation_logs": {
                    "total": len(op_logs),
                    "by_action": op_by_action,
                    "by_status": op_by_status,
                    "error_rate": error_rate,
                    "top_users": sorted(op_by_user.items(), key=lambda x: -x[1])[:10],
                    "top_ips": sorted(op_by_ip.items(), key=lambda x: -x[1])[:10],
                    "recent_failures": failed_ops[:10],
                },
                "audit_events": {
                    "total": len(audit_events),
                    "by_type": audit_by_type,
                    "by_severity": audit_by_severity,
                    "critical_events": critical_events[:10],
                },
                "alerts": {
                    "suspicious_ips": suspicious_ips,
                    "high_error_rate": error_rate > 20,
                    "critical_event_count": len(critical_events),
                },
            }
        finally:
            db.close()

    def get_stats(
        self,
        *,
        hours: int = 24,
    ) -> Dict[str, Any]:
        """统计信息"""
        since = datetime.now() - timedelta(hours=hours)
        db = SessionLocal()
        try:
            op_total = db.query(OperationLog).filter(
                OperationLog.created_at >= since
            ).count()

            audit_total = db.query(AuditEvent).filter(
                AuditEvent.created_at >= since
            ).count()

            critical_count = db.query(AuditEvent).filter(
                AuditEvent.created_at >= since,
                AuditEvent.severity == AuditSeverity.CRITICAL.value,
            ).count()

            warning_count = db.query(AuditEvent).filter(
                AuditEvent.created_at >= since,
                AuditEvent.severity == AuditSeverity.WARNING.value,
            ).count()

            unique_users = db.query(OperationLog.username).filter(
                OperationLog.created_at >= since,
                OperationLog.username.isnot(None),
            ).distinct().count()

            unique_ips = db.query(OperationLog.ip_address).filter(
                OperationLog.created_at >= since,
                OperationLog.ip_address.isnot(None),
            ).distinct().count()

            return {
                "time_range_hours": hours,
                "operation_logs_total": op_total,
                "audit_events_total": audit_total,
                "critical_events": critical_count,
                "warning_events": warning_count,
                "unique_users": unique_users,
                "unique_ips": unique_ips,
            }
        finally:
            db.close()

    def detect_security_anomalies(
        self,
        *,
        hours: int = 1,
    ) -> List[Dict[str, Any]]:
        """检测安全异常

        检测规则:
        1. 同IP高频访问(>50次/小时)
        2. 同用户高频操作(>100次/小时)
        3. 大量失败请求(>10次/小时)
        4. 敏感操作(删除/权限变更)
        """
        since = datetime.now() - timedelta(hours=hours)
        db = SessionLocal()
        try:
            anomalies = []

            # 1. 同IP高频访问
            ip_counts = db.query(
                OperationLog.ip_address,
                func.count(OperationLog.id).label("cnt"),
            ).filter(
                OperationLog.created_at >= since,
                OperationLog.ip_address.isnot(None),
            ).group_by(OperationLog.ip_address).all()

            for ip, count in ip_counts:
                if count > 50:
                    anomalies.append({
                        "type": "high_frequency_ip",
                        "severity": AuditSeverity.WARNING.value,
                        "ip_address": ip,
                        "count": count,
                        "description": f"IP {ip} 在{hours}小时内访问{count}次",
                    })

            # 2. 大量失败请求
            failed_logs = db.query(OperationLog).filter(
                OperationLog.created_at >= since,
                OperationLog.response_status >= 400,
            ).all()

            failed_by_ip: Dict[str, int] = {}
            for log in failed_logs:
                if log.ip_address:
                    failed_by_ip[log.ip_address] = failed_by_ip.get(log.ip_address, 0) + 1

            for ip, count in failed_by_ip.items():
                if count > 10:
                    anomalies.append({
                        "type": "high_failure_rate",
                        "severity": AuditSeverity.WARNING.value,
                        "ip_address": ip,
                        "count": count,
                        "description": f"IP {ip} 在{hours}小时内失败{count}次",
                    })

            # 3. 敏感操作
            sensitive_logs = db.query(OperationLog).filter(
                OperationLog.created_at >= since,
                OperationLog.action.in_(["delete", "permission_change", "config_change"]),
            ).all()

            for log in sensitive_logs:
                anomalies.append({
                    "type": "sensitive_operation",
                    "severity": AuditSeverity.INFO.value,
                    "user": log.username,
                    "action": log.action,
                    "path": log.path,
                    "time": log.created_at.isoformat() if log.created_at else None,
                    "description": f"用户 {log.username} 执行了 {log.action} 操作",
                })

            return anomalies
        finally:
            db.close()


# ============================================================
# 单例
# ============================================================
_service: Optional[AuditService] = None


def get_audit_service() -> AuditService:
    global _service
    if _service is None:
        _service = AuditService()
    return _service


def reset_audit_service() -> None:
    """重置单例(测试用)"""
    global _service
    _service = None
