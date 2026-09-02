"""
执行调度器（基于资产类型路由）

职责：
  - 从 TestAsset 调度执行
  - 根据 asset_type 路由到对应 runner
  - 收集结果、生成报告

路由规则：
  - api    → _run_api  (CaseRunner + HttpRunner)
  - web    → _run_web  (placeholder)
  - android → _run_android (placeholder)

流程：
  dispatch_by_asset → create record → route → run → collect → report
  dispatch_batch   → create record → group by type → route each → collect → report
"""
import time
import asyncio
from typing import Dict, List, Optional, Any

from app.models.test_asset import TestAsset
from app.models.execution_record import ExecutionRecord, ExecutionStatus, ExecutionType
from app.services.execution.context import ExecutionContext
from app.services.execution.case_runner import CaseRunner
from app.services.execution.http_runner import HttpRunner
from app.services.execution.assertion_engine import AssertionEngine
from app.services.execution.result_writer import ResultWriter
from app.services.execution.report_generator import ReportGenerator
from app.db.database import SessionLocal
from app.core.logger import log


class ExecutionDispatcher:
    """执行调度器 - 基于资产类型路由"""

    # 资产类型 → 执行方法 映射
    _RUNNER_MAP = {
        "api": "_run_api",
        "web": "_run_web",
        "android": "_run_android",
    }

    @staticmethod
    async def dispatch_by_asset(
        asset_id: int,
        user_id: int,
        env: str = "test",
        base_url: str = "http://localhost:8080",
        progress_queue: Optional[asyncio.Queue] = None,
    ) -> Dict:
        """
        执行单个 TestAsset

        Args:
            asset_id: 测试资产ID
            user_id: 用户ID
            env: 执行环境
            base_url: 基础URL
            progress_queue: 进度队列

        Returns:
            {"execution_id": int, "status": str, "asset_id": int}
        """
        db = SessionLocal()
        try:
            # 1. 加载 TestAsset
            asset = db.query(TestAsset).filter(
                TestAsset.id == asset_id,
                TestAsset.is_deleted == False,
            ).first()

            if not asset:
                log.error(f"ExecutionDispatcher | 资产不存在: {asset_id}")
                return {"execution_id": None, "status": "error", "asset_id": asset_id, "error": "资产不存在"}

            # 2. 创建 ExecutionRecord（status=WAITING）
            execution_type = asset.asset_type if asset.asset_type else "api"
            record = ExecutionRecord(
                asset_id=asset.id,
                execution_type=execution_type,
                status=ExecutionStatus.WAITING,
                user_id=user_id,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            execution_id = record.id

            if progress_queue:
                try:
                    progress_queue.put_nowait({
                        "type": "executing",
                        "payload": {"asset_id": asset.id, "title": asset.title, "execution_id": execution_id},
                    })
                except Exception:
                    pass

            # 3. 路由到对应 runner
            runner_method = ExecutionDispatcher._RUNNER_MAP.get(execution_type, "_run_api")
            runner_fn = getattr(ExecutionDispatcher, runner_method)

            try:
                # 更新状态为 RUNNING
                record.status = ExecutionStatus.RUNNING
                record.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
                db.commit()

                result = await runner_fn(asset, env, base_url)

                # 4. 更新 ExecutionRecord
                run_status = result.get("status", "error")
                if run_status in ("PASS", "pass"):
                    record.status = ExecutionStatus.SUCCESS
                    record.success_count = 1
                    record.failed_count = 0
                elif run_status in ("FAIL", "fail"):
                    record.status = ExecutionStatus.FAILED
                    record.success_count = 0
                    record.failed_count = 1
                elif run_status == "not_implemented":
                    record.status = ExecutionStatus.FAILED
                    record.error_message = result.get("message", "未实现")
                else:
                    record.status = ExecutionStatus.FAILED
                    record.error_message = result.get("error", "执行失败")

                record.end_time = time.strftime("%Y-%m-%d %H:%M:%S")
                record.duration = result.get("duration_ms", 0) / 1000.0
                if result.get("error"):
                    record.error_message = result.get("error")

                # 更新资产执行状态
                asset.execution_state = __import__("json").dumps({
                    "last_run_status": run_status,
                    "last_run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "last_run_id": str(execution_id),
                }, ensure_ascii=False)

                db.commit()

            except Exception as e:
                record.status = ExecutionStatus.FAILED
                record.error_message = str(e)
                record.end_time = time.strftime("%Y-%m-%d %H:%M:%S")
                db.commit()
                log.error(f"ExecutionDispatcher | 执行失败: asset_id={asset_id}, error={e}")

            if progress_queue:
                try:
                    progress_queue.put_nowait({
                        "type": "completed",
                        "payload": {"execution_id": execution_id, "status": record.status},
                    })
                except Exception:
                    pass

            return {
                "execution_id": record.id,
                "status": record.status,
                "asset_id": asset_id,
            }

        except Exception as e:
            log.error(f"ExecutionDispatcher | dispatch_by_asset 异常: {e}")
            return {"execution_id": None, "status": "error", "asset_id": asset_id, "error": str(e)}
        finally:
            db.close()

    @staticmethod
    async def dispatch_batch(
        asset_ids: List[int],
        user_id: int,
        env: str = "test",
        base_url: str = "http://localhost:8080",
        progress_queue: Optional[asyncio.Queue] = None,
    ) -> Dict:
        """
        批量执行多个 TestAsset

        Args:
            asset_ids: 测试资产ID列表
            user_id: 用户ID
            env: 执行环境
            base_url: 基础URL
            progress_queue: 进度队列

        Returns:
            {"execution_id": int, "status": str, "results": [...]}
        """
        db = SessionLocal()
        try:
            # 1. 加载所有 TestAsset
            assets = db.query(TestAsset).filter(
                TestAsset.id.in_(asset_ids),
                TestAsset.is_deleted == False,
            ).all()

            if not assets:
                return {"execution_id": None, "status": "error", "results": [], "error": "无可用资产"}

            # 2. 创建单个 ExecutionRecord（execution_type=batch）
            record = ExecutionRecord(
                execution_type=ExecutionType.BATCH,
                status=ExecutionStatus.WAITING,
                user_id=user_id,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            execution_id = record.id

            # 3. 按 asset_type 分组
            groups: Dict[str, List[TestAsset]] = {}
            for asset in assets:
                asset_type = asset.asset_type or "api"
                groups.setdefault(asset_type, []).append(asset)

            # 4. 逐组执行
            record.status = ExecutionStatus.RUNNING
            record.start_time = time.strftime("%Y-%m-%d %H:%M:%S")
            db.commit()

            all_results = []
            total_start = time.time()

            for asset_type, group_assets in groups.items():
                runner_method = ExecutionDispatcher._RUNNER_MAP.get(asset_type, "_run_api")
                runner_fn = getattr(ExecutionDispatcher, runner_method)

                for i, asset in enumerate(group_assets):
                    if progress_queue:
                        try:
                            progress_queue.put_nowait({
                                "type": "executing",
                                "payload": {
                                    "index": i + 1,
                                    "total": len(group_assets),
                                    "asset_id": asset.id,
                                    "title": asset.title,
                                    "asset_type": asset_type,
                                    "execution_id": execution_id,
                                },
                            })
                        except Exception:
                            pass

                    try:
                        result = await runner_fn(asset, env, base_url)
                        result["asset_id"] = asset.id
                        result["title"] = asset.title
                        result["asset_type"] = asset_type
                        all_results.append(result)

                        # 更新资产执行状态
                        asset.execution_state = __import__("json").dumps({
                            "last_run_status": result.get("status", "unknown"),
                            "last_run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "last_run_id": str(execution_id),
                        }, ensure_ascii=False)

                    except Exception as e:
                        all_results.append({
                            "asset_id": asset.id,
                            "title": asset.title,
                            "asset_type": asset_type,
                            "status": "error",
                            "error": str(e),
                        })

            # 5. 汇总结果，更新 ExecutionRecord
            total_duration_ms = int((time.time() - total_start) * 1000)
            passed = sum(1 for r in all_results if r.get("status") in ("PASS", "pass"))
            failed = len(all_results) - passed

            record.success_count = passed
            record.failed_count = failed
            record.duration = total_duration_ms / 1000.0
            record.end_time = time.strftime("%Y-%m-%d %H:%M:%S")
            record.status = ExecutionStatus.SUCCESS if failed == 0 else ExecutionStatus.FAILED

            # 保存结果详情
            ResultWriter.save_all_results(execution_id, all_results, total_duration_ms)

            db.commit()

            # 6. 生成报告（持久化到文件，更新 report_path）
            try:
                ReportGenerator.generate_and_save(execution_id, format="html")
            except Exception as e:
                log.warning(f"ExecutionDispatcher | 报告生成失败: {e}")

            if progress_queue:
                try:
                    progress_queue.put_nowait({
                        "type": "completed",
                        "payload": {
                            "execution_id": execution_id,
                            "total": len(all_results),
                            "passed": passed,
                            "failed": failed,
                        },
                    })
                except Exception:
                    pass

            return {
                "execution_id": execution_id,
                "status": record.status,
                "results": all_results,
            }

        except Exception as e:
            log.error(f"ExecutionDispatcher | dispatch_batch 异常: {e}")
            return {"execution_id": None, "status": "error", "results": [], "error": str(e)}
        finally:
            db.close()

    @staticmethod
    async def _run_api(asset: TestAsset, env: str, base_url: str) -> Dict:
        """
        运行 API 测试（CaseRunner + HttpRunner）

        Args:
            asset: TestAsset 实例
            env: 执行环境
            base_url: 基础URL

        Returns:
            {"status": "PASS"|"FAIL"|"error", "duration_ms": int, "assertions": [...], ...}
        """
        try:
            # 1. 加载资产内容
            exec_data = asset.to_execution_json()
            if not exec_data:
                return {"status": "error", "error": "无执行内容", "duration_ms": 0, "assertions": []}

            # 2. 构建执行上下文
            context = ExecutionContext(
                env=env,
                base_url=base_url,
                variables=exec_data.get("variables", {}),
            )

            # 3. 构建用例格式供 CaseRunner 使用
            case = {
                "case_id": exec_data.get("execution_case_id", f"EX_{asset.id}"),
                "title": asset.title,
                "type": "api",
                "steps": [],
                "assertions": exec_data.get("assertions", []),
            }

            # 从 request 构建 steps
            request = exec_data.get("request", {})
            if request:
                step = {
                    "action": request.get("method", "POST").upper(),
                    "url": request.get("url", ""),
                    "headers": request.get("headers", {}),
                    "body": request.get("body"),
                    "timeout": request.get("timeout", 30),
                }
                case["steps"].append(step)

            # 4. 使用 CaseRunner 执行
            runner = CaseRunner()
            start = time.time()
            case_result = await asyncio.to_thread(runner.run, case, context)
            duration_ms = int((time.time() - start) * 1000)

            # 5. 使用 AssertionEngine 执行断言（CaseRunner 内部已执行，此处取结果）
            assertion_result = case_result.get("assertion_result", {})

            # 6. 汇总结果
            status = case_result.get("status", "error")

            result = {
                "status": status,
                "duration_ms": case_result.get("duration_ms", duration_ms),
                "assertions": assertion_result.get("results", []),
                "assertion_passed": assertion_result.get("passed", False),
                "assertion_passed_count": assertion_result.get("passed_count", 0),
                "assertion_failed_count": assertion_result.get("failed_count", 0),
                "step_results": case_result.get("step_results", []),
                "error": case_result.get("error"),
            }

            log.info(f"ExecutionDispatcher._run_api | asset_id={asset.id}, status={status}, duration={duration_ms}ms")
            return result

        except Exception as e:
            log.error(f"ExecutionDispatcher._run_api | asset_id={asset.id}, error={e}")
            return {"status": "error", "error": str(e), "duration_ms": 0, "assertions": []}

    @staticmethod
    async def _run_web(asset: TestAsset, env: str, base_url: str) -> Dict:
        """
        Web runner - 运行 Playwright 脚本

        从 asset.script_content 加载脚本，动态导入 test_* 函数，
        用 Playwright chromium 逐个执行，聚合结果。

        Returns:
            {"status": "PASS"|"FAIL"|"error", "duration_ms": int,
             "error": str|None, "assertion_result": {...}, "sub_tests": [...]}
        """
        import asyncio
        script_content = asset.script_content or ""
        if not script_content:
            return {"status": "error", "error": "无脚本内容", "duration_ms": 0,
                    "assertion_result": {"passed": False, "passed_count": 0, "failed_count": 1, "results": []}}

        result = await asyncio.to_thread(
            ExecutionDispatcher._run_web_sync, asset, script_content, base_url
        )
        return result

    @staticmethod
    def _run_web_sync(asset: TestAsset, script_content: str, base_url: str) -> Dict:
        """同步执行 Playwright 脚本（在线程中调用）"""
        import importlib.util
        import sys
        import tempfile
        import os
        import time as _t
        import traceback

        start = _t.time()
        sub_tests = []
        module = None
        tmp_path = None

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
                f.write(script_content)
                tmp_path = f.name

            mod_name = f"_web_script_{asset.id}_{int(_t.time())}"
            spec = importlib.util.spec_from_file_location(mod_name, tmp_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[mod_name] = module
                spec.loader.exec_module(module)
            else:
                return {"status": "error", "error": "脚本加载失败", "duration_ms": 0,
                        "assertion_result": {"passed": False, "passed_count": 0, "failed_count": 1, "results": []}}
        except Exception as e:
            return {"status": "error", "error": f"脚本加载异常: {e}",
                    "duration_ms": int((_t.time() - start) * 1000),
                    "assertion_result": {"passed": False, "passed_count": 0, "failed_count": 1, "results": []}}
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        test_funcs = []
        if module:
            for name in dir(module):
                if name.startswith("test_") and callable(getattr(module, name)):
                    test_funcs.append((name, getattr(module, name)))

        if not test_funcs:
            return {"status": "error", "error": "脚本中未找到 test_* 函数",
                    "duration_ms": int((_t.time() - start) * 1000),
                    "assertion_result": {"passed": False, "passed_count": 0, "failed_count": 1, "results": []}}

        from playwright.sync_api import sync_playwright

        first_error = None
        passed_count = 0
        failed_count = 0
        assertion_results = []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()

                for func_name, func in test_funcs:
                    test_start = _t.time()
                    test_status = "PASS"
                    test_error = None
                    try:
                        func(page)
                    except Exception as e:
                        test_status = "FAIL"
                        test_error = f"{type(e).__name__}: {e}"
                        if first_error is None:
                            first_error = test_error
                        log.warning(f"_run_web | {func_name} 失败: {test_error}\n{traceback.format_exc()}")

                    test_ms = int((_t.time() - test_start) * 1000)
                    if test_status == "PASS":
                        passed_count += 1
                    else:
                        failed_count += 1
                    assertion_results.append({
                        "name": func_name,
                        "passed": test_status == "PASS",
                        "error": test_error,
                        "duration_ms": test_ms,
                    })
                    sub_tests.append({
                        "case_id": func_name,
                        "title": func_name,
                        "status": test_status,
                        "duration_ms": test_ms,
                        "error": test_error,
                    })

                try:
                    screenshot_dir = os.environ.get("SCREENSHOT_DIR", "/app/data/screenshots")
                    os.makedirs(screenshot_dir, exist_ok=True)
                    screenshot_path = os.path.join(screenshot_dir, f"exec_{asset.id}_{int(_t.time())}.png")
                    page.screenshot(path=screenshot_path, full_page=True)
                except Exception:
                    pass

                browser.close()

        except Exception as e:
            return {"status": "error", "error": f"Playwright 启动失败: {e}",
                    "duration_ms": int((_t.time() - start) * 1000),
                    "assertion_result": {"passed": False, "passed_count": 0,
                                         "failed_count": len(test_funcs), "results": assertion_results},
                    "sub_tests": sub_tests}

        total_ms = int((_t.time() - start) * 1000)
        overall_status = "PASS" if failed_count == 0 else "FAIL"

        return {
            "status": overall_status,
            "duration_ms": total_ms,
            "error": first_error,
            "assertion_result": {
                "passed": failed_count == 0,
                "passed_count": passed_count,
                "failed_count": failed_count,
                "results": assertion_results,
            },
            "sub_tests": sub_tests,
        }

    @staticmethod
    async def _run_android(asset: TestAsset, env: str, base_url: str) -> Dict:
        """
        Android runner（占位）

        Returns:
            {"status": "not_implemented", "message": "Android runner not implemented yet"}
        """
        log.warning(f"ExecutionDispatcher._run_android | Android runner 未实现, asset_id={asset.id}")
        return {"status": "not_implemented", "message": "Android runner not implemented yet"}
