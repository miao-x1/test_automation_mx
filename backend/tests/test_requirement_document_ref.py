"""P1-3: 文档上传后任务必须持久化真实路径，不能只存文件名。"""
from app.api.requirement import _pack_additional_info, _unpack_additional_info


def test_pack_document_paths_not_filename_only():
    packed = _pack_additional_info("备注", ["requirement_documents/abc123.pdf"])
    note, docs = _unpack_additional_info(packed)
    assert note == "备注"
    assert docs == ["requirement_documents/abc123.pdf"]
    assert "report.pdf" not in packed or "requirement_documents" in packed


def test_unpack_plain_additional_info():
    note, docs = _unpack_additional_info("https://www.baidu.com")
    assert note == "https://www.baidu.com"
    assert docs == []


def test_pack_without_documents_keeps_note():
    assert _pack_additional_info("hello", None) == "hello"
    assert _pack_additional_info("hello", []) == "hello"
