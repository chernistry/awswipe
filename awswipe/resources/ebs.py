import logging
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete

class EBSCleaner(ResourceCleaner):
    def cleanup(self, region=None):
        self.delete_volumes(region)
        self.delete_snapshots(region)

    def delete_volumes(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            # Only delete available (unattached) volumes
            volumes = ec2.describe_volumes(
                Filters=[{'Name': 'status', 'Values': ['available']}]
            ).get('Volumes', [])
            
            for vol in volumes:
                v_id = vol['VolumeId']
                logging.info(f"[{region}] Deleting EBS volume {v_id}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: ec2.delete_volume(VolumeId=v_id),
                        f"Delete EBS volume {v_id}"
                    )
                    self._record_result('EBS Volumes', v_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete EBS volume {v_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting EBS volumes: {e}")

    def delete_snapshots(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            # Only delete snapshots owned by self
            snapshots = ec2.describe_snapshots(OwnerIds=['self']).get('Snapshots', [])
            
            for snap in snapshots:
                s_id = snap['SnapshotId']
                logging.info(f"[{region}] Deleting EBS snapshot {s_id}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: ec2.delete_snapshot(SnapshotId=s_id),
                        f"Delete EBS snapshot {s_id}"
                    )
                    self._record_result('EBS Snapshots', s_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete EBS snapshot {s_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting EBS snapshots: {e}")
