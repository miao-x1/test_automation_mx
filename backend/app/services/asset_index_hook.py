"""
资产索引 Hook - 既有业务模块创建资产时自动索引到测试资产中心

设计原则:
  1. 不阻塞主流程: hook 失败只记日志, 不抛异常
  2. 幂等性: ref_type+ref_id 已存在则跳过(由 AssetRegistryService 校验)
  3. 独立模块: 不耦合具体业务 service, 通过统一 register_* 接口暴露
  4. 可选调用: 既有 service 决定是否调用 hook

支持的来源模块:
  - ApiEndpointService.create_endpoint / publish_endpoint
  - (未来) TestCaseService.create_case
  - (未来) ScriptService.create_script

使用方式:
  from app.services.asset_index_hook import register_from_api_endpoint

  # 在 ApiEndpointService.create_endpoint 成功后:
  try:
      register_from_api_endpoint(endpoint_dict, user_id=user_id)
  except Exception as e:
      logger.warning(f"资产索引失败, 不影响主流程: {e}")
"""
import logging
from typing import Any, Dict, Optional

from app.schemas.asset_registry import AssetCreate
from app.services.asset_registry_service import AssetRegistryService

logger = logging.getLogger(__name__)

# 全局 service 单例(无状态, 可复用)
_registry_service: Optional[AssetRegistryService] = None


def _get_service() -> AssetRegistryService:
    """延迟加载 AssetRegistryService 单例"""
    global _registry_service
    if _registry_service is None:
        _registry_service = AssetRegistryService()
    return _registry_service


# ============================================================
# API 接口 → 资产索引
# ============================================================

def register_from_api_endpoint(
    endpoint: Dict[str, Any],
    *,
    user_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """从 API 接口创建资产索引

    在 ApiEndpointService.create_endpoint 成功后调用, 自动将接口登记为资产。
    幂等: 若 ref_type=api_endpoint + ref_id=endpoint.id 已存在, 跳过。

    Args:
        endpoint: 接口详情 dict (来自 ApiEndpointRepository.to_dict)
        user_id: 创建者 ID

    Returns:
        资产 dict (成功) / None (跳过或失败)
    """
    endpoint_id = endpoint.get("id")
    if not endpoint_id:
        logger.warning("[AssetIndexHook] endpoint.id 为空, 跳过索引")
        return None

    try:
        # 构造 extra_metadata: 包含接口关键字段
        extra_metadata: Dict[str, Any] = {
            "method": endpoint.get("method"),
            "path": endpoint.get("path"),
            "module": endpoint.get("module"),
        }
        # 可选字段
        if endpoint.get("summary"):
            extra_metadata["summary"] = endpoint["summary"]
        if endpoint.get("tags"):
            extra_metadata["tags"] = endpoint["tags"]
        if endpoint.get("auth"):
            extra_metadata["auth"] = endpoint["auth"]
        if endpoint.get("body"):
            extra_metadata["body"] = endpoint["body"]
        if endpoint.get("params"):
            extra_metadata["params"] = endpoint["params"]
        if endpoint.get("headers"):
            extra_metadata["headers"] = endpoint["headers"]
        if endpoint.get("response"):
            extra_metadata["response"] = endpoint["response"]

        payload = AssetCreate(
            name=endpoint.get("name") or f"接口 {endpoint_id}",
            asset_type="api_endpoint",
            ref_type="api_endpoint",
            ref_id=endpoint_id,
            summary=endpoint.get("summary"),
            description=endpoint.get("description"),
            module=endpoint.get("module"),
            tags=endpoint.get("tags") or [],
            source=endpoint.get("source") or "manual",
            extra_metadata=extra_metadata,
        )

        service = _get_service()
        result = service.create_asset(payload, user_id=user_id, created_by=user_id)
        logger.info(
            f"[AssetIndexHook] 接口 #{endpoint_id} 已索引为资产 "
            f"{result.get('asset_code')}"
        )
        return result

    except Exception as e:
        # 不阻塞主流程, 仅记日志
        logger.warning(
            f"[AssetIndexHook] 接口 #{endpoint_id} 索引失败 (不影响主流程): {e}"
        )
        return None


def publish_from_api_endpoint(
    endpoint_id: int,
    *,
    change_log: str = "",
    user_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """接口发布时同步发布资产索引

    在 ApiEndpointService.publish_endpoint 成功后调用。
    通过 ref_type+ref_id 反查资产, 然后调用 AssetRegistryService.publish_asset。

    Args:
        endpoint_id: 接口 ID
        change_log: 变更说明
        user_id: 操作者 ID

    Returns:
        资产 dict / None (失败或未找到资产)
    """
    try:
        from app.services.asset_search_service import AssetSearchService

        # 反查资产
        search_service = AssetSearchService()
        asset = search_service.find_by_ref(
            ref_type="api_endpoint",
            ref_id=endpoint_id,
            user_id=user_id,
        )
        if not asset:
            logger.info(
                f"[AssetIndexHook] 接口 #{endpoint_id} 未找到对应资产, "
                f"跳过发布同步"
            )
            return None

        asset_id = asset.get("id")
        if not asset_id:
            return None

        # 发布资产
        from app.schemas.asset_registry import PublishRequest
        service = _get_service()
        result = service.publish_asset(
            asset_id,
            PublishRequest(change_log=change_log or "接口发布触发", change_type="update"),
            user_id=user_id,
        )
        logger.info(
            f"[AssetIndexHook] 接口 #{endpoint_id} 对应资产 "
            f"{asset.get('asset_code')} 已发布"
        )
        return result

    except Exception as e:
        logger.warning(
            f"[AssetIndexHook] 接口 #{endpoint_id} 发布资产同步失败 "
            f"(不影响主流程): {e}"
        )
        return None


# ============================================================
# 通用注册接口 (供未来模块使用)
# ============================================================

def register_asset(
    *,
    name: str,
    asset_type: str,
    ref_type: str,
    ref_id: int,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    module: Optional[str] = None,
    tags: Optional[list] = None,
    source: str = "manual",
    extra_metadata: Optional[Dict[str, Any]] = None,
    user_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """通用资产索引注册接口

    供未来业务模块(测试用例/脚本/测试数据等)创建资产时调用。

    Args:
        name: 资产名称
        asset_type: 资产类型 (api_endpoint/ui_element/test_case/...)
        ref_type: 关联表名 (通常与 asset_type 一致)
        ref_id: 关联记录 ID
        summary: 摘要
        description: 详细描述
        module: 业务模块
        tags: 标签列表
        source: 来源
        extra_metadata: 扩展元数据
        user_id: 创建者 ID

    Returns:
        资产 dict / None (失败)
    """
    try:
        payload = AssetCreate(
            name=name,
            asset_type=asset_type,
            ref_type=ref_type,
            ref_id=ref_id,
            summary=summary,
            description=description,
            module=module,
            tags=tags or [],
            source=source,
            extra_metadata=extra_metadata,
        )
        service = _get_service()
        result = service.create_asset(payload, user_id=user_id, created_by=user_id)
        logger.info(
            f"[AssetIndexHook] {asset_type} #{ref_id} 已索引为资产 "
            f"{result.get('asset_code')}"
        )
        return result

    except Exception as e:
        logger.warning(
            f"[AssetIndexHook] {asset_type} #{ref_id} 索引失败 (不影响主流程): {e}"
        )
        return None
