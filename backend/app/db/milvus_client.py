"""
Milvus向量数据库连接与集合管理

支持两种模式：
1. Milvus Lite（嵌入式，开发环境，无需Docker）
2. Milvus Standalone（生产环境，需Docker部署）
"""
import os
import time
import threading
import subprocess
from pymilvus import MilvusClient, DataType, CollectionSchema, FieldSchema
from app.core.config import settings
from app.core.logger import log


# 向量维度（从配置读取，DashScope text-embedding-v3 默认1024维，本地 all-MiniLM-L6-v2 为384维）
EMBEDDING_DIM = settings.EMBEDDING_DIM

# 集合名称（从统一常量文件导入，禁止硬编码）
from app.db.collection_constants import (
    UI_ELEMENT_COLLECTION as COLLECTION_NAME,
    CASE_COLLECTION as CASE_COLLECTION_NAME,
    SCRIPT_COLLECTION as SCRIPT_COLLECTION_NAME,
)

# Milvus Lite数据文件路径
MILVUS_DATA_DIR = os.path.abspath(os.path.join(settings.UPLOAD_DIR, "milvus"))
MILVUS_DB_FILE = os.path.join(MILVUS_DATA_DIR, "milvus_lite.db")
MILVUS_LOCK_FILE = os.path.join(MILVUS_DATA_DIR, "milvus_lite.db.lock")

# 全局客户端单例 + 线程锁
_milvus_client = None
_client_lock = threading.Lock()
_last_connect_time = 0  # 上次连接失败时间，用于冷却
_CONNECT_COOLDOWN = 10  # 连接失败后冷却10秒，避免频繁重试


def _cleanup_lock_file():
    """清理Milvus Lite残留锁文件"""
    if os.path.exists(MILVUS_LOCK_FILE):
        try:
            os.remove(MILVUS_LOCK_FILE)
            log.info(f"已清理Milvus Lite锁文件: {MILVUS_LOCK_FILE}")
        except Exception as e:
            log.warning(f"清理锁文件失败: {e}")


def _kill_milvus_processes():
    """杀掉残留的Milvus Lite进程"""
    try:
        if os.name == 'nt':
            # Windows: 查找并杀掉占用milvus_lite.db的进程
            result = subprocess.run(
                ['wmic', 'process', 'where', f"CommandLine like '%milvus_lite%'", 'get', 'ProcessId', '/format:list'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.startswith('ProcessId='):
                    pid = line.split('=')[1].strip()
                    if pid.isdigit():
                        try:
                            subprocess.run(['taskkill', '/F', '/PID', pid], capture_output=True, timeout=3)
                            log.info(f"已杀掉残留Milvus进程 PID={pid}")
                        except Exception:
                            pass
        else:
            subprocess.run(['pkill', '-f', 'milvus_lite'], capture_output=True, timeout=3)
    except Exception as e:
        log.warning(f"杀掉Milvus进程失败: {e}")


def _safe_close_client(client):
    """安全关闭Milvus客户端"""
    if client is None:
        return
    try:
        client.close()
    except Exception:
        pass


def force_reset_milvus():
    """强制重置Milvus连接（杀进程+清锁+重置单例）"""
    global _milvus_client
    log.info("强制重置Milvus连接...")
    _safe_close_client(_milvus_client)
    _milvus_client = None
    _kill_milvus_processes()
    time.sleep(1)
    _cleanup_lock_file()
    log.info("Milvus连接已重置")


def get_milvus_client(allow_fail=True) -> MilvusClient | None:
    """
    获取Milvus客户端（单例模式，线程安全）

    Args:
        allow_fail: 如果为True，连接失败时返回None而不是抛异常
    """
    global _milvus_client, _last_connect_time

    # [DEBUG] 进入函数
    _start = time.time()
    log.info(f"[DEBUG] 开始：get_milvus_client | 输入：allow_fail={allow_fail}, has_client={_milvus_client is not None}")

    # 快速路径：已有客户端直接返回
    if _milvus_client is not None:
        try:
            _milvus_client.list_collections()
            return _milvus_client
        except Exception:
            log.warning("Milvus客户端连接失效，正在重建...")
            _safe_close_client(_milvus_client)
            _milvus_client = None

    # 冷却期内直接返回None，避免阻塞
    now = time.time()
    if _last_connect_time > 0 and (now - _last_connect_time) < _CONNECT_COOLDOWN:
        log.debug(f"Milvus连接冷却中，跳过重试")
        if allow_fail:
            return None
        else:
            raise ConnectionError("Milvus连接冷却中，请稍后重试")

    with _client_lock:
        # 双重检查
        if _milvus_client is not None:
            try:
                _milvus_client.list_collections()
                return _milvus_client
            except Exception:
                _safe_close_client(_milvus_client)
                _milvus_client = None

        os.makedirs(MILVUS_DATA_DIR, exist_ok=True)

        max_retries = 2  # 减少重试次数
        for attempt in range(max_retries):
            try:
                # 首次尝试前清理锁文件
                if attempt == 0:
                    _cleanup_lock_file()
                else:
                    # 重试时先杀进程再清锁
                    _kill_milvus_processes()
                    time.sleep(1)
                    _cleanup_lock_file()

                if settings.MILVUS_HOST in ("localhost", "127.0.0.1") and not settings.MILVUS_STANDALONE and settings.MILVUS_PORT != 19530:
                    log.info(f"使用Milvus Lite模式 | 数据文件: {MILVUS_DB_FILE}")
                    _milvus_client = MilvusClient(MILVUS_DB_FILE)
                else:
                    uri = f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}"
                    log.info(f"连接Milvus服务器 | URI: {uri}")
                    # 设置gRPC keepalive参数，避免too_many_pings错误
                    # pymilvus默认keepalive_time=10s，Milvus服务端认为太频繁
                    _milvus_client = MilvusClient(
                        uri=uri,
                        grpc_options={
                            "grpc.keepalive_time_ms": 60000,  # 60秒发送一次keepalive ping
                            "grpc.keepalive_timeout_ms": 30000,  # keepalive超时30秒
                            "grpc.keepalive_permit_without_calls": False,  # 无活跃RPC时不发ping
                        },
                    )

                # 验证连接
                _milvus_client.list_collections()
                _last_connect_time = 0  # 连接成功，重置冷却

                # [DEBUG] 连接成功
                _elapsed = time.time() - _start
                log.info(f"[DEBUG] 结束：get_milvus_client | 输出：client_connected=True | 耗时：{_elapsed:.2f}s")
            
                return _milvus_client

            except Exception as e:
                log.warning(f"Milvus连接尝试 {attempt + 1}/{max_retries} 失败: {e}")
                _safe_close_client(_milvus_client)
                _milvus_client = None
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    _last_connect_time = time.time()  # 记录失败时间，启动冷却
                    log.error(f"Milvus连接失败，将冷却{_CONNECT_COOLDOWN}秒")
                    if allow_fail:
                        return None
                    else:
                        raise


def create_collection(client: MilvusClient) -> None:
    """
    创建ui_element_vector集合

    字段：
    - id: 主键（自增）
    - task_id: 任务ID
    - page_name: 页面名称
    - element_name: 元素名称
    - element_type: 元素类型
    - locator: 定位器
    - description: 描述文本（用于生成embedding的原始文本）
    - embedding: 向量（384维）
    """
    # 如果集合已存在，直接返回
    if client.has_collection(COLLECTION_NAME):
        log.info(f"集合 {COLLECTION_NAME} 已存在")
        return

    # 使用MilvusClient的快捷方式创建集合（自动创建索引）
    schema = client.create_schema(auto_id=True, enable_dynamic_field=False)

    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, description="主键ID")
    schema.add_field(field_name="task_id", datatype=DataType.INT64, description="任务ID")
    schema.add_field(field_name="page_name", datatype=DataType.VARCHAR, max_length=512, description="页面名称/URL")
    schema.add_field(field_name="element_name", datatype=DataType.VARCHAR, max_length=255, description="元素名称")
    schema.add_field(field_name="element_type", datatype=DataType.VARCHAR, max_length=50, description="元素类型")
    schema.add_field(field_name="locator", datatype=DataType.VARCHAR, max_length=1024, description="定位器")
    schema.add_field(field_name="description", datatype=DataType.VARCHAR, max_length=2048, description="描述文本")
    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM, description="向量嵌入")

    # 创建索引
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        index_name="embedding_index",
        params={"nlist": 128},
    )

    # 创建集合
    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )

    log.info(f"集合 {COLLECTION_NAME} 创建成功 | 向量维度: {EMBEDDING_DIM}")


def get_or_create_collection() -> MilvusClient:
    """获取客户端并确保元素集合存在"""
    client = get_milvus_client()
    create_collection(client)
    return client


def create_case_collection(client: MilvusClient) -> None:
    """
    创建test_case_vector集合

    字段：
    - id: 主键（自增）
    - task_id: 任务ID
    - case_name: 用例名称
    - description: 用例描述
    - steps: 用例步骤(JSON)
    - embedding: 向量
    """
    if client.has_collection(CASE_COLLECTION_NAME):
        log.info(f"集合 {CASE_COLLECTION_NAME} 已存在")
        return

    schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, description="主键ID")
    schema.add_field(field_name="task_id", datatype=DataType.INT64, description="任务ID")
    schema.add_field(field_name="case_name", datatype=DataType.VARCHAR, max_length=255, description="用例名称")
    schema.add_field(field_name="description", datatype=DataType.VARCHAR, max_length=2048, description="用例描述")
    schema.add_field(field_name="steps", datatype=DataType.VARCHAR, max_length=4096, description="用例步骤JSON")
    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM, description="向量嵌入")

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        index_name="embedding_index",
        params={"nlist": 128},
    )

    client.create_collection(
        collection_name=CASE_COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
    log.info(f"集合 {CASE_COLLECTION_NAME} 创建成功 | 向量维度: {EMBEDDING_DIM}")


def create_script_collection(client: MilvusClient) -> None:
    """
    创建script_vector集合

    字段：
    - id: 主键（自增）
    - task_id: 任务ID
    - script_name: 脚本名称
    - script_content: 脚本内容
    - description: 脚本描述
    - embedding: 向量
    """
    if client.has_collection(SCRIPT_COLLECTION_NAME):
        log.info(f"集合 {SCRIPT_COLLECTION_NAME} 已存在")
        return

    schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, description="主键ID")
    schema.add_field(field_name="task_id", datatype=DataType.INT64, description="任务ID")
    schema.add_field(field_name="script_name", datatype=DataType.VARCHAR, max_length=255, description="脚本名称")
    schema.add_field(field_name="script_content", datatype=DataType.VARCHAR, max_length=8192, description="脚本内容")
    schema.add_field(field_name="description", datatype=DataType.VARCHAR, max_length=2048, description="脚本描述")
    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM, description="向量嵌入")

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="IVF_FLAT",
        metric_type="COSINE",
        index_name="embedding_index",
        params={"nlist": 128},
    )

    client.create_collection(
        collection_name=SCRIPT_COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )
    log.info(f"集合 {SCRIPT_COLLECTION_NAME} 创建成功 | 向量维度: {EMBEDDING_DIM}")


def ensure_all_collections() -> MilvusClient | None:
    """获取客户端并确保所有集合存在，Milvus不可用时返回None"""
    # [DEBUG] 数据入库前
    _start = time.time()
    log.info(f"[DEBUG] 开始：ensure_all_collections | 输入：无")

    client = get_milvus_client(allow_fail=True)
    if client is None:
        # [DEBUG] Milvus不可用
        log.warning(f"[DEBUG] 结束：ensure_all_collections | 输出：client=None (Milvus不可用) | 耗时：{time.time() - _start:.2f}s")
        return None
    create_collection(client)
    create_case_collection(client)
    create_script_collection(client)

    # [DEBUG] 数据入库后
    _elapsed = time.time() - _start
    log.info(f"[DEBUG] 结束：ensure_all_collections | 输出：client_ready=True | 耗时：{_elapsed:.2f}s")

    return client
