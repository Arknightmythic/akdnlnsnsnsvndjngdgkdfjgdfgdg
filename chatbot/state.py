from typing import TypedDict

class ExecutionState(TypedDict):
    query: str
    error_message: str
    is_dangerous: bool
    query_result: str