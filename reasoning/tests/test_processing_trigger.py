import pytest
from unittest.mock import MagicMock, patch
import sys
import os

# Menambahkan root project ke sys.path jika belum ada
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from processing.handler import MatchFileHandler

import asyncio

@patch('reasoning.tasks.trigger_rows_for_file.delay')
def test_processing_hits_reasoning_orchestrator(mock_trigger_delay):
    """
    Skenario: Memastikan bahwa setelah proses matching selesai (grade A-E),
    kode di processing/handler.py benar-benar melempar (hit) task orchestrator
    ke modul AI Reasoning milik kita via Celery.
    """
    async def run_test():
        # 1. Setup Mock Dependencies untuk MatchFileHandler
        mock_minio = MagicMock()
        mock_engine = MagicMock()
        bucket_name = "test-bucket"
        
        # 2. Inisialisasi Handler
        handler = MatchFileHandler(
            minio_client=mock_minio,
            bucket_name=bucket_name,
            starrocks_engine=mock_engine
        )
        
        # 3. Mock Data & Fungsi di MatchingService agar tidak error
        file_id = "testing-file-123"
        
        # Mock starrocks_service.get_uploaded_file (Anggap file ini grade 1 / Grade A)
        handler.matching_service.starrocks_service = MagicMock()
        handler.matching_service.starrocks_service.get_uploaded_file = MagicMock(return_value={"grade": 1})
        
        # Mock proses matching agar tidak benar-benar jalan
        handler.matching_service.process_grade_a = MagicMock(return_value={"status": "matched"})
        
        # 4. Eksekusi fungsi process_file
        result = await handler.process_file(file_id)
        
        # 5. Verifikasi Hasil (Assert)
        # Pastikan process_grade_a terpanggil
        handler.matching_service.process_grade_a.assert_called_once_with(file_id)
        
        # [INTI TEST]: Pastikan modul AI Reasoning kita (trigger_rows_for_file) benar-benar di-hit!
        mock_trigger_delay.assert_called_once_with(file_id)
        
        # Pastikan result dikembalikan dengan benar
        assert result == {"status": "matched"}
        print("\n[SUCCESS] processing/handler.py berhasil menembak modul AI Reasoning!")
        
    asyncio.run(run_test())
    print("\n[SUCCESS] processing/handler.py berhasil menembak modul AI Reasoning!")

@patch('reasoning.tasks.trigger_rows_for_file.delay')
def test_processing_hits_reasoning_orchestrator_grade_3(mock_trigger_delay):
    """
    Skenario: Memastikan trigger tetap terkirim meskipun file_id memiliki grade berbeda (misal grade 3).
    """
    async def run_test():
        mock_minio = MagicMock()
        mock_engine = MagicMock()
        
        handler = MatchFileHandler(mock_minio, "test-bucket", mock_engine)
        file_id = "testing-file-grade-3"
        
        # File memiliki grade 3
        handler.matching_service.starrocks_service = MagicMock()
        handler.matching_service.starrocks_service.get_uploaded_file = MagicMock(return_value={"grade": 3})
        handler.matching_service.process_grade_c = MagicMock(return_value={"status": "matched_c"})
        
        await handler.process_file(file_id)
        
        # Pastikan process_grade_c dipanggil
        handler.matching_service.process_grade_c.assert_called_once_with(file_id)
        
        # Modul AI Reasoning HARUS tetap di-hit
        mock_trigger_delay.assert_called_once_with(file_id)

    asyncio.run(run_test())
