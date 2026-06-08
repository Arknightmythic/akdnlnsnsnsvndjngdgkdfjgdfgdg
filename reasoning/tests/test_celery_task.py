import pytest
from unittest.mock import MagicMock, patch

def test_enqueue_endpoint():
    """
    Test apakah fungsi handler enqueue_reasoning berhasil mengirim task
    """
    from reasoning.handler import ReasoningHandler
    
    # Setup handler dengan engine mock (tidak perlu minio lagi)
    handler = ReasoningHandler(MagicMock())
    
    with patch("reasoning.tasks.trigger_rows_for_file.delay") as mock_delay:
        mock_task = MagicMock()
        mock_task.id = "fake-task-id"
        mock_delay.return_value = mock_task
        
        res = handler.enqueue_reasoning("file_123")
        
        mock_delay.assert_called_once_with("file_123")
        assert res["status"] == "queued"
        assert res["file_id"] == "file_123"
        assert res["task_id"] == "fake-task-id"
