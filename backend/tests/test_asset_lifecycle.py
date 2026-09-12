from app.services.asset_lifecycle import PILLARS, STAGE_MAP, STAGES, TYPE_BY_STAGE, serialize
from app.models.asset_registry import AssetRegistry, AssetRegistrySource


def test_ten_stages_exist():
    assert len(STAGES) == 10
    assert list(STAGE_MAP) == [item["key"] for item in STAGES]
    assert all(item["categories"] for item in STAGES)
    assert TYPE_BY_STAGE["04_cases"] == "test_case"
    assert TYPE_BY_STAGE["05_scripts"] == "script"
    assert [item["key"] for item in PILLARS] == ["workspace", "understand", "design", "execute"]
    assert all(item.get("pillar") for item in STAGES)
    assert {item["pillar"] for item in STAGES} == {"understand", "design", "execute"}


def test_serialize_uses_stage_metadata():
    asset = AssetRegistry(
        id=1,
        asset_code="ASSET-2026-0001",
        name="登录需求",
        asset_type="requirement",
        ref_type="requirement",
        ref_id=1,
        module="01_analysis",
        source=AssetRegistrySource.AI,
        status="active",
        version=1,
        extra_metadata='{"stage":"01_analysis","category":"页面分析","project_id":3,"reusable":true}',
    )
    data = serialize(asset, relation_count=2)
    assert data["stage"] == "01_analysis"
    assert data["stage_name"] == "需求分析"
    assert data["pillar"] == "understand"
    assert data["pillar_name"] == "项目理解"
    assert data["origin"] == "AI生成"
    assert data["relation_count"] == 2
    assert data["project_id"] == 3
