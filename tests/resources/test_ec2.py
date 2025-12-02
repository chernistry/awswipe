import pytest
from unittest.mock import MagicMock
from awswipe.resources.ec2 import EC2Cleaner
from awswipe.core.config import Config

@pytest.fixture
def mock_session():
    return MagicMock()

@pytest.fixture
def mock_config():
    return Config(dry_run=False)

def test_ec2_cleanup(mock_session, mock_config):
    ec2_client = MagicMock()
    mock_session.client.return_value = ec2_client
    
    # Mock describe_instances
    ec2_client.describe_instances.return_value = {
        'Reservations': [{
            'Instances': [{'InstanceId': 'i-12345'}]
        }]
    }
    
    # Mock describe_instance_attribute (termination protection)
    ec2_client.describe_instance_attribute.return_value = {
        'DisableApiTermination': {'Value': True}
    }
    
    cleaner = EC2Cleaner(mock_session, mock_config, {})
    cleaner.cleanup('us-east-1')
    
    # Verify termination protection disabled
    ec2_client.modify_instance_attribute.assert_called_with(
        InstanceId='i-12345',
        DisableApiTermination={'Value': False}
    )
    
    # Verify terminate called
    ec2_client.terminate_instances.assert_called_with(InstanceIds=['i-12345'])

def test_ec2_cleanup_dry_run(mock_session):
    config = Config(dry_run=True)
    ec2_client = MagicMock()
    mock_session.client.return_value = ec2_client
    
    ec2_client.describe_instances.return_value = {
        'Reservations': [{
            'Instances': [{'InstanceId': 'i-12345'}]
        }]
    }
    
    cleaner = EC2Cleaner(mock_session, config, {})
    cleaner.cleanup('us-east-1')
    
    # Verify terminate NOT called
    ec2_client.terminate_instances.assert_not_called()
    ec2_client.modify_instance_attribute.assert_not_called()
