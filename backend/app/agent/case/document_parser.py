"""
DocumentParserAgent - 文档解析Agent

职责：解析PDF、Word、URL、Text等输入，提取需求上下文

支持：
- PDF文件：提取文本内容
- Word文件：提取文本内容
- URL：抓取页面文本
- Text：直接作为需求文本
- Swagger/OpenAPI：解析API定义
"""
import json
import os
from typing import Any, Dict, Optional
from app.core.logger import log
from app.agent.core.base import BaseAgent


class DocumentParserAgent(BaseAgent):
    """文档解析Agent"""

    agent_name = "document_parser"

    def __init__(self):
        super().__init__()
        self.model = None
        self.system_prompt = "你是一个专业的需求文档解析专家，擅长从各类文档中提取测试需求。"

    def execute(self, **kwargs) -> Any:
        """统一执行入口"""
        return self.parse(**kwargs)

    def parse(self, task_id: int, source_type: str = "text", **kwargs) -> Dict[str, Any]:
        """
        解析输入内容

        Args:
            task_id: 用例任务ID
            source_type: 输入类型
            **kwargs: file_path, url, raw_text 等

        Returns:
            {
                "requirement_context": str,
                "structured_data": dict,
                "source_type": str
            }
        """
        log.info(f"DocumentParserAgent | 开始解析 | source_type={source_type}, task_id={task_id}")

        try:
            if source_type in ("pdf", "doc", "docx", "word"):
                result = self._parse_document(source_type=source_type, **kwargs)
            elif source_type == "url":
                result = self._parse_url(**kwargs)
            elif source_type == "swagger":
                result = self._parse_swagger(**kwargs)
            elif source_type == "text":
                result = self._parse_text(**kwargs)
            else:
                result = self._parse_text(**kwargs)

            self.emit("parsed", {"task_id": task_id, "source_type": source_type})
            return result

        except Exception as e:
            log.error(f"DocumentParserAgent | 解析失败 | source_type={source_type}, error={e}")
            return {
                "requirement_context": kwargs.get("raw_text", ""),
                "structured_data": {},
                "source_type": source_type,
                "error": str(e),
            }

    def _parse_document(self, source_type: str = "", **kwargs) -> Dict[str, Any]:
        """解析文档文件（PDF/Word）"""
        file_path = kwargs.get("file_path", "")

        if not file_path or not os.path.exists(file_path):
            log.warning(f"DocumentParserAgent | 文件不存在: {file_path}")
            return {
                "requirement_context": kwargs.get("raw_text", "文件不存在"),
                "structured_data": {},
                "source_type": source_type,
            }

        text_content = ""

        if source_type == "pdf":
            text_content = self._extract_pdf(file_path)
        elif source_type in ("doc", "docx", "word"):
            text_content = self._extract_word(file_path)
        else:
            text_content = self._extract_text_file(file_path)

        return {
            "requirement_context": text_content,
            "structured_data": {"file_path": file_path, "char_count": len(text_content)},
            "source_type": source_type,
        }

    def _parse_url(self, **kwargs) -> Dict[str, Any]:
        """解析URL内容"""
        url = kwargs.get("url", "")
        if not url:
            return {
                "requirement_context": kwargs.get("raw_text", ""),
                "structured_data": {},
                "source_type": "url",
            }

        try:
            import httpx
            response = httpx.get(url, timeout=30, follow_redirects=True)
            text_content = response.text[:50000]  # 限制长度
            return {
                "requirement_context": text_content,
                "structured_data": {"url": url, "status_code": response.status_code},
                "source_type": "url",
            }
        except Exception as e:
            log.warning(f"DocumentParserAgent | URL抓取失败: {url}, error={e}")
            return {
                "requirement_context": kwargs.get("raw_text", f"URL抓取失败: {e}"),
                "structured_data": {"url": url, "error": str(e)},
                "source_type": "url",
            }

    def _parse_swagger(self, **kwargs) -> Dict[str, Any]:
        """解析Swagger/OpenAPI定义"""
        file_path = kwargs.get("file_path", "")
        raw_text = kwargs.get("raw_text", "")

        swagger_content = raw_text
        if file_path and os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                swagger_content = f.read()

        structured_data = {}
        try:
            api_def = json.loads(swagger_content)
            paths = api_def.get("paths", {})
            endpoints = []
            for path, methods in paths.items():
                for method, detail in methods.items():
                    if method.lower() in ("get", "post", "put", "delete", "patch"):
                        endpoints.append({
                            "path": path,
                            "method": method.upper(),
                            "summary": detail.get("summary", ""),
                            "parameters": detail.get("parameters", []),
                        })
            structured_data = {
                "title": api_def.get("info", {}).get("title", ""),
                "version": api_def.get("info", {}).get("version", ""),
                "endpoints": endpoints,
                "endpoint_count": len(endpoints),
            }
            # 构建需求上下文
            context_parts = [f"API: {structured_data['title']} v{structured_data['version']}"]
            for ep in endpoints:
                context_parts.append(f"  {ep['method']} {ep['path']} - {ep['summary']}")
            swagger_content = "\n".join(context_parts)
        except json.JSONDecodeError:
            log.warning("DocumentParserAgent | Swagger JSON解析失败")

        return {
            "requirement_context": swagger_content,
            "structured_data": structured_data,
            "source_type": "swagger",
        }

    def _parse_text(self, **kwargs) -> Dict[str, Any]:
        """解析纯文本输入"""
        raw_text = kwargs.get("raw_text", "")
        return {
            "requirement_context": raw_text,
            "structured_data": {"char_count": len(raw_text)},
            "source_type": "text",
        }

    def _extract_pdf(self, file_path: str) -> str:
        """提取PDF文本"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text_parts = []
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()
            return "\n".join(text_parts)
        except ImportError:
            log.warning("PyMuPDF未安装，尝试pdfplumber")
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    text_parts = [page.extract_text() or "" for page in pdf.pages]
                return "\n".join(text_parts)
            except ImportError:
                log.warning("pdfplumber也未安装，返回文件路径提示")
                return f"[PDF文件: {os.path.basename(file_path)}，请安装PyMuPDF或pdfplumber以提取内容]"
        except Exception as e:
            log.warning(f"PDF提取失败: {e}")
            return f"[PDF文件提取失败: {e}]"

    def _extract_word(self, file_path: str) -> str:
        """提取Word文本"""
        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n".join(paragraphs)
        except ImportError:
            log.warning("python-docx未安装")
            return f"[Word文件: {os.path.basename(file_path)}，请安装python-docx以提取内容]"
        except Exception as e:
            log.warning(f"Word提取失败: {e}")
            return f"[Word文件提取失败: {e}]"

    def _extract_text_file(self, file_path: str) -> str:
        """提取纯文本文件"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, "r", encoding="gbk") as f:
                    return f.read()
            except Exception as e:
                return f"[文件读取失败: {e}]"
