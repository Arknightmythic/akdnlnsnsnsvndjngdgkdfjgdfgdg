from langchain.messages import AIMessage
from langgraph.runtime import Runtime
from dotenv import load_dotenv

from chatbot.middlewares import PIIMiddleware

load_dotenv()


def test_pii_nik():
    """
    utk nik hanya menampilkan 3 digit terakhir saja, sisanya ditimpa pke "*"
    contoh:
    - 1234567890123456 (16 digit) -> *************456
    """
    mask_nik_length = 16-3
    question = AIMessage("Berikut adalah 3 data dari tabel `institution` beserta NIK-nya:\n\n| ID | ID Incoming | NIK Master |\n| :--- | :--- | :--- |\n| 6499996 | 2521 | 9502906601690558 |\n| 6500014 | 2539 | 7205415202884752 |\n| 6500023 | 2548 | 9428506203920227 |")
    pii_middleware_nik = PIIMiddleware(pii_type="nik", detector=r"\b\d{16}\b", strategy="mask")
    state = {"messages": [question]}

    result = pii_middleware_nik.after_agent(state=state, runtime=Runtime())

    assert "*"*mask_nik_length in result["messages"][-1].text