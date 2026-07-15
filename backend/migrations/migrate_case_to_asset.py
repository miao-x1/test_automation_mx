"""
数据迁移脚本：CaseContent / ApiCase / 旧TestAsset → 统一 TestAsset

迁移原则：
  - 保留旧数据（不删除旧表）
  - 自动迁移（幂等，可重复执行）
  - 兼容旧接口（legacy_*_id 字段关联）
  - 禁止白屏（旧API继续工作）
  - 禁止删除用户数据

使用方式：
  python -m migrations.migrate_case_to_asset          # 全量迁移
  python -m migrations.migrate_case_to_asset --dry-run # 预览模式
"""
import sys
import json
import argparse
from datetime import datetime

# 添加项目路径
sys.path.insert(0, ".")

from app.db.database import SessionLocal, sync_engine as engine
from app.core.logger import log
from sqlalchemy import text


def infer_asset_type(test_type: str) -> str:
    """从旧test_type推断新asset_type"""
    if not test_type:
        return "api"
    t = test_type.upper()
    if t in ("UI", "WEB"):
        return "web"
    if t == "ANDROID":
        return "android"
    return "api"


def infer_status_from_case(case_status: str) -> str:
    """从CaseContent.case_status推断新status"""
    if not case_status:
        return "draft"
    mapping = {
        "draft": "draft",
        "review": "reviewed",
        "published": "published",
        "archived": "draft",
    }
    return mapping.get(case_status, "draft")


def infer_status_from_api(status: str) -> str:
    """从ApiCase.status推断新status"""
    if not status:
        return "draft"
    mapping = {
        "draft": "draft",
        "review": "reviewed",
        "published": "published",
        "deprecated": "draft",
    }
    return mapping.get(status, "draft")


def safe_json_parse(text, default=None):
    """安全解析JSON，处理多JSON对象等异常"""
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个完整JSON
        try:
            decoder = json.JSONDecoder()
            obj, idx = decoder.raw_decode(text)
            return obj
        except (json.JSONDecodeError, ValueError):
            return default


def build_content_from_case_content(cc) -> str:
    """从CaseContent构建content_json"""
    steps = safe_json_parse(cc.steps, [])
    expected = safe_json_parse(cc.expected, [])

    # 尝试从steps提取API信息
    method = ""
    url = ""
    headers = {}
    body = {}
    timeout = 5000

    if steps and isinstance(steps, list) and isinstance(steps[0], dict):
        first = steps[0]
        action = first.get("action", "")
        if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            method = action.upper()
            url = first.get("url", "")
            headers = first.get("headers", {})
            body = first.get("body", {})
            timeout = first.get("timeout", 5000)

    content = {
        "method": method,
        "url": url,
        "headers": headers,
        "body": body,
        "timeout": timeout,
        "precondition": cc.precondition or "",
        "steps": steps,
        "assertions": expected if isinstance(expected, list) else [expected],
        "pre_steps": [],
        "variables": {},
        "runtime": {"retry": 0, "env": "test"},
    }
    return json.dumps(content, ensure_ascii=False)


def build_content_from_api_case(ac) -> str:
    """从ApiCase构建content_json"""
    steps = safe_json_parse(ac.steps, [])
    assertions = safe_json_parse(ac.assertions, [])
    extracts = safe_json_parse(ac.extracts, [])
    variables = safe_json_parse(ac.variables, {})
    pre_steps = safe_json_parse(ac.pre_steps, [])
    env_override = safe_json_parse(ac.env_override, {})

    content = {
        "method": ac.method or "",
        "url": ac.url or "",
        "headers": {},
        "body": {},
        "timeout": 5000,
        "precondition": ac.precondition or "",
        "steps": steps,
        "assertions": assertions,
        "extracts": extracts,
        "pre_steps": pre_steps,
        "variables": variables,
        "env_override": env_override,
        "runtime": {"retry": 0, "env": "test"},
    }
    return json.dumps(content, ensure_ascii=False)


def build_content_from_old_test_asset(ta) -> str:
    """从旧TestAsset构建content_json"""
    content = {
        "script_content": ta.script_content or "",
        "script_language": ta.script_language or "python",
        "script_path": ta.script_path or "",
        "input_config": safe_json_parse(ta.input_config, {}),
        "exec_config": safe_json_parse(ta.exec_config, {}),
    }
    return json.dumps(content, ensure_ascii=False)


def migrate_case_content(dry_run: bool = False) -> dict:
    """CaseContent → TestAsset"""
    from app.models.case_content import CaseContent
    from app.models.test_asset import TestAsset

    db = SessionLocal()
    stats = {"created": 0, "skipped": 0, "errors": 0}

    try:
        # 获取已迁移的ID
        migrated_ids = set(
            row[0] for row in db.query(TestAsset.legacy_case_content_id)
            .filter(TestAsset.legacy_case_content_id.isnot(None))
            .all()
        )

        contents = db.query(CaseContent).filter(
            CaseContent.is_deleted == False,
        ).all()

        for cc in contents:
            if cc.id in migrated_ids:
                stats["skipped"] += 1
                continue

            try:
                asset_type = infer_asset_type(cc.test_type)
                status = infer_status_from_case(cc.case_status)
                source_type = "ai" if cc.source_type == "ai" else "manual"
                content_json = build_content_from_case_content(cc)
                published = status in ("published", "executed")

                asset = TestAsset(
                    title=cc.title,
                    description=cc.precondition,
                    asset_type=asset_type,
                    source_type=source_type,
                    status=status,
                    content_json=content_json,
                    published=published,
                    priority=cc.priority if cc.priority in ("P0", "P1", "P2", "P3") else "P1",
                    tags=cc.tags,
                    version=cc.version or 1,
                    user_id=cc.user_id,
                    created_by=cc.created_by,
                    legacy_case_content_id=cc.id,
                    legacy_api_case_id=cc.api_case_id,
                )

                if not dry_run:
                    db.add(asset)
                stats["created"] += 1

            except Exception as e:
                stats["errors"] += 1
                log.warning(f"migrate_case_to_asset | CaseContent迁移失败 id={cc.id}: {e}")

        if not dry_run:
            db.commit()

    except Exception as e:
        log.error(f"migrate_case_to_asset | CaseContent迁移异常: {e}")
        db.rollback()
        stats["errors"] += 1
    finally:
        db.close()

    return stats


def migrate_api_case(dry_run: bool = False) -> dict:
    """ApiCase → TestAsset"""
    from app.models.api_case import ApiCase
    from app.models.test_asset import TestAsset

    db = SessionLocal()
    stats = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}

    try:
        # 获取已迁移的ID
        migrated_ids = set(
            row[0] for row in db.query(TestAsset.legacy_api_case_id)
            .filter(TestAsset.legacy_api_case_id.isnot(None))
            .all()
        )

        cases = db.query(ApiCase).filter(
            ApiCase.is_deleted == False,
        ).all()

        for ac in cases:
            if ac.id in migrated_ids:
                stats["skipped"] += 1
                continue

            try:
                # 检查是否已通过CaseContent迁移
                existing = db.query(TestAsset).filter(
                    TestAsset.legacy_case_content_id == ac.source_content_id,
                ).first() if ac.source_content_id else None

                asset_type = infer_asset_type(ac.test_type)
                status = infer_status_from_api(ac.status)
                source_type = "ai" if ac.source == "ai" else "manual"
                content_json = build_content_from_api_case(ac)
                published = status in ("published", "executed")

                if existing:
                    # 补充发布内容（如果CaseContent迁移时只创建了草稿）
                    if not existing.published and published:
                        existing.published = True
                        existing.status = status
                    existing.legacy_api_case_id = ac.id
                    stats["updated"] += 1
                else:
                    asset = TestAsset(
                        title=ac.title,
                        description=ac.description,
                        asset_type=asset_type,
                        source_type=source_type,
                        status=status,
                        content_json=content_json,
                        published=published,
                        priority=ac.priority if ac.priority in ("P0", "P1", "P2", "P3") else "P1",
                        tags=ac.tags,
                        version=ac.version or 1,
                        user_id=ac.user_id,
                        created_by=ac.created_by,
                        legacy_api_case_id=ac.id,
                        legacy_case_content_id=ac.source_content_id,
                    )
                    if not dry_run:
                        db.add(asset)
                    stats["created"] += 1

            except Exception as e:
                stats["errors"] += 1
                log.warning(f"migrate_case_to_asset | ApiCase迁移失败 id={ac.id}: {e}")

        if not dry_run:
            db.commit()

    except Exception as e:
        log.error(f"migrate_case_to_asset | ApiCase迁移异常: {e}")
        db.rollback()
        stats["errors"] += 1
    finally:
        db.close()

    return stats


def migrate_old_test_asset(dry_run: bool = False) -> dict:
    """旧TestAsset → 新TestAsset"""
    from app.models.test_asset import TestAsset

    db = SessionLocal()
    stats = {"created": 0, "skipped": 0, "errors": 0}

    try:
        # 获取已迁移的ID
        migrated_ids = set(
            row[0] for row in db.query(TestAsset.legacy_test_asset_id)
            .filter(TestAsset.legacy_test_asset_id.isnot(None))
            .all()
        )

        # 从旧表读取（表名 web_script_asset）
        try:
            old_assets = db.execute(text("SELECT * FROM web_script_asset")).fetchall()
        except Exception:
            # 旧表可能还不存在
            log.info("migrate_case_to_asset | 旧test_asset表不存在，跳过")
            return {"created": 0, "skipped": 0, "errors": 0}

        for ta in old_assets:
            if ta.id in migrated_ids:
                stats["skipped"] += 1
                continue

            try:
                asset_type = "web" if ta.asset_type in ("web",) else ta.asset_type
                status = "published" if ta.status in ("ready", "completed") else "draft"
                source_type = "manual"
                if ta.source == "generated":
                    source_type = "ai"
                elif ta.source == "reused":
                    source_type = "reused"

                content_json = build_content_from_old_test_asset(ta)
                published = status in ("published", "executed")

                asset = TestAsset(
                    title=ta.name,
                    description=f"Web脚本资产（迁移自旧TestAsset #{ta.id}）",
                    asset_type=asset_type,
                    source_type=source_type,
                    status=status,
                    content_json=content_json,
                    published=published,
                    version=ta.version or 1,
                    user_id=ta.user_id,
                    created_by=ta.created_by,
                    legacy_test_asset_id=ta.id,
                )

                if not dry_run:
                    db.add(asset)
                stats["created"] += 1

            except Exception as e:
                stats["errors"] += 1
                log.warning(f"migrate_case_to_asset | 旧TestAsset迁移失败 id={ta.id}: {e}")

        if not dry_run:
            db.commit()

    except Exception as e:
        log.error(f"migrate_case_to_asset | 旧TestAsset迁移异常: {e}")
        db.rollback()
        stats["errors"] += 1
    finally:
        db.close()

    return stats


def run_migration(dry_run: bool = False):
    """执行全部迁移"""
    print(f"\n{'[预览模式] ' if dry_run else ''}开始数据迁移...")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 0. 重命名旧test_asset表（如果存在）
    if not dry_run:
        print("0. 检查旧test_asset表 ...")
        try:
            with engine.connect() as conn:
                # 检查旧表是否存在
                result = conn.execute(
                    __import__("sqlalchemy").text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = DATABASE() AND table_name = 'test_asset'"
                    )
                )
                exists = result.scalar() > 0

                if exists:
                    # 检查是否是旧结构（有name列没有title列）
                    col_result = conn.execute(
                        __import__("sqlalchemy").text(
                            "SELECT COUNT(*) FROM information_schema.columns "
                            "WHERE table_schema = DATABASE() AND table_name = 'test_asset' AND column_name = 'name'"
                        )
                    )
                    is_old_structure = col_result.scalar() > 0

                    if is_old_structure:
                        # 检查web_script_asset是否已存在
                        ws_result = conn.execute(
                            __import__("sqlalchemy").text(
                                "SELECT COUNT(*) FROM information_schema.tables "
                                "WHERE table_schema = DATABASE() AND table_name = 'web_script_asset'"
                            )
                        )
                        ws_exists = ws_result.scalar() > 0

                        if not ws_exists:
                            print("   重命名 test_asset → web_script_asset ...")
                            conn.execute(__import__("sqlalchemy").text(
                                "RENAME TABLE test_asset TO web_script_asset"
                            ))
                            conn.commit()
                            print("   ✓ 旧表已重命名为 web_script_asset")
                        else:
                            print("   web_script_asset 已存在，跳过重命名")
                    else:
                        print("   test_asset 表已是新结构，跳过")
                else:
                    print("   test_asset 表不存在，将创建新表")
        except Exception as e:
            print(f"   ! 检查旧表异常: {e}（继续执行）")

    # 1. 创建新表
    if not dry_run:
        print("\n1. 创建新表 test_asset ...")
        try:
            from app.models.test_asset import TestAsset
            TestAsset.__table__.create(engine, checkfirst=True)
            print("   ✓ test_asset 表已创建/已存在")
        except Exception as e:
            print(f"   ✗ 创建表失败: {e}")
            return
    else:
        print("\n1. [预览] 跳过建表")

    # 2. 迁移 CaseContent
    print("\n2. 迁移 CaseContent → TestAsset ...")
    cc_stats = migrate_case_content(dry_run)
    print(f"   创建: {cc_stats['created']}  跳过: {cc_stats['skipped']}  错误: {cc_stats['errors']}")

    # 3. 迁移 ApiCase
    print("\n3. 迁移 ApiCase → TestAsset ...")
    ac_stats = migrate_api_case(dry_run)
    print(f"   创建: {ac_stats['created']}  更新: {ac_stats['updated']}  跳过: {ac_stats['skipped']}  错误: {ac_stats['errors']}")

    # 4. 迁移旧TestAsset
    print("\n4. 迁移 旧TestAsset → TestAsset ...")
    ta_stats = migrate_old_test_asset(dry_run)
    print(f"   创建: {ta_stats['created']}  跳过: {ta_stats['skipped']}  错误: {ta_stats['errors']}")

    # 5. 汇总
    total_created = cc_stats['created'] + ac_stats['created'] + ta_stats['created']
    total_errors = cc_stats['errors'] + ac_stats['errors'] + ta_stats['errors']
    print(f"\n{'[预览模式] ' if dry_run else ''}迁移完成！")
    print(f"   总计创建: {total_created}")
    print(f"   总计错误: {total_errors}")

    if dry_run:
        print("\n   这是预览模式，未实际写入数据。去掉 --dry-run 执行实际迁移。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据迁移：CaseContent/ApiCase/旧TestAsset → 统一TestAsset")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入")
    args = parser.parse_args()
    run_migration(dry_run=args.dry_run)
