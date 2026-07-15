"""
Neo4j图数据库连接管理

节点类型：
- Page: 页面节点
- Element: 元素节点
- TestCase: 测试用例节点
- Script: 脚本节点

关系类型：
- HAS_ELEMENT: Page -> Element（页面包含元素）
- NAVIGATE_TO: Page -> Page（页面跳转）
- TRIGGER: Element -> Page（元素触发跳转）
- NEXT: Element -> Element（元素操作顺序）
- USES: TestCase -> Element（用例使用元素）
- TEST_ON: TestCase -> Page（用例测试页面）
- GENERATES: TestCase -> Script（用例生成脚本）
- EXECUTES: Script -> Page（脚本执行页面）
"""
import threading
import time as _time
from typing import Optional, List, Dict, Any
from neo4j import GraphDatabase, Driver, Session
from app.core.config import settings
from app.core.logger import log


# ========== 节点标签 ==========
LABEL_PAGE = "Page"
LABEL_ELEMENT = "Element"
LABEL_CASE = "TestCase"
LABEL_SCRIPT = "Script"

# ========== 关系类型 ==========
REL_HAS_ELEMENT = "HAS_ELEMENT"       # Page -> Element
REL_NAVIGATE_TO = "NAVIGATE_TO"       # Page -> Page
REL_TRIGGER = "TRIGGER"               # Element -> Page
REL_NEXT = "NEXT"                     # Element -> Element
REL_USES = "USES"                     # TestCase -> Element
REL_TEST_ON = "TEST_ON"               # TestCase -> Page
REL_GENERATES = "GENERATES"           # TestCase -> Script
REL_EXECUTES = "EXECUTES"             # Script -> Page

ALL_REL_TYPES = [
    REL_HAS_ELEMENT, REL_NAVIGATE_TO, REL_TRIGGER,
    REL_NEXT, REL_USES, REL_TEST_ON, REL_GENERATES, REL_EXECUTES,
]

# 全局客户端单例
_driver: Optional[Driver] = None
_lock = threading.Lock()
_last_error_time = 0
_CONNECT_COOLDOWN = 15


def get_driver() -> Optional[Driver]:
    """获取Neo4j驱动实例"""
    global _driver, _last_error_time

    # [DEBUG] 进入函数
    _start = _time.time()
    log.info(f"[DEBUG] 开始：neo4j.get_driver | 输入：has_driver={_driver is not None}")

    if _driver is not None:
        return _driver

    with _lock:
        if _driver is not None:
            return _driver

        import time
        now = time.time()
        if now - _last_error_time < _CONNECT_COOLDOWN:
            log.debug("Neo4j连接冷却中，跳过重连")
            return None

        try:
            _driver = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
                max_connection_pool_size=10,
                connection_timeout=5,
            )
            _driver.verify_connectivity()
            log.info(f"Neo4j连接成功 | URI={settings.NEO4J_URI}")

            # [DEBUG] 连接成功
            _elapsed = _time.time() - _start
            log.info(f"[DEBUG] 结束：neo4j.get_driver | 输出：driver_connected=True | 耗时：{_elapsed:.2f}s")
        
            return _driver
        except Exception as e:
            _last_error_time = now
            _driver = None

            # [DEBUG] 异常
            _elapsed = _time.time() - _start
            log.warning(f"[DEBUG] 异常：neo4j.get_driver | 错误：{e} | 耗时：{_elapsed:.2f}s")
        
            log.warning(f"Neo4j连接失败: {e}")
            return None


def get_session() -> Optional[Session]:
    """获取数据库会话"""
    driver = get_driver()
    if driver is None:
        return None
    return driver.session()


def close():
    """关闭连接"""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
            log.info("Neo4j连接已关闭")
        except Exception as e:
            log.warning(f"关闭Neo4j连接异常: {e}")
        finally:
            _driver = None


def is_available() -> bool:
    """检查Neo4j是否可用"""
    driver = get_driver()
    if driver is None:
        return False
    try:
        driver.verify_connectivity()
        return True
    except Exception:
        return False


def run_query(cypher: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """执行Cypher查询"""
    # [DEBUG] 进入函数
    _start = _time.time()
    log.info(f"[DEBUG] 开始：neo4j.run_query | 输入：cypher={cypher[:80]}")

    session = get_session()
    if session is None:
        raise RuntimeError("Neo4j不可用")

    try:
        result = session.run(cypher, parameters or {})
        data = [record.data() for record in result]
        # [DEBUG] 结束
        _elapsed = _time.time() - _start
        log.info(f"[DEBUG] 结束：neo4j.run_query | 输出：rows={len(data)} | 耗时：{_elapsed:.2f}s")
        return data
    finally:
        session.close()


def run_write(cypher: str, parameters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """执行写操作（MERGE/CREATE/DELETE）"""
    # [DEBUG] 数据入库前
    _start = _time.time()
    log.info(f"[DEBUG] 开始：neo4j.run_write | 输入：cypher={cypher[:80]}")

    session = get_session()
    if session is None:
        raise RuntimeError("Neo4j不可用")

    try:
        result = session.run(cypher, parameters or {})
        data = [record.data() for record in result]
        # [DEBUG] 数据入库后
        _elapsed = _time.time() - _start
        log.info(f"[DEBUG] 结束：neo4j.run_write | 输出：rows={len(data)} | 耗时：{_elapsed:.2f}s")
        return data
    finally:
        session.close()


def ensure_constraints():
    """创建唯一性约束（幂等操作）"""
    constraints = [
        f"CREATE CONSTRAINT IF NOT EXISTS FOR (p:{LABEL_PAGE}) REQUIRE p.id IS UNIQUE",
        f"CREATE CONSTRAINT IF NOT EXISTS FOR (e:{LABEL_ELEMENT}) REQUIRE e.id IS UNIQUE",
        f"CREATE CONSTRAINT IF NOT EXISTS FOR (c:{LABEL_CASE}) REQUIRE c.id IS UNIQUE",
        f"CREATE CONSTRAINT IF NOT EXISTS FOR (s:{LABEL_SCRIPT}) REQUIRE s.id IS UNIQUE",
    ]

    for cql in constraints:
        try:
            run_query(cql)
        except Exception as e:
            log.debug(f"约束创建提示: {e}")

    log.info("Neo4j唯一性约束已就绪")


def clear_all():
    """清空所有节点和关系"""
    run_query("MATCH (n) DETACH DELETE n")
    log.warning("Neo4j图谱已清空")


def get_statistics() -> Dict[str, Any]:
    """获取图谱统计信息"""
    stats = {}

    for label in [LABEL_PAGE, LABEL_ELEMENT, LABEL_CASE, LABEL_SCRIPT]:
        key = f"{label.lower()}_count"
        try:
            r = run_query(f"MATCH (n:{label}) RETURN COUNT(n) AS cnt")
            stats[key] = r[0]["cnt"] if r else 0
        except Exception:
            stats[key] = 0

    # 关系统计
    rel_counts = {}
    for rel_type in ALL_REL_TYPES:
        try:
            r = run_query(f"MATCH ()-[r:{rel_type}]->() RETURN COUNT(r) AS cnt")
            rel_counts[rel_type] = r[0]["cnt"] if r else 0
        except Exception:
            rel_counts[rel_type] = 0
    stats["relationships"] = rel_counts

    stats["total_nodes"] = sum(
        v for k, v in stats.items() if k.endswith("_count")
    )
    stats["total_relationships"] = sum(rel_counts.values())

    # 平均度
    try:
        deg = run_query(
            "MATCH (n) WHERE size((n)--()) > 0 RETURN avg(size((n)--())) AS avg_deg"
        )
        stats["avg_degree"] = round(deg[0]["avg_deg"], 2) if deg and deg[0].get("avg_deg") else 0
    except Exception:
        # fallback: 手动计算
        try:
            total = stats["total_nodes"]
            rels = stats["total_relationships"]
            stats["avg_degree"] = round(2 * rels / total, 2) if total > 0 else 0
        except Exception:
            stats["avg_degree"] = 0

    stats["available"] = is_available()
    return stats
