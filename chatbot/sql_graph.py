from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv

from chatbot.state import SQLState
from chatbot.nodes.schema_getter import SchemaGetter
from chatbot.nodes.query_generator import QueryGenerator
from chatbot.nodes.query_validator import QueryValidator
from chatbot.nodes.query_executor import QueryExecutor
from chatbot.nodes.query_repairment import QueryRepairement
from chatbot.nodes.answer_generator import AnswerGenerator

load_dotenv()

def is_dangerous(state: SQLState):
    if state["is_dangerous"]:
        return "dangerous"
    return "safe"

def is_error(state: SQLState):
    error_message = state["error_message"]
    if error_message:
        return "error"
    return "success"

class SQLGraphBuilder:
    def __init__(self):
        self.workflow = StateGraph(SQLState)

        self.workflow.add_node("schema_getter", SchemaGetter.get_schema) 
        self.workflow.add_node("query_generator", QueryGenerator.generate_query) 
        self.workflow.add_node("query_validator", QueryValidator.validate_query) 
        self.workflow.add_node("query_executor", QueryExecutor.execution_query) 
        self.workflow.add_node("query_repairment", QueryRepairement.repair_query) 
        self.workflow.add_node("answer_generator", AnswerGenerator.generate_answer)

        self.workflow.add_edge(START, "schema_getter")
        self.workflow.add_edge("schema_getter", "query_generator")
        self.workflow.add_edge("query_generator", "query_validator")
        self.workflow.add_conditional_edges("query_validator", is_dangerous, {
            "dangerous": "answer_generator", 
            "safe": "query_executor"
        })
        self.workflow.add_conditional_edges("query_executor", is_error, {
            "success": "answer_generator",
            "error": "query_repairment"
        })
        self.workflow.add_edge("query_repairment", "query_executor")
        self.workflow.add_edge("answer_generator", END)
        self._compiled_app = self.workflow.compile()

    def get_graph_app(self):
        return self._compiled_app
        

if __name__ == "__main__":
    sql_graph = SQLGraphBuilder().get_graph_app()
    sql_graph.get_graph().draw_mermaid_png(output_file_path="chatbot/sql_graph.png")