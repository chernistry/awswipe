import logging
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete

class EC2Cleaner(ResourceCleaner):
    @property
    def prerequisites(self):
        return []

    def cleanup(self, region=None):
        self.terminate_instances(region)

    def terminate_instances(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            # Filter for instances that are not already terminated
            instances = ec2.describe_instances(
                Filters=[{'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']}]
            )
            instance_ids = []
            for reservation in instances.get('Reservations', []):
                for instance in reservation.get('Instances', []):
                    instance_ids.append(instance['InstanceId'])
            
            if not instance_ids:
                return

            logging.info(f"[{region}] Terminating EC2 instances: {instance_ids}")
            
            if not self.config.dry_run:
                # Check for termination protection
                for i_id in instance_ids:
                    try:
                        attr = ec2.describe_instance_attribute(InstanceId=i_id, Attribute='disableApiTermination')
                        if attr['DisableApiTermination']['Value']:
                            logging.info(f"[{region}] Disabling termination protection for {i_id}")
                            ec2.modify_instance_attribute(InstanceId=i_id, DisableApiTermination={'Value': False})
                    except ClientError as e:
                        logging.warning(f"[{region}] Failed to check/disable termination protection for {i_id}: {e}")

                success = retry_delete(
                    lambda: ec2.terminate_instances(InstanceIds=instance_ids),
                    f"Terminate instances {instance_ids}"
                )
                # We record result for each instance individually for better reporting
                for i_id in instance_ids:
                    self._record_result('EC2 Instances', i_id, success)
            else:
                for i_id in instance_ids:
                    logging.info(f"[Dry-Run] Would terminate EC2 instance {i_id}")

        except ClientError as e:
            logging.error(f"[{region}] Error terminating EC2 instances: {e}")
