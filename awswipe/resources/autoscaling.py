import logging
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete

class ASGCleaner(ResourceCleaner):
    @property
    def prerequisites(self):
        return ['ec2']

    def cleanup(self, region=None):
        self.delete_asgs(region)
        self.delete_launch_configurations(region)
        self.delete_launch_templates(region)

    def delete_asgs(self, region):
        asg_client = self.session.client('autoscaling', region_name=region)
        try:
            paginator = asg_client.get_paginator('describe_auto_scaling_groups')
            asgs = []
            for page in paginator.paginate():
                asgs.extend(page['AutoScalingGroups'])
            
            for asg in asgs:
                asg_name = asg['AutoScalingGroupName']
                logging.info(f"[{region}] Deleting ASG {asg_name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: asg_client.delete_auto_scaling_group(AutoScalingGroupName=asg_name, ForceDelete=True),
                        f"Delete ASG {asg_name}"
                    )
                    self._record_result('Auto Scaling Groups', asg_name, success)
                else:
                    logging.info(f"[Dry-Run] Would delete ASG {asg_name}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting ASGs: {e}")

    def delete_launch_configurations(self, region):
        asg_client = self.session.client('autoscaling', region_name=region)
        try:
            lcs = asg_client.describe_launch_configurations().get('LaunchConfigurations', [])
            for lc in lcs:
                lc_name = lc['LaunchConfigurationName']
                logging.info(f"[{region}] Deleting Launch Configuration {lc_name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: asg_client.delete_launch_configuration(LaunchConfigurationName=lc_name),
                        f"Delete Launch Config {lc_name}"
                    )
                    self._record_result('Launch Configurations', lc_name, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Launch Config {lc_name}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Launch Configurations: {e}")

    def delete_launch_templates(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            lts = ec2.describe_launch_templates().get('LaunchTemplates', [])
            for lt in lts:
                lt_name = lt['LaunchTemplateName']
                lt_id = lt['LaunchTemplateId']
                logging.info(f"[{region}] Deleting Launch Template {lt_name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: ec2.delete_launch_template(LaunchTemplateId=lt_id),
                        f"Delete Launch Template {lt_name}"
                    )
                    self._record_result('Launch Templates', lt_name, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Launch Template {lt_name}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Launch Templates: {e}")
