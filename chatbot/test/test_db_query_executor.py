import pytest
from chatbot.tools.db_query_executor import RunQueryBuilder

def test_query_with_created_at_is_safe():
    builder = RunQueryBuilder()
    state = {"query": "SELECT uf.created_at FROM uploaded_files AS uf ORDER BY uf.created_at DESC LIMIT 1"}
    result = builder._validate_query(state)
    assert not result.get("is_dangerous"), f"Query was incorrectly flagged as dangerous: {result}"

def test_query_with_updated_at_is_safe():
    builder = RunQueryBuilder()
    state = {"query": "SELECT uf.updated_at FROM uploaded_files AS uf LIMIT 10"}
    result = builder._validate_query(state)
    assert not result.get("is_dangerous"), f"Query was incorrectly flagged as dangerous: {result}"

def test_query_auto_appends_limit_if_missing():
    builder = RunQueryBuilder()
    state = {"query": "SELECT * FROM manual_matches WHERE nama_incoming LIKE '%Zulaikha%'"}
    result = builder._validate_query(state)
    assert not result.get("is_dangerous")
    assert "LIMIT 50" in result.get("query")

def test_query_does_not_append_limit_if_already_present():
    builder = RunQueryBuilder()
    state = {"query": "SELECT * FROM manual_matches LIMIT 5"}
    result = builder._validate_query(state)
    assert result.get("query") == "SELECT * FROM manual_matches LIMIT 5"

def test_query_with_aggregate_does_not_require_limit():
    builder = RunQueryBuilder()
    state = {"query": "SELECT COUNT(*) FROM manual_matches"}
    result = builder._validate_query(state)
    assert "LIMIT 50" not in result.get("query")

def test_query_with_actual_dangerous_drop():
    builder = RunQueryBuilder()
    state = {"query": "DROP TABLE uploaded_files"}
    result = builder._validate_query(state)
    assert result.get("is_dangerous") is True
