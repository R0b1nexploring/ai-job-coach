import pytest

from app.providers.llm.json_repair import loads_lenient


def test_loads_lenient_accepts_direct_json_object():
    assert loads_lenient('{"value": "直接解析"}') == {"value": "直接解析"}


def test_loads_lenient_strips_markdown_json_fence():
    assert loads_lenient('```json\n{"value": "围栏"}\n```') == {"value": "围栏"}


def test_loads_lenient_extracts_object_from_wrapper_text():
    assert loads_lenient('结果如下：\n{"value": "包裹"}\n请查收。') == {"value": "包裹"}


def test_loads_lenient_rejects_invalid_or_non_object_json():
    with pytest.raises(ValueError, match="有效 JSON 对象"):
        loads_lenient("这不是 JSON")
    with pytest.raises(ValueError, match="有效 JSON 对象"):
        loads_lenient('["不是对象"]')
