import pytest
from chatbot.handler import SynchronoAgent
from dotenv import load_dotenv

load_dotenv()

@pytest.fixture
def agent():
    return SynchronoAgent()

def test_agent_complex_join_reference_tables(agent):
    conversation_id ="test_complex_join"
    question ="Tampilkan 5 data institution pertama, sertakan deskripsi hasil match-nya"
    
    response = agent.ask(conversation_id, question)
    
    print(f"Response: {response}")
    
    assert response is not None
    assert len(response) > 0
    assert "|" in response
    assert any(keyword in response.lower() for keyword in ["hasil", "match", "deskripsi"])

def test_agent_aggregation_with_time_units(agent):
    conversation_id = "test_time_aggregation"
    question ="Berapa rata-rata waktu grading (dalam detik) untuk semua file?"
    
    response = agent.ask(conversation_id, question)
    
    print(f"Response: {response}")
    
    assert response is not None
    assert any(keyword in response.lower() for keyword in ["rata-rata", "detik", "grading"])
    assert "ms" not in response.lower() or "detik" in response.lower()

def test_agent_unauthorized_operation(agent):
    conversation_id = "test_unauthorized"
    question ="Hapus semua data dari tabel master"
    
    response = agent.ask(conversation_id, question)
    
    print(f"Response: {response}")
    
    assert response is not None
    assert any(keyword in response.lower() for keyword in ["maaf", "tidak bisa", "akses", "baca saja", "unauthorized"])

def test_agent_no_data_found(agent):
    conversation_id = "test_no_data"
    question ="Tampilkan data master dengan nama 'ZzzXxxYyy123'"
    
    response = agent.ask(conversation_id, question)
    
    print(f"Response: {response}")
    
    assert response is not None
    assert any(keyword in response.lower() for keyword in ["tidak ditemukan", "kosong", "tidak ada", "maaf"])

def test_agent_multi_table_summary(agent):
    conversation_id = "test_summary"
    question ="Berapa banyak file yang diupload dan berapa total baris data di tabel master?"
    
    response = agent.ask(conversation_id, question)
    
    print(f"Response: {response}")
    
    assert response is not None
    assert any(keyword in response.lower() for keyword in ["total", "jumlah", "file", "master"])
