from typing import TypedDict

class SQLState(TypedDict):
    question: str
    schema: str
    query: str
    error_message: str
    is_dangerous: bool
    result: str
    answer: str