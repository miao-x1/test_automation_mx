"""
ReportGenerator - 报告生成器

职责：根据执行结果生成测试报告

支持格式：
- JSON: 结构化数据
- HTML: 可视化报告
- Excel: .xlsx 文件报告
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.execution_record import ExecutionRecord

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


class ReportGenerator:
    """报告生成器"""

    @staticmethod
    def generate(execution_id: int, format: str = "json") -> Any:
        """
        生成测试报告

        Args:
            execution_id: 执行ID
            format: 报告格式 (json/html/excel)

        Returns:
            报告数据（dict / str / 文件路径）
        """
        db = SessionLocal()
        try:
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if not record:
                return {"error": "执行记录不存在"}

            report = ReportGenerator._build_report(record)

            if format == "json":
                return ReportGenerator._generate_json(report)
            elif format == "html":
                return ReportGenerator._generate_html(report)
            elif format == "excel":
                return ReportGenerator._generate_excel(report)
            else:
                return {"error": f"不支持的报告格式: {format}"}

        finally:
            db.close()

    @staticmethod
    def _build_report(record: ExecutionRecord) -> Dict[str, Any]:
        """
        构建报告数据结构

        Args:
            record: ExecutionRecord 实例

        Returns:
            报告数据字典
        """
        analysis = json.loads(record.analysis_result) if record.analysis_result else {}
        cases = analysis.get("cases", [])

        total = analysis.get("total", 0)
        passed = analysis.get("passed", record.success_count or 0)
        failed = analysis.get("failed", record.failed_count or 0)
        pass_rate = f"{(passed / max(total, 1) * 100):.1f}%"

        return {
            "execution_id": record.id,
            "status": record.status,
            "execution_type": record.execution_type,
            "asset_id": record.asset_id,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": pass_rate,
            "duration_ms": analysis.get("duration_ms", 0),
            "created_at": str(record.created_at) if record.created_at else None,
            "cases": cases,
        }

    @staticmethod
    def _generate_json(report: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成JSON报告

        Args:
            report: 报告数据结构

        Returns:
            结构化字典
        """
        return report

    @staticmethod
    def _generate_html(report: Dict[str, Any]) -> str:
        """
        生成HTML报告

        Args:
            report: 报告数据结构

        Returns:
            HTML字符串
        """
        total = report.get("total", 0)
        passed = report.get("passed", 0)
        failed = report.get("failed", 0)
        pass_rate = report.get("pass_rate", "0%")
        duration = report.get("duration_ms", 0)
        execution_type = report.get("execution_type", "-")
        created_at = report.get("created_at", "-")

        rows = ""
        for c in report.get("cases", []):
            status_color = "#52c41a" if c.get("status") == "PASS" else "#f5222d"
            rows += f"""
            <tr>
                <td>{c.get('case_id', '')}</td>
                <td>{c.get('title', '')}</td>
                <td style="color:{status_color};font-weight:bold">{c.get('status', '')}</td>
                <td>{c.get('duration_ms', 0)}ms</td>
                <td>{c.get('error', '') or '-'}</td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>测试报告 - E{report.get('execution_id', '')}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; background: #f0f2f5; }}
.container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 32px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
h1 {{ color: #1a1a1a; margin-bottom: 4px; font-size: 24px; }}
.meta {{ color: #888; font-size: 14px; margin-bottom: 20px; }}
.summary {{ display: flex; gap: 20px; margin: 24px 0; }}
.stat {{ flex: 1; padding: 20px; border-radius: 10px; text-align: center; }}
.stat.total {{ background: #e6f7ff; border: 1px solid #91d5ff; }}
.stat.passed {{ background: #f6ffed; border: 1px solid #b7eb8f; }}
.stat.failed {{ background: #fff2f0; border: 1px solid #ffa39e; }}
.stat.rate {{ background: #fff7e6; border: 1px solid #ffd591; }}
.stat .number {{ font-size: 32px; font-weight: bold; }}
.stat.total .number {{ color: #1890ff; }}
.stat.passed .number {{ color: #52c41a; }}
.stat.failed .number {{ color: #f5222d; }}
.stat.rate .number {{ color: #fa8c16; }}
.stat .label {{ color: #666; font-size: 14px; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #f0f0f0; }}
th {{ background: #fafafa; font-weight: 600; color: #333; position: sticky; top: 0; }}
tr:hover {{ background: #fafafa; }}
.footer {{ margin-top: 24px; padding-top: 16px; border-top: 1px solid #f0f0f0; color: #999; font-size: 12px; text-align: center; }}
</style></head><body><div class="container">
<h1>测试报告</h1>
<div class="meta">
执行ID: E{report.get('execution_id', '')} | 类型: {execution_type} | 耗时: {duration}ms | 生成时间: {created_at}
</div>
<div class="summary">
<div class="stat total"><div class="number">{total}</div><div class="label">总计</div></div>
<div class="stat passed"><div class="number">{passed}</div><div class="label">通过</div></div>
<div class="stat failed"><div class="number">{failed}</div><div class="label">失败</div></div>
<div class="stat rate"><div class="number">{pass_rate}</div><div class="label">通过率</div></div>
</div>
<table><thead><tr><th>用例ID</th><th>标题</th><th>状态</th><th>耗时(ms)</th><th>错误信息</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="footer">Generated by UI-Automation ReportGenerator</div>
</div></body></html>"""

    @staticmethod
    def _generate_excel(report: Dict[str, Any]) -> str:
        """
        生成Excel报告

        Args:
            report: 报告数据结构

        Returns:
            文件路径，或错误字典
        """
        if not HAS_OPENPYXL:
            return {"error": "openpyxl not installed"}

        report_dir = settings.REPORT_DIR
        os.makedirs(report_dir, exist_ok=True)

        wb = Workbook()
        ws = wb.active
        ws.title = "测试报告"

        # 表头
        headers = ["用例ID", "标题", "状态", "耗时(ms)", "错误信息"]
        header_font = Font(name="Microsoft YaHei", bold=True, size=11, color="FFFFFF")
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center")
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9"),
        )

        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border

        # 数据行
        data_font = Font(name="Microsoft YaHei", size=10)
        pass_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
        fail_fill = PatternFill(start_color="FCE4EC", end_color="FCE4EC", fill_type="solid")

        for row_idx, case in enumerate(report.get("cases", []), 2):
            values = [
                case.get("case_id", ""),
                case.get("title", ""),
                case.get("status", ""),
                case.get("duration_ms", 0),
                case.get("error", "") or "",
            ]
            row_fill = pass_fill if case.get("status") == "PASS" else fail_fill
            for col_idx, value in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.font = data_font
                cell.border = thin_border
                cell.fill = row_fill

        # 自动列宽
        for col in ws.columns:
            max_length = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_length + 4, 50)

        # 保存文件
        execution_id = report.get("execution_id", "unknown")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_E{execution_id}_{timestamp}.xlsx"
        filepath = os.path.join(report_dir, filename)
        wb.save(filepath)

        log.info(f"Excel报告已生成: {filepath}")
        return filepath

    @staticmethod
    def generate_and_save(execution_id: int, format: str = "html") -> Optional[str]:
        """
        生成报告并保存到文件

        Args:
            execution_id: 执行ID
            format: 报告格式 (json/html/excel)

        Returns:
            文件路径，失败返回None
        """
        db = SessionLocal()
        try:
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if not record:
                log.error(f"执行记录不存在: {execution_id}")
                return None

            report = ReportGenerator._build_report(record)

            report_dir = settings.REPORT_DIR
            os.makedirs(report_dir, exist_ok=True)

            execution_id_str = report.get("execution_id", "unknown")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            if format == "json":
                filename = f"report_E{execution_id_str}_{timestamp}.json"
                filepath = os.path.join(report_dir, filename)
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)

            elif format == "html":
                filename = f"report_E{execution_id_str}_{timestamp}.html"
                filepath = os.path.join(report_dir, filename)
                html_content = ReportGenerator._generate_html(report)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(html_content)

            elif format == "excel":
                result = ReportGenerator._generate_excel(report)
                if isinstance(result, dict):
                    log.error(f"Excel生成失败: {result.get('error')}")
                    return None
                filepath = result

            else:
                log.error(f"不支持的报告格式: {format}")
                return None

            # 更新执行记录的报告路径
            record.report_path = filepath
            db.commit()

            log.info(f"报告已保存: {filepath}")
            return filepath

        except Exception as e:
            log.error(f"生成报告失败: {e}")
            db.rollback()
            return None
        finally:
            db.close()
