import pytest
from chatbot.handler import SynchronoAgent
from dotenv import load_dotenv

load_dotenv()

agent = SynchronoAgent()

def test_agent_fix_field():
    question = "Field mana yang paling perlu diperbaiki?"
    response = agent.ask("test_sql_1", question)
    
    print(f"Response: {response}")

def test_agent_count():
    question = "Apa saja jenis jenis match result dan berapa masing masing jumlahnya?"
    response = agent.ask("test_sql_2", question)
    
    print(f"Response: {response}")

def test_agent_manual_review():
    question = "Kenapa id 8302843 pada tabel intitution masuk manual review?"
    response = agent.ask("test_sql_3", question)
    
    print(f"Response: {response}")

def test_agent_short_term_memory():
    question = "nama saya Maulana"
    response = agent.ask("test_sql_4", question)
    question = "inget gk siapa nama saya?"
    response = agent.ask("test_sql_4", question)
    
    print(f"Response: {response}")