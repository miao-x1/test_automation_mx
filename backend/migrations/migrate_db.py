"""
数据库迁移脚本 - 统一测试平台

自动检测并补齐数据库表结构，使现有表与SQLAlchemy模型一致。
支持：
1. 创建缺失的表
2. 给已有表添加缺失的列
3. 不删除已有列和数据
"""
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import inspect, text
from app.core.config import settings
from app.db.database import Base, sync_engine
from app.models import *  # noqa: 确保所有模型已加载


def migrate():
    """执行数据库迁移"""
    print(f"数据库: {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else settings.DATABASE_URL}")
    print("=" * 60)

    inspector = inspect(sync_engine)
    existing_tables = set(inspector.get_table_names())
    model_tables = set()

    # 收集所有模型对应的表名
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if hasattr(cls, '__tablename__') and not cls.__tablename__.startswith('_'):
            model_tables.add(cls.__tablename__)

    # 1. 创建缺失的表
    new_tables = model_tables - existing_tables
    if new_tables:
        print(f"\n[新建表] 发现 {len(new_tables)} 个新表: {new_tables}")
        Base.metadata.create_all(bind=sync_engine, checkfirst=True)
        print("[新建表] 创建完成")
    else:
        print("\n[新建表] 无需创建新表")

    # 2. 给已有表添加缺失的列
    with sync_engine.connect() as conn:
        fixes = 0
        for table_name in model_tables & existing_tables:
            # 获取数据库中已有的列名
            db_columns = {col['name'] for col in inspector.get_columns(table_name)}

            # 获取模型中定义的列
            if table_name not in Base.metadata.tables:
                continue
            model_columns = {col.name: col for col in Base.metadata.tables[table_name].columns}

            # 找出缺失的列
            missing_cols = set(model_columns.keys()) - db_columns
            if missing_cols:
                print(f"\n[补列] 表 '{table_name}' 缺少列: {missing_cols}")
                for col_name in missing_cols:
                    col = model_columns[col_name]
                    alter_sql = _generate_alter_sql(table_name, col)
                    if alter_sql:
                        try:
                            conn.execute(text(alter_sql))
                            conn.commit()
                            print(f"  [OK] 添加列: {col_name}")
                            fixes += 1
                        except Exception as e:
                            conn.rollback()
                            print(f"  [FAIL] 添加列 {col_name} 失败: {e}")
                    else:
                        print(f"  - 跳过列: {col_name} (无法生成SQL)")

        if fixes == 0:
            print("\n[补列] 所有表结构已是最新")
        else:
            print(f"\n[补列] 共修复 {fixes} 个列")

    # 3. 验证
    print("\n" + "=" * 60)
    print("[验证] 检查所有模型与数据库一致性...")
    inspector = inspect(sync_engine)
    all_ok = True
    for table_name in model_tables:
        db_columns = {col['name'] for col in inspector.get_columns(table_name)}
        if table_name not in Base.metadata.tables:
            continue
        model_columns = {col.name for col in Base.metadata.tables[table_name].columns}
        missing = model_columns - db_columns
        if missing:
            print(f"  [X] 表 '{table_name}' 仍缺少列: {missing}")
            all_ok = False

    if all_ok:
        print("[验证] [OK] 所有表结构一致")
    else:
        print("[验证] [X] 仍有不一致，请手动检查")

    print("\n迁移完成!")
    return all_ok


def _generate_alter_sql(table_name: str, col) -> str:
    """生成ALTER TABLE添加列的SQL"""
    col_type = _get_column_type_str(col)
    if not col_type:
        return ""

    nullable = "NULL" if col.nullable else "NOT NULL"
    default = ""
    if col.default is not None:
        default_val = col.default.arg
        if callable(default_val):
            # 跳过函数默认值（如datetime.now）
            pass
        elif isinstance(default_val, str):
            default = f" DEFAULT '{default_val}'"
        elif isinstance(default_val, (int, float)):
            default = f" DEFAULT {default_val}"
        elif isinstance(default_val, bool):
            default = f" DEFAULT {1 if default_val else 0}"

    comment = ""
    if col.comment:
        comment = f" COMMENT '{col.comment}'"

    if settings.USE_SQLITE:
        # SQLite不支持COMMENT和部分ALTER语法
        return f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {nullable}{default}"
    else:
        return f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {nullable}{default}{comment}"


def _get_column_type_str(col) -> str:
    """获取列类型的SQL字符串"""
    col_type = str(col.type)
    # 常见类型映射
    type_map = {
        "INTEGER": "INTEGER",
        "VARCHAR": f"VARCHAR({col.type.length if hasattr(col.type, 'length') and col.type.length else 255})",
        "STRING": f"VARCHAR({col.type.length if hasattr(col.type, 'length') and col.type.length else 255})",
        "TEXT": "TEXT",
        "FLOAT": "FLOAT",
        "DATETIME": "DATETIME",
        "BOOLEAN": "BOOLEAN",
        "BLOB": "BLOB",
        "BIGINT": "BIGINT",
    }

    # 处理ENUM类型
    if "ENUM" in col_type.upper():
        if hasattr(col.type, 'enums') and col.type.enums:
            enums = "','".join(col.type.enums)
            if settings.USE_SQLITE:
                return "VARCHAR(20)"
            return f"ENUM('{enums}')"
        return "VARCHAR(20)"

    for key, val in type_map.items():
        if key in col_type.upper():
            return val

    return col_type


if __name__ == "__main__":
    migrate()
