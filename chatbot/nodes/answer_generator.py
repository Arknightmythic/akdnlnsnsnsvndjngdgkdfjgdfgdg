from dotenv import load_dotenv

from chatbot.state import SQLState
from chatbot.chains.answer_generation import AnswerGeneration

load_dotenv()

class AnswerGenerator:
    def generate_answer(state: SQLState)-> SQLState:
        question = state.get("question")
        result_query = state.get("result")
        schema = state.get("schema")

        chain = AnswerGeneration().get_chain()
        result = chain.invoke({
            "question": question,
            "schema": schema,
            "query_result": result_query
        })

        return {"answer": result.answer}
