"""VideoAnalyzerAgent - 视频需求分析Agent

将需求视频解析为统一的RequirementContext。
使用OpenCV提取关键帧，VisionParser识别帧内容，LLM生成测试要点。
"""
import json
import logging
import os
import tempfile
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.agent.requirement.requirement_context import (
    RequirementContext, PageInfo, ElementInfo, BusinessFlow, TestPoint, Constraint,
)
from app.core.logger import log

logger = logging.getLogger(__name__)


@default_subscription
class VideoAnalyzerAgent(BaseRoutedAgent):
    """视频需求分析Agent - 将视频解析为RequirementContext"""

    def __init__(self) -> None:
        super().__init__(
            description="视频需求分析Agent，提取关键帧并识别测试要点",
            display_name="VideoAnalyzerAgent",
            capabilities=["video_parse", "frame_extract", "requirement_parse"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """分析需求视频"""
        video_path = payload.get("video_path", "")
        requirement = payload.get("requirement", "")
        task_id = payload.get("task_id", "")
        session_key = payload.get("session_key", "default")

        log.info(f"[VideoAnalyzerAgent] 开始分析视频: {video_path}")

        if not video_path or not os.path.exists(video_path):
            return {"status": "error", "error": f"视频文件不存在: {video_path}"}

        # Step 1: 提取关键帧
        frame_paths: List[str] = []
        video_meta: Dict[str, Any] = {}
        try:
            frame_paths, video_meta = self._extract_key_frames(video_path)
            log.info(
                f"[VideoAnalyzerAgent] 关键帧提取完成: {len(frame_paths)} 帧, "
                f"fps={video_meta.get('fps', 0):.1f}, "
                f"duration={video_meta.get('duration', 0):.1f}s"
            )
        except ImportError:
            log.error("[VideoAnalyzerAgent] opencv-python(cv2) not installed")
        except Exception as e:
            log.error(f"[VideoAnalyzerAgent] 关键帧提取失败: {e}")

        if not frame_paths:
            return {"status": "error", "error": "无法从视频中提取关键帧"}

        # Step 2: 使用VisionParser分析关键帧
        frame_analysis: Dict[str, Any] = {}
        try:
            from app.agent.requirement.input_router import VisionParser
            parser = VisionParser()
            result = parser.parse(frame_paths)
            frame_analysis = result.to_dict()
            log.info(
                f"[VideoAnalyzerAgent] 帧分析完成: "
                f"success={frame_analysis.get('success')}, "
                f"elements={len(frame_analysis.get('elements', []))}"
            )
        except Exception as e:
            log.warning(f"[VideoAnalyzerAgent] VisionParser失败: {e}")
            frame_analysis = {"summary": "视频帧分析失败", "elements": [], "success": False}

        # Step 3: LLM分析生成测试要点
        analysis_text = json.dumps(frame_analysis, ensure_ascii=False, default=str)
        if len(analysis_text) > 8000:
            analysis_text = analysis_text[:8000]

        system_prompt = (
            "你是视频需求分析专家。请分析以下视频关键帧的识别结果，提取测试相关信息。\n"
            "视频通常包含用户操作流程，请重点关注操作步骤和页面流转。\n"
            "返回JSON格式，包含以下字段：\n"
            '{"pages": [{"url":"","title":"页面名称","page_type":"login/list/detail/form/dashboard","description":"页面描述","elements":[]}],\n'
            '"elements": [{"name":"元素名","element_type":"button/input/select/link/text","locator":"","text":"显示文本","action":"click/input/select","required":false}],\n'
            '"business_flow": [{"flow_name":"流程名","steps":[{"action":"","target":"","description":""}],"preconditions":[],"postconditions":[]}],\n'
            '"test_points": [{"name":"测试点名","description":"描述","category":"functional/boundary/error/security","priority":"high/medium/low","test_data":{}}],\n'
            '"constraints": [{"type":"business/technical/environmental","description":"约束描述","source":"video"}],\n'
            '"summary": "整体摘要","intent": "测试意图"}\n'
            "只返回JSON，不要其他内容。"
        )

        user_prompt = analysis_text
        if requirement:
            user_prompt = f"附加需求: {requirement}\n\n帧识别结果:\n{analysis_text}"

        try:
            llm_response = await self.call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
                task_id=task_id,
                step="video_llm_analyze",
                session_key=session_key,
            )
            parsed = self._parse_llm_json(llm_response)
        except Exception as e:
            log.error(f"[VideoAnalyzerAgent] LLM分析失败: {e}")
            parsed = {
                "summary": frame_analysis.get("summary", "视频需求"),
                "intent": "video_requirement",
            }

        # Step 4: 构建RequirementContext
        context = RequirementContext(
            task_id=task_id,
            session_key=session_key,
            source_types=["video"],
            source_files=[video_path],
            raw_requirement=frame_analysis.get("summary", ""),
            summary=parsed.get("summary", frame_analysis.get("summary", "")),
            intent=parsed.get("intent", "video_requirement"),
            metadata={
                "video_path": video_path,
                "frame_count": len(frame_paths),
                "frame_paths": frame_paths,
                "fps": video_meta.get("fps", 0),
                "duration": video_meta.get("duration", 0),
                "total_frames": video_meta.get("total_frames", 0),
            },
        )

        # 填充pages
        for p in parsed.get("pages", []):
            context.pages.append(PageInfo(
                url=p.get("url", ""),
                title=p.get("title", ""),
                page_type=p.get("page_type", ""),
                description=p.get("description", ""),
                elements=p.get("elements", []),
            ))

        # 填充elements
        for e in parsed.get("elements", []):
            context.elements.append(ElementInfo(
                name=e.get("name", ""),
                element_type=e.get("element_type", ""),
                locator=e.get("locator", ""),
                text=e.get("text", ""),
                action=e.get("action", ""),
                required=e.get("required", False),
            ))

        # 填充business_flow
        for f in parsed.get("business_flow", []):
            context.business_flow.append(BusinessFlow(
                flow_name=f.get("flow_name", ""),
                steps=f.get("steps", []),
                preconditions=f.get("preconditions", []),
                postconditions=f.get("postconditions", []),
            ))

        # 若LLM未给出business_flow，用VisionParser的steps兜底
        if not context.business_flow and frame_analysis.get("steps"):
            context.business_flow.append(BusinessFlow(
                flow_name="视频操作流程",
                steps=[{"action": s, "target": "", "description": s} for s in frame_analysis.get("steps", [])],
                preconditions=[],
                postconditions=[],
            ))

        # 填充test_points
        for tp in parsed.get("test_points", []):
            context.test_points.append(TestPoint(
                name=tp.get("name", ""),
                description=tp.get("description", ""),
                category=tp.get("category", "functional"),
                priority=tp.get("priority", "medium"),
                test_data=tp.get("test_data", {}),
            ))

        # 填充constraints
        for c in parsed.get("constraints", []):
            context.constraints.append(Constraint(
                type=c.get("type", "business"),
                description=c.get("description", ""),
                source="video",
            ))

        # 清理临时帧文件
        self._cleanup_frames(frame_paths)

        log.info(
            f"[VideoAnalyzerAgent] 分析完成: "
            f"{len(context.pages)} pages, {len(context.business_flow)} flows, "
            f"{len(context.test_points)} test_points"
        )
        return {"status": "success", "context": context.to_dict()}

    def _extract_key_frames(self, video_path: str):
        """提取视频关键帧（在10%/30%/50%/70%/90%位置）"""
        import cv2

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0.0

        # 在 10%, 30%, 50%, 70%, 90% 位置提取关键帧
        frame_indices = [int(total_frames * p) for p in [0.1, 0.3, 0.5, 0.7, 0.9]]
        frame_indices = [idx for idx in frame_indices if 0 <= idx < total_frames]

        tmp_dir = tempfile.gettempdir()
        frame_paths: List[str] = []
        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if ret:
                frame_path = os.path.join(tmp_dir, f"video_frame_{idx}.jpg")
                cv2.imwrite(frame_path, frame)
                frame_paths.append(frame_path)

        cap.release()

        meta = {
            "fps": fps,
            "total_frames": total_frames,
            "duration": duration,
        }
        return frame_paths, meta

    def _cleanup_frames(self, frame_paths: List[str]) -> None:
        """清理临时帧文件"""
        for fp in frame_paths:
            try:
                if os.path.exists(fp):
                    os.remove(fp)
            except Exception as e:
                log.debug(f"[VideoAnalyzerAgent] 清理帧文件失败 {fp}: {e}")

    def _parse_llm_json(self, raw: str) -> dict:
        """解析LLM返回的JSON"""
        if isinstance(raw, dict):
            return raw
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        try:
            return json.loads(raw)
        except Exception:
            return {"summary": str(raw)[:500]}
