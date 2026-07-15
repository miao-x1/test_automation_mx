#!/usr/bin/env python3
"""
迁移脚本：CaseContent + ApiCase → TestAsset

规则：
  - 幂等：已迁移的跳过（通过 legacy_*_id 判断）
  - 禁止覆盖：已存在的 TestAsset 不修改
  - 禁止重新生成：只迁移数据，不调用AI

用法：
  python scripts/migrate_case_asset.py           # 执行迁移
  python scripts/migrate_case_asset.py --dry-run  # 预览
"""
import sys
import os
import json
import argparse

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.db.database import SessionLocal
from app.models.test_asset import TestAsset, AssetType, AssetStatus, SourceType
from app.models.case_content import CaseContent
from app.models.api_case import ApiCase


def safe_json_parse(text: str):
    """安全解析JSON，处理多JSON对象的情况"""
    if not text:
        return None
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个完整JSON
        try:
            import json.decoder
            decoder = json.decoder.JSONDecoder()
            obj, _ = decoder.raw_decode(text)
            return obj
        except (json.JSONDecodeError, ValueError):
            return None


def migrate_case_content(dry_run: bool = False):
    """迁移 CaseContent → TestAsset"""
    db = SessionLocal()
    try:
        # 查找未迁移的 CaseContent
        migrated_ids = set(
            row[0] for row in
            db.query(TestAsset.legacy_case_content_id)
            .filter(TestAsset.legacy_case_content_id.isnot(None))
            .all()
        )

        contents = db.query(CaseContent).filter(
            CaseContent.is_deleted == False,
            ~CaseContent.id.in_(migrated_ids),
        ).all()

        print(f"[CaseContent] 待迁移: {len(contents)} 条, 已迁移: {len(migrated_ids)} 条")

        migrated = 0
        errors = 0
        for cc in contents:
            try:
                data = cc.to_test_asset()
                asset = TestAsset(**data)
                asset.validate_executable()
                if not dry_run:
                    db.add(asset)
                    db.flush()
                migrated += 1
            except Exception as e:
                errors += 1
                print(f"  [ERROR] CaseContent#{cc.id}: {e}")

        if not dry_run and migrated > 0:
            db.commit()

        print(f"[CaseContent] 迁移完成: {migrated} 成功, {errors} 失败")
        return migrated, errors
    finally:
        db.close()


def migrate_api_case(dry_run: bool = False):
    """迁移 ApiCase → TestAsset"""
    db = SessionLocal()
    try:
        # 查找未迁移的 ApiCase
        migrated_ids = set(
            row[0] for row in
            db.query(TestAsset.legacy_api_case_id)
            .filter(TestAsset.legacy_api_case_id.isnot(None))
            .all()
        )

        cases = db.query(ApiCase).filter(
            ApiCase.is_deleted == False,
            ~ApiCase.id.in_(migrated_ids),
        ).all()

        print(f"[ApiCase] 待迁移: {len(cases)} 条, 已迁移: {len(migrated_ids)} 条")

        migrated = 0
        errors = 0
        for ac in cases:
            try:
                # 构建 content_json（Case First 格式）
                steps_raw = safe_json_parse(ac.steps) or []
                assertions_raw = safe_json_parse(ac.assertions) or []

                # 转换 steps
                steps = []
                for s in steps_raw:
                    if isinstance(s, dict):
                        steps.append({
                            "action": s.get("action", ac.method or "POST"),
                            "url": s.get("url", ac.url or ""),
                            "method": s.get("method", s.get("action", ac.method or "POST")),
                            "headers": s.get("headers", {}),
                            "body": s.get("body", {}),
                        })

                # 如果 steps 为空但有 method/url，构建一个 step
                if not steps and (ac.method or ac.url):
                    steps.append({
                        "action": f"{ac.method or 'POST'} {ac.url or ''}",
                        "url": ac.url or "",
                        "method": ac.method or "POST",
                        "headers": {},
                        "body": {},
                    })

                # 转换 assertions
                assertions = []
                for a in assertions_raw:
                    if isinstance(a, dict):
                        assertions.append({
                            "path": a.get("path", ""),
                            "operator": a.get("type", a.get("operator", "eq")),
                            "expected": a.get("expected", ""),
                        })

                # 转换 preconditions
                preconditions = []
                if ac.precondition:
                    preconditions = [ac.precondition]

                content = {
                    "preconditions": preconditions,
                    "steps": steps,
                    "assertions": assertions,
                    "expected_result": "",
                    "env": "test",
                    "variables": safe_json_parse(ac.variables) or {},
                }

                # 映射类型
                type_map = {"API": "api", "UI": "web", "WEB": "web", "ANDROID": "android"}
                asset_type = type_map.get(ac.test_type, "api")

                source_map = {"ai": "ai", "manual": "manual", "swagger": "swagger", "import": "import"}
                source_type = source_map.get(ac.source, "manual")

                # 映射状态
                status_map = {
                    "draft": "draft", "review": "reviewed",
                    "published": "published", "deprecated": "draft",
                }
                status = status_map.get(ac.status, "draft")

                asset = TestAsset(
                    title=ac.title,
                    asset_type=asset_type,
                    source_type=source_type,
                    status=status,
                    content_json=json.dumps(content, ensure_ascii=False),
                    published=(status == "published"),
                    priority=ac.priority or "P1",
                    tags=ac.tags,
                    version=ac.version or 1,
                    user_id=ac.user_id,
                    created_by=ac.user_id,
                    legacy_api_case_id=ac.id,
                    legacy_case_content_id=ac.source_content_id,
                )
                asset.validate_executable()

                if not dry_run:
                    db.add(asset)
                    db.flush()
                migrated += 1
            except Exception as e:
                errors += 1
                print(f"  [ERROR] ApiCase#{ac.id}: {e}")

        if not dry_run and migrated > 0:
            db.commit()

        print(f"[ApiCase] 迁移完成: {migrated} 成功, {errors} 失败")
        return migrated, errors
    finally:
        db.close()


def update_executable_flags(dry_run: bool = False):
    """更新所有 TestAsset 的 executable 标记"""
    db = SessionLocal()
    try:
        assets = db.query(TestAsset).filter(TestAsset.is_deleted == False).all()
        updated = 0
        for asset in assets:
            old_exec = asset.executable
            asset.validate_executable()
            if asset.executable != old_exec:
                updated += 1

        if not dry_run and updated > 0:
            db.commit()

        print(f"[Executable] 更新 {updated} 条 executable 标记")
        return updated
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="迁移 CaseContent + ApiCase → TestAsset")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不写入数据库")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN 模式 ===\n")

    print("开始迁移...\n")

    cc_migrated, cc_errors = migrate_case_content(args.dry_run)
    ac_migrated, ac_errors = migrate_api_case(args.dry_run)
    exec_updated = update_executable_flags(args.dry_run)

    print(f"\n=== 迁移完成 ===")
    print(f"CaseContent: {cc_migrated} 成功, {cc_errors} 失败")
    print(f"ApiCase: {ac_migrated} 成功, {ac_errors} 失败")
    print(f"Executable标记: {exec_updated} 更新")
    print(f"总计: {cc_migrated + ac_migrated} 条迁移")
