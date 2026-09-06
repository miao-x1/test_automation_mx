"""Safe Alembic helpers: inspect-then-apply. Never prints secrets."""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text


def _inspector():
    return inspect(op.get_bind())


def table_exists(table: str) -> bool:
    return table in _inspector().get_table_names()


def column_exists(table: str, column: str) -> bool:
    if not table_exists(table):
        return False
    return column in {c["name"] for c in _inspector().get_columns(table)}


def index_exists(table: str, name: str) -> bool:
    if not table_exists(table):
        return False
    return name in {i["name"] for i in _inspector().get_indexes(table)}


def fk_exists(table: str, name: str) -> bool:
    if not table_exists(table):
        return False
    return name in {fk["name"] for fk in _inspector().get_foreign_keys(table) if fk.get("name")}


def add_column_if_missing(table: str, column) -> bool:
    if not table_exists(table):
        return False
    if column_exists(table, column.name):
        return False
    op.add_column(table, column)
    return True


def create_index_if_missing(name: str, table: str, columns: list[str]) -> bool:
    if not table_exists(table) or index_exists(table, name):
        return False
    op.create_index(name, table, columns)
    return True


def create_fk_if_missing(name: str, source: str, referent: str, local_cols: list[str], remote_cols: list[str], ondelete: str | None = None) -> bool:
    if not table_exists(source) or not table_exists(referent) or fk_exists(source, name):
        return False
    if any(not column_exists(source, col) for col in local_cols):
        return False
    op.create_foreign_key(name, source, referent, local_cols, remote_cols, ondelete=ondelete)
    return True


def ensure_user_table() -> bool:
    """Create user before any revision that adds FK(user.id)."""
    if table_exists("user"):
        return False
    import sqlalchemy as sa
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column("username", sa.String(50), nullable=False, comment="用户名（唯一）"),
        sa.Column("email", sa.String(255), nullable=True, comment="邮箱（可选，唯一）"),
        sa.Column("hashed_password", sa.String(255), nullable=False, comment="加密密码"),
        sa.Column("display_name", sa.String(100), nullable=True, comment="显示名称"),
        sa.Column("avatar", sa.String(512), nullable=True, comment="头像URL"),
        sa.Column("role", sa.String(20), nullable=False, comment="角色: admin/user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, comment="是否激活"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    create_index_if_missing("ix_user_username", "user", ["username"])
    create_index_if_missing("ix_user_email", "user", ["email"])
    create_index_if_missing("ix_user_role", "user", ["role"])
    return True


def ensure_ui_element_table() -> bool:
    if table_exists("ui_element"):
        return False
    import sqlalchemy as sa
    op.create_table(
        "ui_element",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"),
        sa.Column("task_id", sa.Integer(), nullable=False, comment="任务ID"),
        sa.Column("name", sa.String(255), nullable=False, comment="元素名称"),
        sa.Column("type", sa.String(50), nullable=False, comment="元素类型"),
        sa.Column("text", sa.String(512), nullable=True, comment="元素文本内容"),
        sa.Column("source", sa.String(20), nullable=False, comment="元素来源: vision/dom/merge"),
        sa.Column("locator", sa.String(512), nullable=True, comment="最佳定位器"),
        sa.Column("xpath", sa.String(1024), nullable=True, comment="XPath定位"),
        sa.Column("css_selector", sa.String(1024), nullable=True, comment="CSS选择器定位"),
        sa.Column("element_id", sa.String(255), nullable=True, comment="元素id属性"),
        sa.Column("element_class", sa.String(512), nullable=True, comment="元素class属性"),
        sa.Column("element_name", sa.String(255), nullable=True, comment="元素name属性"),
        sa.Column("placeholder", sa.String(255), nullable=True, comment="placeholder属性"),
        sa.Column("href", sa.String(1024), nullable=True, comment="href属性"),
        sa.Column("aria_label", sa.String(255), nullable=True, comment="aria-label属性"),
        sa.Column("role", sa.String(50), nullable=True, comment="角色属性"),
        sa.Column("data_testid", sa.String(255), nullable=True, comment="data-testid属性"),
        sa.Column("page_url", sa.String(1024), nullable=True, comment="页面URL"),
        sa.Column("confidence", sa.Float(), nullable=True, comment="识别置信度(0-1)"),
        sa.Column("kb_status", sa.String(20), nullable=False, server_default="approved", comment="知识库审核状态"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
    )
    create_index_if_missing("ix_ui_element_task_id", "ui_element", ["task_id"])
    create_index_if_missing("ix_ui_element_type", "ui_element", ["type"])
    create_index_if_missing("ix_ui_element_source", "ui_element", ["source"])
    create_index_if_missing("ix_ui_element_kb_status", "ui_element", ["kb_status"])
    return True


def ensure_test_asset_table() -> bool:
    """Task.selectin loads test_assets; table was never created by historical revisions."""
    if table_exists("test_asset"):
        return False
    import sqlalchemy as sa
    fks = []
    if table_exists("task"):
        fks.append(sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"))
    if table_exists("requirement_task"):
        fks.append(sa.ForeignKeyConstraint(["requirement_id"], ["requirement_task.id"], ondelete="SET NULL"))
    op.create_table(
        "test_asset",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column("user_id", sa.Integer(), nullable=True, comment="所属用户ID"),
        sa.Column("created_by", sa.Integer(), nullable=True, comment="创建者用户ID"),
        sa.Column("title", sa.String(500), nullable=False, comment="用例标题"),
        sa.Column("description", sa.Text(), nullable=True, comment="描述"),
        sa.Column("asset_type", sa.String(20), nullable=False, server_default="api", comment="资产类型"),
        sa.Column("source_type", sa.String(20), nullable=False, server_default="ai", comment="来源"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft", comment="状态"),
        sa.Column("executable", sa.Boolean(), nullable=False, server_default="0", comment="是否可执行"),
        sa.Column("session_id", sa.Integer(), nullable=True, comment="关联会话ID"),
        sa.Column("requirement_id", sa.Integer(), nullable=True, comment="关联需求ID"),
        sa.Column("project_id", sa.Integer(), nullable=True, comment="项目ID"),
        sa.Column("task_id", sa.Integer(), nullable=True, comment="关联任务ID"),
        sa.Column("folder_id", sa.Integer(), nullable=True, comment="所属目录ID"),
        sa.Column("test_point_id", sa.Integer(), nullable=True, comment="关联测试点ID"),
        sa.Column("content_json", sa.Text(), nullable=True, comment="用例内容(JSON)"),
        sa.Column("draft_content", sa.Text(), nullable=True, comment="草稿内容(JSON)"),
        sa.Column("published_content", sa.Text(), nullable=True, comment="发布内容(JSON)"),
        sa.Column("input_config", sa.Text(), nullable=True, comment="输入配置(JSON)"),
        sa.Column("exec_config", sa.Text(), nullable=True, comment="执行配置(JSON)"),
        sa.Column("script_content", sa.Text(), nullable=True, comment="测试脚本内容"),
        sa.Column("script_language", sa.String(20), nullable=True, comment="脚本语言"),
        sa.Column("script_path", sa.String(512), nullable=True, comment="脚本文件路径"),
        sa.Column("kb_status", sa.String(20), nullable=False, server_default="approved", comment="知识库审核状态"),
        sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0", comment="被复用次数"),
        sa.Column("published", sa.Boolean(), nullable=False, server_default="0", comment="是否已发布"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1", comment="版本号"),
        sa.Column("execution_state", sa.Text(), nullable=True, comment="执行状态(JSON)"),
        sa.Column("priority", sa.String(5), nullable=True, comment="优先级"),
        sa.Column("tags", sa.String(500), nullable=True, comment="标签"),
        sa.Column("legacy_case_content_id", sa.Integer(), nullable=True, comment="旧CaseContent ID"),
        sa.Column("legacy_api_case_id", sa.Integer(), nullable=True, comment="旧ApiCase ID"),
        sa.Column("legacy_test_asset_id", sa.Integer(), nullable=True, comment="旧TestAsset ID"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0", comment="软删除"),
        sa.PrimaryKeyConstraint("id"),
        *fks,
    )
    create_index_if_missing("ix_test_asset_asset_type", "test_asset", ["asset_type"])
    create_index_if_missing("ix_test_asset_status", "test_asset", ["status"])
    create_index_if_missing("ix_test_asset_task_id", "test_asset", ["task_id"])
    return True


def ensure_workspace_table() -> bool:
    if not table_exists("user") or table_exists("workspace"):
        return False
    import sqlalchemy as sa
    op.create_table(
        "workspace",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="主键ID"),
        sa.Column("created_at", sa.DateTime(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, comment="更新时间"),
        sa.Column("user_id", sa.Integer(), nullable=False, comment="所属用户ID"),
        sa.Column("name", sa.String(100), nullable=False, comment="工作空间名称"),
        sa.Column("description", sa.String(512), nullable=True, comment="工作空间描述"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    create_index_if_missing("ix_workspace_user_id", "workspace", ["user_id"])
    create_index_if_missing("idx_workspace_user", "workspace", ["user_id"])
    return True


def modify_varchar(table: str, column: str, length: int, nullable: bool = True, default: str | None = None) -> None:
    if not column_exists(table, column):
        return
    null_sql = "NULL" if nullable else "NOT NULL"
    default_sql = f" DEFAULT '{default}'" if default is not None else ""
    op.execute(text(
        f"ALTER TABLE {table} MODIFY COLUMN {column} VARCHAR({length}) {null_sql}{default_sql}"
    ))
