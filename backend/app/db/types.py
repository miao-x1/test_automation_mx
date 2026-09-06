"""跨 MySQL / SQLite 的列类型。

MySQL 使用 MEDIUMTEXT（最大约 16MB），SQLite 没有该方言类型，映射为 TEXT。
"""
from sqlalchemy.dialects.mysql import MEDIUMTEXT as MYSQL_MEDIUMTEXT
from sqlalchemy.types import Text, TypeDecorator


class CompatMediumText(TypeDecorator):
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "mysql":
            return dialect.type_descriptor(MYSQL_MEDIUMTEXT())
        return dialect.type_descriptor(Text())


MEDIUMTEXT = CompatMediumText
