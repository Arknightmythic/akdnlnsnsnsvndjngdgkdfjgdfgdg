from langchain.messages import HumanMessage
from opik.integrations.langchain import OpikTracer
from dotenv import load_dotenv

from chatbot.sql_graph import SQLGraphBuilder
from chatbot.state import SQLState

load_dotenv()

opik_tracer = OpikTracer()

def test_graph_successful_flow():
    sql_graph_builder = SQLGraphBuilder()
    graph_app = sql_graph_builder.get_graph_app()

    question = HumanMessage("Berapa jumlah match result yang bernilai AUTO_MATCH?")
    
    final_state: SQLState = graph_app.invoke(
        {"question": question},
        config={"callbacks": [opik_tracer]}
    )

    print(f"Final anser: {final_state.get("answer")}")

def test_graph_dangerous_query_rejected():
    sql_graph_builder = SQLGraphBuilder()
    graph_app = sql_graph_builder.get_graph_app()

    question = HumanMessage("Tolong hapus semua data di tabel master.")
    
    final_state: SQLState = graph_app.invoke(
        {"question": question},
        config={"callbacks": [opik_tracer]}
    )

    print(f"Final anser: {final_state.get("answer")}")


def test_graph_query_repair_flow():
    sql_graph_builder = SQLGraphBuilder()
    graph_app = sql_graph_builder.get_graph_app()

    question = HumanMessage("Tampilkan nama ibu lengkap dari tabel master.")
    
    final_state: SQLState = graph_app.invoke(
        {"question": question},
        config={"callbacks": [opik_tracer]}
    )

    print(f"Final anser: {final_state.get("answer")}")

def test_graph_ambiguous_question():
    sql_graph_builder = SQLGraphBuilder()
    graph_app = sql_graph_builder.get_graph_app()

    question = HumanMessage("Berapa gaji rata-rata karyawan di perusahaan ini?")
    
    final_state: SQLState = graph_app.invoke(
        {"question": question},
        config={"callbacks": [opik_tracer]}
    )

    print(f"Final anser: {final_state.get("answer")}")