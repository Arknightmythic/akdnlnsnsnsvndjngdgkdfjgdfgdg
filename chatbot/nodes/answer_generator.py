from dotenv import load_dotenv

from chatbot.state import SQLState
from chatbot.chains.answer_generation import AnswerGeneration

load_dotenv()

class AnswerGenerator:
    def generate_answer(state: SQLState)-> SQLState:
        question = state.get("question")
        result_query = state.get("result")

        chain = AnswerGeneration().get_chain()
        result = chain.invoke({
            "question": question,
            "result": result_query
        })

        return {"answer": result.answer}
