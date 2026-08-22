"""
PromptManager - Agent Prompt 版本管理服务

功能:
1. 版本管理 - 创建/查看/激活/归档 Prompt 版本
2. A/B 测试 - 按流量比例分配不同版本
3. Prompt 回滚 - 快速切换回历史活跃版本
4. 版本比较 - 对比两个版本的内容差异
5. Agent 获取 - Agent 运行时通过 get_prompt() 获取当前活跃 Prompt

使用示例:
    # Agent 内部获取 Prompt (ApiCaseAgent → PromptManager → api_case_v2)
    prompt = PromptManager.get_prompt("api_case_agent", "system_prompt")

    # 创建新版本
    PromptManager.create_version(
        agent_name="api_case_agent",
        prompt_key="system_prompt",
        version="v2",
        content="你是接口用例生成专家...",
    )

    # 激活版本
    PromptManager.activate("api_case_agent", "system_prompt", "v2")

    # 回滚到上一版本
    PromptManager.rollback("api_case_agent", "system_prompt")

    # 版本比较
    diff = PromptManager.compare_versions("api_case_agent", "v1", "v2")
"""
import json
import random
import logging
import difflib
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from app.models.prompt_version import PromptVersion, PromptStatus

logger = logging.getLogger(__name__)


class PromptManager:
    """Prompt 版本管理器

    所有方法均为静态方法,通过 SessionLocal 获取 DB 会话。
    Agent 运行时通过 get_prompt() 获取当前活跃 Prompt。
    """

    # ============================================================
    # Agent 获取 Prompt (核心方法 - Agent 调用入口)
    # ============================================================

    @staticmethod
    def get_prompt(
        agent_name: str,
        prompt_key: str = "system_prompt",
        db: Optional[Session] = None,
    ) -> Optional[str]:
        """获取 Agent 的当前活跃 Prompt

        Agent 调用入口:
            ApiCaseAgent → PromptManager.get_prompt("api_case_agent") → "api_case_v2 内容"

        逻辑:
        1. 如果有 A/B 测试,按流量比例随机选择版本
        2. 否则返回 ACTIVE 版本
        3. 如果没有 ACTIVE 版本,返回 None

        Args:
            agent_name: Agent 名称
            prompt_key: Prompt 标识 (默认 system_prompt)
            db: 可选的数据库会话(外部传入避免重复创建)

        Returns:
            Prompt 内容字符串,不存在返回 None
        """
        own_session = db is None
        if own_session:
            from app.db.database import SessionLocal
            db = SessionLocal()
        try:
            # 1. 检查 A/B 测试
            testing_versions = db.query(PromptVersion).filter(
                and_(
                    PromptVersion.agent_name == agent_name,
                    PromptVersion.prompt_key == prompt_key,
                    PromptVersion.status == PromptStatus.TESTING,
                )
            ).all()

            if testing_versions:
                # 获取 ACTIVE 版本(作为基准)
                active = db.query(PromptVersion).filter(
                    and_(
                        PromptVersion.agent_name == agent_name,
                        PromptVersion.prompt_key == prompt_key,
                        PromptVersion.status == PromptStatus.ACTIVE,
                    )
                ).first()

                # 计算流量分配
                versions = list(testing_versions)
                if active:
                    versions.append(active)

                # 按比例随机选择
                rand = random.random()
                cumulative = 0.0
                for v in versions:
                    ratio = v.ab_test_ratio or 0.0
                    cumulative += ratio
                    if rand <= cumulative:
                        # 更新使用统计
                        v.usage_count = (v.usage_count or 0) + 1
                        db.commit()
                        logger.debug(f"[PromptManager] A/B 测试命中: {agent_name}/{v.version} (group={v.ab_test_group})")
                        return v.content

                # 如果比例总和 < 1,回退到 ACTIVE
                if active:
                    active.usage_count = (active.usage_count or 0) + 1
                    db.commit()
                    return active.content

            # 2. 无 A/B 测试,返回 ACTIVE 版本
            active = db.query(PromptVersion).filter(
                and_(
                    PromptVersion.agent_name == agent_name,
                    PromptVersion.prompt_key == prompt_key,
                    PromptVersion.status == PromptStatus.ACTIVE,
                )
            ).first()

            if active:
                active.usage_count = (active.usage_count or 0) + 1
                db.commit()
                return active.content

            return None
        finally:
            if own_session:
                db.close()

    @staticmethod
    async def get_prompt_async(
        agent_name: str,
        prompt_key: str = "system_prompt",
    ) -> Optional[str]:
        """异步获取 Prompt (Agent 异步调用入口)"""
        return PromptManager.get_prompt(agent_name, prompt_key)

    # ============================================================
    # 版本管理 - CRUD
    # ============================================================

    @staticmethod
    def create_version(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version: str,
        content: str,
        description: str = "",
        status: PromptStatus = PromptStatus.DRAFT,
        tags: Optional[List[str]] = None,
        created_by: Optional[int] = None,
    ) -> PromptVersion:
        """创建新的 Prompt 版本

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            prompt_key: Prompt 标识
            version: 版本号
            content: Prompt 内容
            description: 版本描述
            status: 初始状态(默认 DRAFT)
            tags: 标签列表

        Returns:
            PromptVersion 记录

        Raises:
            ValueError: 版本号已存在
        """
        # 检查版本号唯一
        existing = db.query(PromptVersion).filter(
            and_(
                PromptVersion.agent_name == agent_name,
                PromptVersion.prompt_key == prompt_key,
                PromptVersion.version == version,
            )
        ).first()
        if existing:
            raise ValueError(
                f"Prompt 版本已存在: {agent_name}/{prompt_key}/{version}"
            )

        # 判断是新建还是修改
        existing_versions = db.query(PromptVersion).filter(
            and_(
                PromptVersion.agent_name == agent_name,
                PromptVersion.prompt_key == prompt_key,
            )
        ).count()
        change_type = "new" if existing_versions == 0 else "modify"

        record = PromptVersion(
            agent_name=agent_name,
            prompt_key=prompt_key,
            version=version,
            content=content,
            description=description,
            status=status,
            change_type=change_type,
            tags=json.dumps(tags, ensure_ascii=False) if tags else None,
            usage_count=0,
            success_count=0,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info(
            f"[PromptManager] 创建版本: {agent_name}/{prompt_key}/{version} "
            f"(status={status.value}, type={change_type})"
        )
        return record

    @staticmethod
    def get_version(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version: str,
    ) -> Optional[PromptVersion]:
        """获取特定版本"""
        return db.query(PromptVersion).filter(
            and_(
                PromptVersion.agent_name == agent_name,
                PromptVersion.prompt_key == prompt_key,
                PromptVersion.version == version,
            )
        ).first()

    @staticmethod
    def list_versions(
        db: Session,
        agent_name: str,
        prompt_key: Optional[str] = None,
        status: Optional[PromptStatus] = None,
    ) -> List[PromptVersion]:
        """列出 Agent 的所有 Prompt 版本"""
        query = db.query(PromptVersion).filter(
            PromptVersion.agent_name == agent_name
        )
        if prompt_key:
            query = query.filter(PromptVersion.prompt_key == prompt_key)
        if status:
            query = query.filter(PromptVersion.status == status)
        return query.order_by(desc(PromptVersion.created_at)).all()

    @staticmethod
    def list_all_agents(db: Session) -> List[Dict[str, Any]]:
        """列出所有有 Prompt 的 Agent"""
        from sqlalchemy import distinct, func
        result = db.query(
            PromptVersion.agent_name,
            PromptVersion.prompt_key,
            func.count(PromptVersion.id).label("version_count"),
        ).group_by(
            PromptVersion.agent_name, PromptVersion.prompt_key
        ).all()
        return [
            {
                "agent_name": r.agent_name,
                "prompt_key": r.prompt_key,
                "version_count": r.version_count,
            }
            for r in result
        ]

    @staticmethod
    def update_version(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version: str,
        content: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[PromptVersion]:
        """更新版本内容(仅 DRAFT 状态可修改)"""
        record = PromptManager.get_version(db, agent_name, prompt_key, version)
        if record is None:
            return None

        # 核心 Prompt 保护:仅 DRAFT 状态可修改
        if record.status not in (PromptStatus.DRAFT,):
            raise ValueError(
                f"仅 DRAFT 状态可修改,当前状态: {record.status.value}。"
                f"如需修改,请新建版本或回滚后再修改。"
            )

        if content is not None:
            record.content = content
        if description is not None:
            record.description = description
        if tags is not None:
            record.tags = json.dumps(tags, ensure_ascii=False)

        db.commit()
        db.refresh(record)
        logger.info(f"[PromptManager] 更新版本: {agent_name}/{prompt_key}/{version}")
        return record

    @staticmethod
    def delete_version(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version: str,
    ) -> bool:
        """删除版本(仅 DRAFT/ARCHIVED 可删除)"""
        record = PromptManager.get_version(db, agent_name, prompt_key, version)
        if record is None:
            return False

        if record.status in (PromptStatus.ACTIVE, PromptStatus.TESTING):
            raise ValueError(
                f"不能删除 {record.status.value} 状态的版本。"
                f"请先切换状态。"
            )

        db.delete(record)
        db.commit()
        logger.info(f"[PromptManager] 删除版本: {agent_name}/{prompt_key}/{version}")
        return True

    # ============================================================
    # 版本激活与状态管理
    # ============================================================

    @staticmethod
    def activate(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version: str,
    ) -> PromptVersion:
        """激活指定版本(将其他 ACTIVE 版本归档)

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            prompt_key: Prompt 标识
            version: 要激活的版本号

        Returns:
            激活后的版本记录

        Raises:
            ValueError: 版本不存在
        """
        record = PromptManager.get_version(db, agent_name, prompt_key, version)
        if record is None:
            raise ValueError(
                f"Prompt 版本不存在: {agent_name}/{prompt_key}/{version}"
            )

        # 将当前 ACTIVE 版本归档
        current_active = db.query(PromptVersion).filter(
            and_(
                PromptVersion.agent_name == agent_name,
                PromptVersion.prompt_key == prompt_key,
                PromptVersion.status == PromptStatus.ACTIVE,
                PromptVersion.version != version,
            )
        ).all()
        for old in current_active:
            old.status = PromptStatus.ARCHIVED

        # 激活目标版本
        record.status = PromptStatus.ACTIVE
        record.ab_test_group = None
        record.ab_test_ratio = None
        db.commit()
        db.refresh(record)
        logger.info(
            f"[PromptManager] 激活版本: {agent_name}/{prompt_key}/{version}"
        )
        return record

    @staticmethod
    def archive(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version: str,
    ) -> Optional[PromptVersion]:
        """归档版本"""
        record = PromptManager.get_version(db, agent_name, prompt_key, version)
        if record is None:
            return None
        record.status = PromptStatus.ARCHIVED
        db.commit()
        db.refresh(record)
        return record

    # ============================================================
    # A/B 测试
    # ============================================================

    @staticmethod
    def start_ab_test(
        db: Session,
        agent_name: str,
        prompt_key: str,
        versions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """启动 A/B 测试

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            prompt_key: Prompt 标识
            versions: 版本配置列表
                [
                    {"version": "v1", "group": "A", "ratio": 0.5},
                    {"version": "v2", "group": "B", "ratio": 0.5},
                ]

        Returns:
            A/B 测试配置信息

        Raises:
            ValueError: 版本不存在 / 比例总和 != 1
        """
        # 验证比例总和
        total_ratio = sum(v.get("ratio", 0) for v in versions)
        if abs(total_ratio - 1.0) > 0.01:
            raise ValueError(
                f"A/B 测试流量比例总和必须为 1.0,当前: {total_ratio}"
            )

        # 设置每个版本的状态
        for v_config in versions:
            version = v_config["version"]
            group = v_config.get("group", version)
            ratio = v_config.get("ratio", 0.0)

            record = PromptManager.get_version(db, agent_name, prompt_key, version)
            if record is None:
                raise ValueError(
                    f"Prompt 版本不存在: {agent_name}/{prompt_key}/{version}"
                )

            record.status = PromptStatus.TESTING
            record.ab_test_group = group
            record.ab_test_ratio = ratio

        db.commit()
        logger.info(
            f"[PromptManager] 启动 A/B 测试: {agent_name}/{prompt_key} - "
            f"{len(versions)} 个版本"
        )
        return {
            "agent_name": agent_name,
            "prompt_key": prompt_key,
            "versions": [
                {
                    "version": v["version"],
                    "group": v.get("group", v["version"]),
                    "ratio": v.get("ratio", 0.0),
                }
                for v in versions
            ],
            "started_at": datetime.now().isoformat(),
        }

    @staticmethod
    def stop_ab_test(
        db: Session,
        agent_name: str,
        prompt_key: str,
        winner_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """停止 A/B 测试

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            prompt_key: Prompt 标识
            winner_version: 获胜版本(将被激活,其余归档)

        Returns:
            停止结果
        """
        testing = db.query(PromptVersion).filter(
            and_(
                PromptVersion.agent_name == agent_name,
                PromptVersion.prompt_key == prompt_key,
                PromptVersion.status == PromptStatus.TESTING,
            )
        ).all()

        results = []
        for record in testing:
            results.append({
                "version": record.version,
                "group": record.ab_test_group,
                "usage_count": record.usage_count,
                "success_count": record.success_count,
                "success_rate": (
                    record.success_count / record.usage_count
                    if record.usage_count and record.usage_count > 0
                    else 0
                ),
            })

            if winner_version and record.version == winner_version:
                record.status = PromptStatus.ACTIVE
            else:
                record.status = PromptStatus.ARCHIVED

            record.ab_test_group = None
            record.ab_test_ratio = None

        db.commit()
        logger.info(
            f"[PromptManager] 停止 A/B 测试: {agent_name}/{prompt_key}, "
            f"winner={winner_version}"
        )
        return {
            "agent_name": agent_name,
            "prompt_key": prompt_key,
            "winner": winner_version,
            "results": results,
            "stopped_at": datetime.now().isoformat(),
        }

    @staticmethod
    def get_ab_test_stats(
        db: Session,
        agent_name: str,
        prompt_key: str,
    ) -> List[Dict[str, Any]]:
        """获取 A/B 测试统计"""
        testing = db.query(PromptVersion).filter(
            and_(
                PromptVersion.agent_name == agent_name,
                PromptVersion.prompt_key == prompt_key,
                PromptVersion.status == PromptStatus.TESTING,
            )
        ).all()

        return [
            {
                "version": r.version,
                "group": r.ab_test_group,
                "ratio": r.ab_test_ratio,
                "usage_count": r.usage_count,
                "success_count": r.success_count,
                "success_rate": (
                    r.success_count / r.usage_count
                    if r.usage_count and r.usage_count > 0
                    else 0
                ),
            }
            for r in testing
        ]

    @staticmethod
    def record_result(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version: str,
        success: bool,
    ) -> None:
        """记录 Prompt 执行结果(用于 A/B 测试统计)"""
        record = PromptManager.get_version(db, agent_name, prompt_key, version)
        if record is None:
            return
        record.usage_count = (record.usage_count or 0) + 1
        if success:
            record.success_count = (record.success_count or 0) + 1
        db.commit()

    # ============================================================
    # 回滚
    # ============================================================

    @staticmethod
    def rollback(
        db: Session,
        agent_name: str,
        prompt_key: str,
        target_version: Optional[str] = None,
    ) -> PromptVersion:
        """回滚到指定版本或上一活跃版本

        Args:
            db: 数据库会话
            agent_name: Agent 名称
            prompt_key: Prompt 标识
            target_version: 目标版本号(为空则回滚到上一个 ARCHIVED 版本)

        Returns:
            激活的版本记录

        Raises:
            ValueError: 没有可回滚的版本
        """
        # 获取当前 ACTIVE 版本
        current = db.query(PromptVersion).filter(
            and_(
                PromptVersion.agent_name == agent_name,
                PromptVersion.prompt_key == prompt_key,
                PromptVersion.status == PromptStatus.ACTIVE,
            )
        ).first()

        if target_version:
            # 回滚到指定版本
            target = PromptManager.get_version(db, agent_name, prompt_key, target_version)
            if target is None:
                raise ValueError(
                    f"目标版本不存在: {agent_name}/{prompt_key}/{target_version}"
                )
        else:
            # 回滚到最近的 ARCHIVED 版本
            target = db.query(PromptVersion).filter(
                and_(
                    PromptVersion.agent_name == agent_name,
                    PromptVersion.prompt_key == prompt_key,
                    PromptVersion.status == PromptStatus.ARCHIVED,
                )
            ).order_by(desc(PromptVersion.updated_at)).first()

            if target is None:
                raise ValueError(
                    f"没有可回滚的历史版本: {agent_name}/{prompt_key}"
                )

        # 当前版本归档
        if current:
            current.status = PromptStatus.ARCHIVED

        # 创建回滚版本(保留历史记录)
        rollback_version = f"{target.version}_rb_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        rollback_record = PromptVersion(
            agent_name=agent_name,
            prompt_key=prompt_key,
            version=rollback_version,
            content=target.content,
            description=f"回滚到 {target.version}",
            status=PromptStatus.ACTIVE,
            change_type="rollback",
            parent_version=target.version,
            usage_count=0,
            success_count=0,
        )

        # 归档目标版本(避免多个 ACTIVE)
        target.status = PromptStatus.ARCHIVED

        db.add(rollback_record)
        db.commit()
        db.refresh(rollback_record)
        logger.info(
            f"[PromptManager] 回滚: {agent_name}/{prompt_key} → "
            f"{target.version} (新版本: {rollback_version})"
        )
        return rollback_record

    # ============================================================
    # 版本比较
    # ============================================================

    @staticmethod
    def compare_versions(
        db: Session,
        agent_name: str,
        prompt_key: str,
        version_a: str,
        version_b: str,
    ) -> Dict[str, Any]:
        """比较两个版本的内容差异

        Returns:
            {
                "version_a": "v1",
                "version_b": "v2",
                "content_a": "...",
                "content_b": "...",
                "diff": "unified diff text",
                "added_lines": 5,
                "removed_lines": 3,
                "similarity": 0.85,
            }
        """
        record_a = PromptManager.get_version(db, agent_name, prompt_key, version_a)
        record_b = PromptManager.get_version(db, agent_name, prompt_key, version_b)

        if record_a is None:
            raise ValueError(f"版本不存在: {version_a}")
        if record_b is None:
            raise ValueError(f"版本不存在: {version_b}")

        content_a = record_a.content
        content_b = record_b.content

        # 生成 diff
        lines_a = content_a.splitlines(keepends=True)
        lines_b = content_b.splitlines(keepends=True)
        diff = difflib.unified_diff(
            lines_a, lines_b,
            fromfile=f"{version_a}",
            tofile=f"{version_b}",
            lineterm="",
        )
        diff_text = "".join(diff)

        # 计算相似度
        similarity = difflib.SequenceMatcher(None, content_a, content_b).ratio()

        # 统计增删行
        added = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))

        return {
            "agent_name": agent_name,
            "prompt_key": prompt_key,
            "version_a": version_a,
            "version_b": version_b,
            "content_a": content_a,
            "content_b": content_b,
            "diff": diff_text,
            "added_lines": added,
            "removed_lines": removed,
            "similarity": round(similarity, 4),
        }

    # ============================================================
    # 从 AgentSpec 同步初始 Prompt
    # ============================================================

    @staticmethod
    def sync_from_specs(db: Session, specs: List[Any]) -> int:
        """将 AgentSpec 中的 system_prompt 同步到 prompt_version 表

        只同步有 system_prompt 的 Agent,版本号 v1。
        已存在的不覆盖。

        Args:
            db: 数据库会话
            specs: AgentSpec 列表

        Returns:
            同步的数量
        """
        synced = 0
        for spec in specs:
            if not hasattr(spec, "system_prompt") or not spec.system_prompt:
                continue
            if not hasattr(spec, "name"):
                continue

            # 检查是否已存在
            existing = db.query(PromptVersion).filter(
                and_(
                    PromptVersion.agent_name == spec.name,
                    PromptVersion.prompt_key == "system_prompt",
                    PromptVersion.version == "v1",
                )
            ).first()
            if existing:
                continue

            # 创建 v1 版本
            record = PromptVersion(
                agent_name=spec.name,
                prompt_key="system_prompt",
                version="v1",
                content=spec.system_prompt,
                description=f"从 AgentSpec 自动同步 ({spec.display_name})",
                status=PromptStatus.ACTIVE,
                change_type="new",
                usage_count=0,
                success_count=0,
            )
            db.add(record)
            synced += 1

        db.commit()
        logger.info(f"[PromptManager] 从 AgentSpec 同步 {synced} 个 Prompt")
        return synced

    # ============================================================
    # 统计
    # ============================================================

    @staticmethod
    def get_stats(db: Session) -> Dict[str, Any]:
        """获取 Prompt 管理统计"""
        from sqlalchemy import func

        total = db.query(func.count(PromptVersion.id)).scalar() or 0

        # 按状态统计
        status_counts = db.query(
            PromptVersion.status,
            func.count(PromptVersion.id),
        ).group_by(PromptVersion.status).all()
        by_status = {
            (s.value if hasattr(s, "value") else s): c
            for s, c in status_counts
        }

        # 按 Agent 统计
        agent_count = db.query(
            func.distinct(PromptVersion.agent_name)
        ).count()

        # A/B 测试中的数量
        ab_testing = db.query(func.count(PromptVersion.id)).filter(
            PromptVersion.status == PromptStatus.TESTING
        ).scalar() or 0

        # 总使用次数
        total_usage = db.query(func.sum(PromptVersion.usage_count)).scalar() or 0

        return {
            "total_versions": total,
            "agents_with_prompts": agent_count,
            "by_status": by_status,
            "ab_testing_count": ab_testing,
            "total_usage": total_usage,
        }
