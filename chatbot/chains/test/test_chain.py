from langchain.messages import HumanMessage
from dotenv import load_dotenv

from chatbot.db import db
from chatbot.chains.query_generation import QueryGeneration, QueryGenerationOutput
from chatbot.chains.query_repair import QueryRepair, QueryRepairOutput
from chatbot.chains.answer_generation import AnswerGeneration, AnswerGenerationOutput

load_dotenv()

def test_query_generation_answer_select():
    schema = db.get_table_info()
    question = HumanMessage("Berapa jumlah match result yang bernilai AUTOMATCH")

    chain = QueryGeneration().get_chain()
    result: QueryGenerationOutput = chain.invoke({
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

def test_query_repair_unknown_column():
    schema = db.get_table_info()
    question = HumanMessage("Tampilkan nama ibu dan nik dari tabel master")
    bad_query = "SELECT nama_ibu_kandung, nik FROM master" 
    error_message = "1054 (42S22): Unknown column 'nama_ibu_kandung' in 'field list'"

    chain = QueryRepair().get_chain()
    result: QueryRepairOutput = chain.invoke({
        "schema": schema,
        "query": bad_query,
        "error_message": error_message,
        "question": question
    })

    print(f"Repaired Query: {result.fixed_query}")
    query_lower = result.fixed_query.lower()
    
    assert "select" in query_lower
    assert "nama_ibu" in query_lower
    assert "nama_ibu_kandung" not in query_lower


def test_query_repair_syntax_error_group_by():
    schema = db.get_table_info()
    question = HumanMessage("Hitung jumlah row_count per status processing")
    bad_query = "SELECT processing_status, row_count FROM uploaded_files"
    error_message = "1140 (42000): In aggregated query without GROUP BY, expression #2 of SELECT list contains nonaggregated column"

    chain = QueryRepair().get_chain()
    result: QueryRepairOutput = chain.invoke({
        "schema": schema,
        "query": bad_query,
        "error_message": error_message,
        "question": question
    })

    print(f"Repaired Query: {result.fixed_query}")
    query_lower = result.fixed_query.lower()
    
    assert "group by" in query_lower or "sum(" in query_lower


def test_query_repair_rejects_dml():
    schema = db.get_table_info()
    question = HumanMessage("Hapus data di tabel master yang nik nya kosong")
    bad_query = "DELETE FROM master WHERE nik IS NULL"
    error_message = "1175 (HY000): You are using safe update mode and you tried to update a table without a WHERE that uses a KEY column"

    chain = QueryRepair().get_chain()
    result: QueryRepairOutput = chain.invoke({
        "schema": schema,
        "query": bad_query,
        "error_message": error_message,
        "question": question
    })

    print(f"Repaired Query: {result.fixed_query}")
    query_lower = result.fixed_query.lower()

    assert "delete" not in query_lower
    assert "update" not in query_lower

def test_answer_generation_single_value():
    question = HumanMessage("Berapa jumlah file yang sudah diunggah?")
    query_result = "[(150,)]"

    chain = AnswerGeneration().get_chain()
    result: AnswerGenerationOutput = chain.invoke({
        "question": question,
        "query_result": query_result
    })

    print(f"Generated Answer: {result.answer}")
    answer_lower = result.answer.lower()

    assert "150" in answer_lower
    assert "file" in answer_lower

def test_answer_generation_multiple_rows():
    question = HumanMessage("Sebutkan 3 original filename pertama beserta grade-nya")
    query_result = "[('data_penduduk_jabar.csv', 'A'), ('data_penduduk_jateng.csv', 'B'), ('data_penduduk_jatim.csv', 'A')]"

    chain = AnswerGeneration().get_chain()
    result: AnswerGenerationOutput = chain.invoke({
        "question": question,
        "query_result": query_result
    })

    print(f"Generated Answer: {result.answer}")
    answer_lower = result.answer.lower()
    
    assert "data_penduduk_jabar.csv" in answer_lower
    assert "grade" in answer_lower

def test_answer_generation_empty_result():
    question = HumanMessage("Siapa saja nama orang dari provinsi antartika?")
    query_result = "[]"

    chain = AnswerGeneration().get_chain()
    result: AnswerGenerationOutput = chain.invoke({
        "question": question,
        "query_result": query_result
    })

    print(f"Generated Answer: {result.answer}")
    answer_lower = result.answer.lower()
    
    assert any(word in answer_lower for word in ["tidak", "kosong", "belum", "maaf", "no"])