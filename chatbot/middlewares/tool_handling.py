from langchain.agents.middleware import wrap_tool_call
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.types import Command
from collections.abc import Callable, Awaitable # Tambahkan Awaitable jika menggunakan type hint yang ketat

class ToolHandlingMiddleware:
    @staticmethod
    @wrap_tool_call
    # 1. Ubah menjadi async def
    async def monitor(request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        try:
            # 2. Tambahkan await karena handler berjalan di context asynchronous
            result = await handler(request)
            return result
        except Exception as e:
            tool_call_id = request.tool_call_id

            if "column" in str(e).lower():
                return ToolMessage(
                    tool_call_id=tool_call_id,
                    content=f"[COLUMN ERROR] There was an error related to column names: {str(e)}. Please check table schemas and column names using the `get_table_detail` tool before retrying."
                )
            elif "table" in str(e).lower():
                return ToolMessage(
                    tool_call_id=tool_call_id,
                    content=f"[TABLE ERROR] There was an error related to table names: {str(e)}. Please check available tables using the `get_table_names` tool before retrying."
                )
            raise e