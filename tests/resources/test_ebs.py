import pytest
from unittest.mock import MagicMock
from awswipe.resources.ebs import EBSCleaner
from awswipe.core.config import Config

@pytest.fixture
def mock_session():
    return MagicMock()

@pytest.fixture
def mock_config():
    return Config(dry_run=False)

def test_ebs_cleanup(mock_session, mock_config):
    ec2_client = MagicMock()
    mock_session.client.return_value = ec2_client
    
    # Mock describe_volumes
    ec2_client.describe_volumes.return_value = {
        'Volumes': [{'VolumeId': 'vol-123'}]
    }
    
    # Mock describe_snapshots
    ec2_client.describe_snapshots.return_value = {
        'Snapshots': [{'SnapshotId': 'snap-456'}]
    }
    
    cleaner = EBSCleaner(mock_session, mock_config, {})
    cleaner.cleanup('us-east-1')
    
    ec2_client.delete_volume.assert_called_with(VolumeId='vol-123')
    ec2_client.delete_snapshot.assert_called_with(SnapshotId='snap-456')

def test_ebs_cleanup_dry_run(mock_session):
    config = Config(dry_run=True)
    ec2_client = MagicMock()
    mock_session.client.return_value = ec2_client
    
    ec2_client.describe_volumes.return_value = {
        'Volumes': [{'VolumeId': 'vol-123'}]
    }
    ec2_client.describe_snapshots.return_value = {
        'Snapshots': [{'SnapshotId': 'snap-456'}]
    }
    
    cleaner = EBSCleaner(mock_session, config, {})
    cleaner.cleanup('us-east-1')
    
    ec2_client.delete_volume.assert_not_called()
    ec2_client.delete_snapshot.assert_not_called()
