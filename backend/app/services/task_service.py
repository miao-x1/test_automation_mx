"""
任务服务层

合并了 TaskService 和 UnifiedTaskService，统一提供：
- 任务 CRUD（create/get/list/update/delete/rerun）
- 任务分析流程（run_analysis 旧版 / run_unified_analysis 统一版）
"""
import json
import hashlib
import os
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.models.task import Task, TaskStatus, InputMode, TaskType
from app.models.image_file import ImageFile
from app.models.analysis_result import AnalysisResult
from app.models.script import Script
from app.models.ui_element import UIElement
from app.models.test_asset import TestAsset, AssetStatus
from app.agent.factory import AgentFactory
from app.agents.factory import AgentRegistry
from app.core.logger import log


class TaskService:
    """任务服务"""

    @staticmethod
    def create_task(
        db: Session,
        task_name: str,
        input_mode: str = "image",
        page_url: str = None,
        file_path: str = None,
        original_filename: str = None,
        file_size: int = None,
        file_type: str = None,
        user_id: int = None,
        task_type: str = None,
        framework: str = None,
        platform: str = None,
        confidence: float = None,
    ) -> Task:
        """创建统一任务（支持 image/url 两种模式，可携带AI识别结果）"""
        task = Task(
            task_name=task_name,
            status=TaskStatus.PENDING,
            input_mode=InputMode(input_mode),
            page_url=page_url,
            user_id=user_id,
            created_by=user_id,
        )

        # 设置AI智能识别结果
        if task_type:
            try:
                task.task_type = TaskType(task_type)
            except ValueError:
                log.warning(f"create_task: 无效的task_type={task_type}，使用默认WEB")
        if framework:
            task.framework = framework
        if platform:
            task.platform = platform
        if confidence is not None:
            task.confidence = confidence

        db.add(task)
        db.flush()

        # 如果是图片模式，保存图片
        if input_mode == "image" and file_path:
            md5_hash = None
            try:
                with open(file_path, 'rb') as f:
                    md5_hash = hashlib.md5(f.read()).hexdigest()
            except Exception:
                pass
            image = ImageFile(
                task_id=task.id,
                original_filename=original_filename or "",
                file_path=file_path,
                file_size=file_size or 0,
                file_type=file_type or "",
                md5_hash=md5_hash,
                user_id=user_id,
                created_by=user_id,
            )
            db.add(image)

        db.commit()
        db.refresh(task)
        log.info(f"统一任务创建成功 | ID: {task.id}, 模式: {input_mode}")
        return task
    
    @staticmethod
    def get_task(db: Session, task_id: int) -> Optional[Task]:
        """获取任务（强制刷新，确保读到最新数据）"""
        db.expire_all()
        return db.query(Task).filter(Task.id == task_id).first()
    
    @staticmethod
    def get_task_list(db: Session, skip: int = 0, limit: int = 20, user_id: int = None) -> tuple[list[Task], int]:
        """获取任务列表（支持用户隔离）"""
        db.expire_all()
        query = db.query(Task)
        if user_id is not None:
            query = query.filter(Task.user_id == user_id)
        total = query.count()
        items = query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()
        return items, total
    
    @staticmethod
    def update_task_status(db: Session, task_id: int, status: TaskStatus, **kwargs) -> Optional[Task]:
        """更新任务状态"""
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.status = status
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            db.commit()
            db.refresh(task)
            log.info(f"任务状态更新 | ID: {task_id}, 状态: {status}")
        return task

    @staticmethod
    def delete_task(db: Session, task_id: int) -> bool:
        """
        删除任务及其关联数据和文件

        删除顺序：
        1. 删除uploads目录对应的图片文件
        2. 删除Milvus中的向量数据
        3. 删除数据库记录（级联删除image_file, analysis_result, script）
        """
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return False

        # 删除关联的图片文件
        images = db.query(ImageFile).filter(ImageFile.task_id == task_id).all()
        for image in images:
            try:
                if os.path.exists(image.file_path):
                    os.remove(image.file_path)
                    log.info(f"删除图片文件 | {image.file_path}")
            except OSError as e:
                log.warning(f"删除图片文件失败 | {image.file_path}: {e}")

        # 删除脚本文件（如果存在）
        script = db.query(Script).filter(Script.task_id == task_id).first()
        if script and script.file_path:
            try:
                if os.path.exists(script.file_path):
                    os.remove(script.file_path)
                    log.info(f"删除脚本文件 | {script.file_path}")
            except OSError as e:
                log.warning(f"删除脚本文件失败 | {script.file_path}: {e}")

        # 删除Milvus中的向量数据
        try:
            from app.db.milvus_client import get_milvus_client, COLLECTION_NAME, CASE_COLLECTION_NAME, SCRIPT_COLLECTION_NAME
            client = get_milvus_client()
            if client:
                # 删除元素向量
                try:
                    client.delete(COLLECTION_NAME, filter=f'task_id == {task_id}')
                    log.info(f"删除元素向量 | task_id={task_id}")
                except Exception as e:
                    log.warning(f"删除元素向量失败 | task_id={task_id}: {e}")
                # 删除用例向量
                try:
                    if client.has_collection(CASE_COLLECTION_NAME):
                        client.delete(CASE_COLLECTION_NAME, filter=f'task_id == {task_id}')
                        log.info(f"删除用例向量 | task_id={task_id}")
                except Exception as e:
                    log.warning(f"删除用例向量失败 | task_id={task_id}: {e}")
                # 删除脚本向量
                try:
                    if client.has_collection(SCRIPT_COLLECTION_NAME):
                        client.delete(SCRIPT_COLLECTION_NAME, filter=f'task_id == {task_id}')
                        log.info(f"删除脚本向量 | task_id={task_id}")
                except Exception as e:
                    log.warning(f"删除脚本向量失败 | task_id={task_id}: {e}")
        except Exception as e:
            log.warning(f"Milvus连接失败，跳过向量删除: {e}")

        # 删除数据库记录（级联删除关联表）
        db.delete(task)
        db.commit()
        log.info(f"任务删除成功 | ID: {task_id}")
        return True

    @staticmethod
    def rerun_task(db: Session, task_id: int) -> Optional[Task]:
        """
        重新执行任务：清除旧的分析结果、脚本和UI元素，重置状态为pending
        """
        from app.models.ui_element import UIElement
        from app.models.page_element import PageElement

        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return None

        # 删除旧的分析结果
        db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).delete()

        # 删除旧的UI元素（Vision分析结果）
        db.query(UIElement).filter(UIElement.task_id == task_id).delete()

        # 删除旧的页面元素（DOM抓取结果）
        db.query(PageElement).filter(PageElement.task_id == task_id).delete()

        # 删除旧的脚本
        old_script = db.query(Script).filter(Script.task_id == task_id).first()
        if old_script:
            if old_script.file_path and os.path.exists(old_script.file_path):
                try:
                    os.remove(old_script.file_path)
                except OSError:
                    pass
            db.delete(old_script)

        # 重置任务状态
        task.status = TaskStatus.PENDING
        task.error_message = None
        db.commit()
        db.refresh(task)

        log.info(f"任务重置成功 | ID: {task_id}")
        return task

    @staticmethod
    def get_script_content(db: Session, task_id: int) -> Optional[str]:
        """获取任务的脚本内容"""
        script = db.query(Script).filter(Script.task_id == task_id).first()
        if script:
            return script.script_content
        return None
    
    @staticmethod
    async def run_analysis(task_id: int) -> AsyncGenerator[str, None]:
        """
        执行分析流程（SSE事件流）

        重要：此方法使用独立的数据库会话，不依赖API层的请求级会话。
        因为SSE是长连接流式响应，请求级会话生命周期无法覆盖整个分析过程。
        """
        from app.db.database import SessionLocal
        from app.models.ui_element import UIElement

        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                yield json.dumps({"error": "任务不存在"}, ensure_ascii=False)
                return

            image = db.query(ImageFile).filter(ImageFile.task_id == task_id).first()
            if not image:
                yield json.dumps({"error": "任务没有关联图片"}, ensure_ascii=False)
                return

            # 更新状态为处理中
            task.status = TaskStatus.PROCESSING
            db.commit()

            # 创建Agent
            agent = AgentFactory.create_agent()
            analysis_data = None

            try:
                # 执行分析
                async for step_data in agent.analyze_image(task_id, image.file_path):
                    if step_data.get("step") == "result":
                        analysis_data = step_data.get("data")
                    yield json.dumps(step_data, ensure_ascii=False)

                # 保存分析结果
                if analysis_data:
                    # 保存AnalysisResult
                    analysis_result = AnalysisResult(
                        task_id=task_id,
                        agent_type=agent.agent_type,
                        page_type=analysis_data.get("page_type"),
                        elements_json=json.dumps(analysis_data.get("elements", []), ensure_ascii=False),
                        interactions_json=json.dumps(analysis_data.get("interactions", []), ensure_ascii=False),
                        layout_json=json.dumps(analysis_data.get("layout", {}), ensure_ascii=False),
                        analysis_summary=f"识别到 {len(analysis_data.get('elements', []))} 个UI元素",
                        raw_output=json.dumps(analysis_data, ensure_ascii=False)
                    )
                    db.add(analysis_result)

                    # 保存UI元素到ui_element表
                    elements = analysis_data.get("elements", [])
                    for el in elements:
                        ui_el = UIElement(
                            task_id=task_id,
                            element_name=el.get("name", ""),
                            element_type=el.get("type", "unknown"),
                            element_text=el.get("text", "")
                        )
                        db.add(ui_el)

                    log.info(f"Task {task_id} | 保存 {len(elements)} 个UI元素到数据库")

                    yield json.dumps({"step": "生成脚本", "progress": 95, "message": "正在生成Playwright测试脚本..."}, ensure_ascii=False)

                    test_script_content = await agent.generate_test_script(analysis_data)

                    script = Script(
                        task_id=task_id,
                        script_type="playwright",
                        script_content=test_script_content,
                        script_language="python"
                    )
                    db.add(script)

                    # 自动创建测试资产（脚本）
                    asset = TestAsset(
                        title=f"任务{task_id} - Playwright脚本",
                        asset_type=task.task_type or "web",
                        task_id=task_id,
                        script_content=test_script_content,
                        script_language="python",
                        source_type="ai",
                        status=AssetStatus.READY,
                        user_id=task.user_id,
                        created_by=task.user_id,
                    )
                    db.add(asset)

                    task.status = TaskStatus.SUCCESS
                    db.commit()
                    log.info(f"任务分析完成并已提交 | ID: {task_id}")

                    yield json.dumps({"step": "完成", "progress": 100, "message": "所有步骤已完成", "test_script": test_script_content}, ensure_ascii=False)

            except Exception as e:
                log.error(f"任务分析失败 | ID: {task_id}, 错误: {e}")
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
                yield json.dumps({"error": str(e)}, ensure_ascii=False)

        finally:
            db.close()

    @staticmethod
    async def run_unified_analysis(task_id: int) -> AsyncGenerator[str, None]:
        """
        执行统一分析流程（SSE事件流）

        核心逻辑：两种模式最终都通过DOM抓取获取真实定位器
        - image: Vision识别URL → DOM抓取 → 融合 → 用例 → 脚本
                 没识别到URL → 仅Vision展示，不生成脚本
        - url: 直接DOM抓取 → 融合 → 用例 → 脚本
        """
        from app.db.database import SessionLocal
        from app.agent.vision.element_agent import ElementAgent
        from app.agent.vision.page_crawler_agent import PageCrawlerAgent
        from app.agent.vision.element_merge_agent import ElementMergeAgent
        from app.agent.case.agent_selector import AgentSelector
        from app.agent.vision.playwright_agent import PlaywrightAgent

        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                yield json.dumps({"error": "任务不存在"}, ensure_ascii=False)
                return

            task.status = TaskStatus.PROCESSING
            db.commit()

            vision_elements = []
            dom_elements = []
            page_url = task.page_url
            screenshot_path = None
            vision_only = False  # 标记是否为仅Vision模式

            try:
                # ===== 阶段1: 数据采集 (0-50%) =====
                if task.input_mode == InputMode.IMAGE:
                    # 图片模式：先Vision分析，识别地址栏URL
                    yield json.dumps({"step": "Vision分析开始", "progress": 5, "message": "开始Vision分析截图..."}, ensure_ascii=False)

                    vision_page_url = None
                    async for msg in TaskService._run_vision(db, task_id, task):
                        yield TaskService._remap_progress(msg, 0, 25)
                        try:
                            data = json.loads(msg)
                            if data.get("step") == "result" and data.get("data"):
                                vision_elements = data["data"].get("elements", [])
                                vision_page_url = data["data"].get("page_url")
                        except Exception:
                            pass

                    yield json.dumps({"step": "Vision分析完成", "progress": 25, "message": f"Vision分析完成，识别到 {len(vision_elements)} 个元素"}, ensure_ascii=False)

                    # 确定DOM抓取URL：优先手动输入，其次Vision识别
                    crawl_url = page_url or vision_page_url

                    if crawl_url:
                        # 识别到URL → 走DOM抓取流程（和URL模式一样）
                        if vision_page_url and not page_url:
                            yield json.dumps({"step": "识别到URL", "progress": 27, "message": f"从截图地址栏识别到URL: {vision_page_url}，开始抓取DOM..."}, ensure_ascii=False)
                            task.page_url = vision_page_url
                            db.commit()
                        else:
                            yield json.dumps({"step": "DOM抓取", "progress": 27, "message": f"开始抓取页面DOM: {crawl_url}"}, ensure_ascii=False)

                        async for msg in TaskService._run_crawl(db, task_id, crawl_url):
                            yield TaskService._remap_progress(msg, 27, 50)
                            try:
                                data = json.loads(msg)
                                if data.get("step") == "result" and data.get("data"):
                                    dom_elements = data["data"].get("elements", [])
                                    if not screenshot_path:
                                        screenshot_path = data["data"].get("screenshot_path")
                            except Exception:
                                pass
                    else:
                        # 未识别到URL → 仅Vision模式，不生成脚本
                        vision_only = True
                        yield json.dumps({
                            "step": "未识别到URL",
                            "progress": 50,
                            "message": "未从截图地址栏识别到URL，仅展示Vision分析结果，不生成测试脚本",
                            "warning": "未识别到页面URL，无法获取真实DOM定位器。如需生成可执行脚本，请提供页面URL或上传包含地址栏的截图。",
                        }, ensure_ascii=False)

                        # 保存Vision元素到ui_element表
                        for el in vision_elements:
                            ui_el = UIElement(
                                task_id=task_id,
                                name=el.get("name", ""),
                                type=el.get("type", "unknown"),
                                text=el.get("text"),
                                source="vision",
                                confidence=el.get("confidence"),
                            )
                            db.add(ui_el)
                        db.commit()

                        task.status = TaskStatus.SUCCESS
                        task.error_message = "Vision-only模式：未识别到URL，仅展示视觉分析结果，未生成测试脚本"
                        db.commit()

                        yield json.dumps({
                            "step": "任务完成",
                            "progress": 100,
                            "message": "Vision分析完成（未识别到URL，不生成脚本）",
                            "vision_only": True,
                            "element_count": len(vision_elements),
                        }, ensure_ascii=False)
                        return

                elif task.input_mode == InputMode.URL:
                    # URL模式：直接DOM抓取
                    yield json.dumps({"step": "DOM抓取", "progress": 5, "message": f"开始抓取页面DOM: {page_url}"}, ensure_ascii=False)

                    async for msg in TaskService._run_crawl(db, task_id, page_url):
                        yield TaskService._remap_progress(msg, 0, 40)
                        try:
                            data = json.loads(msg)
                            if data.get("step") == "result" and data.get("data"):
                                dom_elements = data["data"].get("elements", [])
                                screenshot_path = data["data"].get("screenshot_path")
                        except Exception:
                            pass

                    # 如果有截图，也做Vision分析用于融合
                    if screenshot_path:
                        image = db.query(ImageFile).filter(ImageFile.task_id == task_id).first()
                        if not image:
                            img = ImageFile(
                                task_id=task_id,
                                original_filename="screenshot.png",
                                file_path=screenshot_path,
                                file_size=0,
                                file_type="image/png",
                            )
                            db.add(img)
                            db.commit()

                        yield json.dumps({"step": "Vision分析", "progress": 42, "message": "开始Vision分析截图..."}, ensure_ascii=False)
                        async for msg in TaskService._run_vision(db, task_id, task):
                            yield TaskService._remap_progress(msg, 40, 50)
                            try:
                                data = json.loads(msg)
                                if data.get("step") == "result" and data.get("data"):
                                    vision_elements = data["data"].get("elements", [])
                            except Exception:
                                pass

                # ===== 阶段2: 元素融合 (50-60%) =====
                yield json.dumps({"step": "开始融合元素", "progress": 50, "message": "开始融合Vision和DOM元素..."}, ensure_ascii=False)

                merge_agent = ElementMergeAgent()
                merged_elements = []
                async for step_data in merge_agent.merge_elements(task_id, vision_elements, dom_elements):
                    yield TaskService._remap_progress(json.dumps(step_data, ensure_ascii=False), 50, 60)
                    if step_data.get("step") == "result":
                        merged_elements = step_data.get("data", {}).get("elements", [])

                # 保存融合后的统一元素到ui_element表
                for el in merged_elements:
                    ui_el = UIElement(
                        task_id=task_id,
                        name=el.get("name", ""),
                        type=el.get("type", "unknown"),
                        text=el.get("text"),
                        source=el.get("source", "merge"),
                        locator=el.get("locator"),
                        xpath=el.get("xpath"),
                        css_selector=el.get("css_selector"),
                        element_id=el.get("element_id"),
                        element_class=el.get("element_class"),
                        element_name=el.get("element_name"),
                        placeholder=el.get("placeholder"),
                        href=el.get("href"),
                        aria_label=el.get("aria_label"),
                        role=el.get("role"),
                        data_testid=el.get("data_testid"),
                        page_url=el.get("page_url"),
                        confidence=el.get("confidence"),
                    )
                    db.add(ui_el)

                db.commit()
                log.info(f"Task {task_id} | 保存 {len(merged_elements)} 个统一元素")

                # ===== 阶段3: 生成测试用例 (60-75%) =====
                yield json.dumps({"step": "生成测试用例", "progress": 60, "message": "正在生成测试用例..."}, ensure_ascii=False)

                case_agent = AgentRegistry.create("case_agent")
                cases = []
                async for step_data in case_agent.generate_cases(task_id, merged_elements):
                    yield TaskService._remap_progress(json.dumps(step_data, ensure_ascii=False), 60, 75)
                    if step_data.get("step") == "result":
                        cases = step_data.get("data", {}).get("cases", [])

                # ===== 阶段4: 生成Playwright脚本 (75-95%) =====
                yield json.dumps({"step": "生成Playwright脚本", "progress": 75, "message": "正在生成Playwright脚本..."}, ensure_ascii=False)

                # 重新获取最新的page_url（可能被Vision识别更新过）
                db.refresh(task)
                final_page_url = task.page_url or page_url

                script_agent = PlaywrightAgent()
                script_content = ""
                async for step_data in script_agent.generate_script(task_id, merged_elements, cases, final_page_url):
                    yield TaskService._remap_progress(json.dumps(step_data, ensure_ascii=False), 75, 95)
                    if step_data.get("step") == "result":
                        script_content = step_data.get("data", {}).get("script", "")

                # 保存脚本
                if script_content:
                    script = Script(
                        task_id=task_id,
                        script_type="playwright",
                        script_content=script_content,
                        script_language="python",
                    )
                    db.add(script)

                    # 自动创建测试资产（脚本）
                    asset = TestAsset(
                        title=f"任务{task_id} - Playwright脚本",
                        asset_type=task.task_type or "web",
                        task_id=task_id,
                        script_content=script_content,
                        script_language="python",
                        source_type="ai",
                        status=AssetStatus.READY,
                        user_id=task.user_id,
                        created_by=task.user_id,
                    )
                    db.add(asset)

                # 自动创建测试资产（用例）
                if cases:
                    case_asset = TestAsset(
                        title=f"任务{task_id} - 测试用例",
                        asset_type=task.task_type or "web",
                        task_id=task_id,
                        input_config=json.dumps({
                            "cases": cases,
                            "element_count": len(merged_elements),
                        }, ensure_ascii=False),
                        source_type="ai",
                        status=AssetStatus.READY,
                        user_id=task.user_id,
                        created_by=task.user_id,
                    )
                    db.add(case_asset)

                task.status = TaskStatus.SUCCESS
                db.commit()
                log.info(f"统一任务完成 | ID: {task_id}")

                yield json.dumps({
                    "step": "任务完成",
                    "progress": 100,
                    "message": "任务完成",
                    "test_script": script_content,
                    "element_count": len(merged_elements),
                    "case_count": len(cases),
                }, ensure_ascii=False)

            except Exception as e:
                import traceback
                log.error(f"统一任务失败 | ID: {task_id}, 错误: {e}\n{traceback.format_exc()}")
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
                yield json.dumps({"error": str(e)}, ensure_ascii=False)

        finally:
            # 如果任务仍为processing状态，说明异常中断，回滚为failed
            try:
                task = db.query(Task).filter(Task.id == task_id).first()
                if task and task.status == TaskStatus.PROCESSING:
                    task.status = TaskStatus.FAILED
                    task.error_message = "分析流程异常中断（SSE连接断开）"
                    db.commit()
                    log.warning(f"Task {task_id} | SSE连接断开，任务状态回滚为failed")
            except Exception:
                pass
            db.close()

    @staticmethod
    async def _run_vision(db: Session, task_id: int, task: Task) -> AsyncGenerator[str, None]:
        """执行Vision分析子流程（进度由外层统一管理）"""
        image = db.query(ImageFile).filter(ImageFile.task_id == task_id).first()
        if not image:
            yield json.dumps({"step": "Vision跳过", "progress": 5, "message": "无图片，跳过Vision分析"}, ensure_ascii=False)
            return

        from app.agent.vision.element_agent import ElementAgent
        agent = ElementAgent()
        analysis_data = None

        async for step_data in agent.analyze_image(task_id, image.file_path):
            yield json.dumps(step_data, ensure_ascii=False)
            if step_data.get("step") == "result":
                analysis_data = step_data.get("data")

        # 保存AnalysisResult
        if analysis_data:
            existing = db.query(AnalysisResult).filter(AnalysisResult.task_id == task_id).first()
            if not existing:
                analysis_result = AnalysisResult(
                    task_id=task_id,
                    agent_type="element",
                    page_type=analysis_data.get("page_type"),
                    elements_json=json.dumps(analysis_data.get("elements", []), ensure_ascii=False),
                    interactions_json=json.dumps(analysis_data.get("interactions", []), ensure_ascii=False),
                    layout_json=json.dumps(analysis_data.get("layout", {}), ensure_ascii=False),
                    analysis_summary=f"识别到 {len(analysis_data.get('elements', []))} 个UI元素",
                    raw_output=json.dumps(analysis_data, ensure_ascii=False),
                )
                db.add(analysis_result)
                db.commit()

    @staticmethod
    async def _run_crawl(db: Session, task_id: int, url: str) -> AsyncGenerator[str, None]:
        """执行DOM抓取子流程（进度由外层统一管理）"""
        from app.agent.vision.page_crawler_agent import PageCrawlerAgent
        agent = PageCrawlerAgent()
        crawl_data = None

        async for step_data in agent.crawl_page(task_id, url):
            yield json.dumps(step_data, ensure_ascii=False)
            if step_data.get("step") == "result":
                crawl_data = step_data.get("data")

    @staticmethod
    def _remap_progress(msg: str, start: int, end: int) -> str:
        """将子Agent的0-100进度重映射到全局start-end范围"""
        try:
            data = json.loads(msg)
            if "progress" in data:
                sub_progress = data["progress"]
                # 将0-100映射到start-end
                data["progress"] = int(start + (end - start) * sub_progress / 100)
                return json.dumps(data, ensure_ascii=False)
        except Exception:
            pass
        return msg
