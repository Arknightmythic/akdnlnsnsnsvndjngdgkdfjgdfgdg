from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage
from chatbot.state import ExecutionState      
from dotenv import load_dotenv

from chatbot.nodes.query_validator import QueryValidator
from chatbot.nodes.query_executor import QueryExecutor

load_dotenv()

def is_dangerous(state: ExecutionState):
    if state["is_dangerous"]:
        return "dangerous"
    return "safe"


class SQLExecutionWorkflow:
    def __init__(self):
        self.workflow = StateGraph(ExecutionState)

        self.workflow.add_node("query_validator", QueryValidator.validate_query) 
        self.workflow.add_node("query_executor", QueryExecutor.execution_query) 

        self.workflow.add_edge(START, "query_validator")
        self.workflow.add_conditional_edges("query_validator", is_dangerous, {
            "dangerous": END, 
            "safe": "query_executor"
        })
        self.workflow.add_edge("query_executor", END)
        self._compiled_app = self.workflow.compile()

    def get_graph_app(self):
        return self._compiled_app

executor_graph = SQLExecutionWorkflow().get_graph_app()

if __name__ == "__main__":
    executor_graph.get_graph().draw_mermaid_png(output_file_path="chatbot/execution_graph.png")