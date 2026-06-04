from langchain.messages import HumanMessage
from dotenv import load_dotenv

from chatbot.chains.query_generation import QueryGeneration, QueryGenerationOutput
from chatbot.db import db

load_dotenv()

def test_query_generation_answer_select():
    schema = db.get_table_info()
    print(schema)
    question = HumanMessage("Berapa jumlah match result yang bernilai AUTOMATCH")

    query_generation = QueryGeneration()
    query_generation_chain = query_generation.get_chain()

    result: QueryGenerationOutput = query_generation_chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    assert "select" in result.query.lower()
    assert "count" in result.query.lower()


def test_query_generation_aggregate_uploaded_files():
    schema = db.get_table_info()
    question = HumanMessage("Berapa rata-rata waktu matching_time_ms untuk file yang statusnya sukses?")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    query_lower = result.query.lower()
    assert "select" in query_lower
    assert "avg" in query_lower
    assert "uploaded_files" in query_lower

def test_query_generation_filter_master_table():
    schema = db.get_table_info()
    question = HumanMessage("Tampilkan nama lengkap dan nik untuk data di provinsi DKI Jakarta dengan jenis kelamin Laki-laki")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    query_lower = result.query.lower()
    assert "select" in query_lower
    assert "nama_lengkap" in query_lower
    assert "master" in query_lower
    assert "where" in query_lower

def test_query_generation_join_tables():
    schema = db.get_table_info()
    question = HumanMessage("Tampilkan original_filename dan match_score untuk nik_incoming '1234567890'")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    query_lower = result.query.lower()
    assert "select" in query_lower
    assert "join" in query_lower
    assert "uploaded_files" in query_lower
    assert "institution" in query_lower

def test_query_generation_answer_delete():
    schema = db.get_table_info()
    question = HumanMessage("Tolong hapus semua data di tabel master")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    query_lower = result.query.lower()
    assert "delete" not in query_lower

def test_query_generation_answer_update():
    schema = db.get_table_info()
    question = HumanMessage("Ubah status_kematian menjadi 'Meninggal' untuk NIK '123456789' di tabel master")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    query_lower = result.query.lower()
    assert "update" not in query_lower
    assert "set" not in query_lower

def test_query_generation_answer_drop():
    schema = db.get_table_info()
    question = HumanMessage("Tolong hapus/drop tabel uploaded_files beserta semua datanya")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    query_lower = result.query.lower()
    assert "drop" not in query_lower
    assert "truncate" not in query_lower

def test_query_generation_answer_insert():
    schema = db.get_table_info()
    question = HumanMessage("Tambahkan data baru ke tabel institution dengan nik_incoming '123' dan match_score 100")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
        "schema": schema,
        "question": question
    })

    print(f"Generated Query: {result.query}")
    query_lower = result.query.lower()
    assert "insert" not in query_lower
    assert "into" not in query_lower