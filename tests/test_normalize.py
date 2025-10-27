"""Tests for data normalization utilities."""

from huntstand_exporter.exporter import as_dict, json_or_list_to_objects


def test_as_dict():
    """Test as_dict helper function."""
    assert as_dict({"a": 1}) == {"a": 1}
    assert as_dict(None) == {}
    assert as_dict(5) == {}


def test_json_or_list_to_objects_list():
    """Test json_or_list_to_objects with list input."""
    data = [{"x": 1}, {"y": 2}]
    assert json_or_list_to_objects(data) == data


def test_json_or_list_to_objects_objects_key():
    """Test json_or_list_to_objects with 'objects' key wrapper."""
    data = {"objects": [{"a": 1}, {"b": 2}]}
    assert json_or_list_to_objects(data) == [{"a": 1}, {"b": 2}]


def test_json_or_list_to_objects_dict_values():
    """Test json_or_list_to_objects with plain dict."""
    data = {"a": {"v": 1}, "b": {"v": 2}}
    out = json_or_list_to_objects(data)
    assert isinstance(out, list)
    assert {d.get("v") for d in out} == {1, 2}


def test_json_or_list_to_objects_none():
    """Test json_or_list_to_objects with None input."""
    assert json_or_list_to_objects(None) == []
