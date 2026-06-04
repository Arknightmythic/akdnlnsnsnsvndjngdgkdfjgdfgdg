from dotenv import load_dotenv

from chatbot.state import SQLState
from chatbot.nodes.query_validator import QueryValidator
from chatbot.nodes.query_executor import QueryExecutor

load_dotenv()

def test_query_validator_select_valid():
    state_mock = {"query": "SELECT * FROM master"}
    result: SQLState = QueryValidator.validate_query(state_mock)
    print(f"Result: {result}")

    assert result.get("is_dangerous") is False

def test_query_validator_select_clean_markdown():
    state_mock = {"query": "```sql\nSELECT COUNT(*) FROM uploaded_files\n```"}
    result: SQLState = QueryValidator.validate_query(state_mock)
    print(f"Result: {result}")

    assert result.get("is_dangerous") is False

def test_query_validator_dangerous_delete():
    state_mock = {"query": "DELETE FROM master WHERE id = 1"}
    result: SQLState = QueryValidator.validate_query(state_mock)

    print(f"Result: {result}")
    assert result.get("is_dangerous") is True
    assert "[WARNING]" in result.get("result")

def test_query_validator_dangerous_update():
    state_mock = {"query": "UPDATE uploaded_files SET status = 'FAILED'"}
    result: SQLState = QueryValidator.validate_query(state_mock)
    print(f"Result: {result}")

    assert result.get("is_dangerous") is True

def test_query_validator_dangerous_truncate():
    state_mock = {"query": "TRUNCATE TABLE institution"}
    result: SQLState = QueryValidator.validate_query(state_mock)
    print(f"Result: {result}")

    assert result.get("is_dangerous") is True

def test_query_validator_not_starting_with_select():
    state_mock = {"query": "SHOW TABLES"}
    result: SQLState = QueryValidator.validate_query(state_mock)
    print(f"Result: {result}")

    assert result.get("is_dangerous") is True
    assert "not a SELECT statement" in result.get("result")

def test_query_validator_subquery_injection():
    state_mock = {"query": "SELECT * FROM master WHERE nama = 'drop it'"}
    result: SQLState = QueryValidator.validate_query(state_mock)
    print(f"Result: {result}")

    assert result.get("is_dangerous") is True

def test_query_executor_valid_select():
    state_mock = {"query": "SELECT * FROM master LIMIT 10"}
    result: SQLState = QueryExecutor.execution_query(state_mock)
    print(f"Result: {result}")

    assert "Query executed successfully" in result.get("result")

def test_query_executor_valid_select_markdown():
    state_mock = {"query": "```sql\nSELECT count(*) FROM master;\n```"}
    result: SQLState = QueryExecutor.execution_query(state_mock)
    print(f"Result: {result}")

    assert result.get("error_message") is None
    assert "Query executed successfully" in result.get("result")

def test_query_executor_no_results():
    state_mock = {"query": "SELECT * FROM master WHERE nama = 'DataPalsuYangMustahilAda123'"}
    result: SQLState = QueryExecutor.execution_query(state_mock)
    print(f"Result: {result}")

    assert result.get("error_message") is None
    assert "Query executed successfully" in result.get("result")

def test_query_executor_syntax_error():
    state_mock = {"query": "SELECT * FROM tabel_yang_tidak_ada_123"}
    result: SQLState = QueryExecutor.execution_query(state_mock)
    print(f"Result: {result}")

    assert result.get("error_message") is not None
    assert result.get("result") is None