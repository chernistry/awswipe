import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError
from awswipe.core.retry import retry_delete, retry_delete_with_backoff

def test_retry_delete_success():
    mock_op = MagicMock(return_value="success")
    result = retry_delete(mock_op, "test op")
    assert result == "success"
    assert mock_op.call_count == 1

def test_retry_delete_throttling():
    # Simulate throttling then success
    error_response = {'Error': {'Code': 'Throttling'}}
    throttling_error = ClientError(error_response, 'test')
    
    mock_op = MagicMock(side_effect=[throttling_error, throttling_error, "success"])
    
    with patch('time.sleep') as mock_sleep: # Don't actually sleep
        result = retry_delete(mock_op, "test op")
        
    assert result == "success"
    assert mock_op.call_count == 3

def test_retry_delete_failure():
    error_response = {'Error': {'Code': 'SomeOtherError'}}
    other_error = ClientError(error_response, 'test')
    
    mock_op = MagicMock(side_effect=other_error)
    
    with pytest.raises(ClientError):
        retry_delete(mock_op, "test op")
    
    assert mock_op.call_count == 1

def test_retry_delete_max_retries():
    error_response = {'Error': {'Code': 'Throttling'}}
    throttling_error = ClientError(error_response, 'test')
    
    mock_op = MagicMock(side_effect=throttling_error)
    
    with patch('time.sleep'):
        with pytest.raises(Exception) as excinfo:
            retry_delete(mock_op, "test op", max_attempts=3)
    
    assert "Max retries (3) exceeded" in str(excinfo.value)
    assert mock_op.call_count == 3
