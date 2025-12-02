import logging
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete, SLEEP_SHORT
import time

class ELBCleaner(ResourceCleaner):
    def cleanup(self, region=None):
        self.delete_load_balancers_v2(region)
        self.delete_target_groups(region)
        self.delete_load_balancers_v1(region)

    def delete_load_balancers_v2(self, region):
        elbv2 = self.session.client('elbv2', region_name=region)
        try:
            lbs = elbv2.describe_load_balancers().get('LoadBalancers', [])
            for lb in lbs:
                lb_arn = lb['LoadBalancerArn']
                lb_name = lb['LoadBalancerName']
                logging.info(f"[{region}] Deleting ELBv2 {lb_name}")
                if not self.config.dry_run:
                    # Disable deletion protection if enabled
                    try:
                        attrs = elbv2.describe_load_balancer_attributes(LoadBalancerArn=lb_arn)
                        for attr in attrs.get('Attributes', []):
                            if attr['Key'] == 'deletion_protection.enabled' and attr['Value'] == 'true':
                                elbv2.modify_load_balancer_attributes(
                                    LoadBalancerArn=lb_arn,
                                    Attributes=[{'Key': 'deletion_protection.enabled', 'Value': 'false'}]
                                )
                    except ClientError:
                        pass

                    success = retry_delete(
                        lambda: elbv2.delete_load_balancer(LoadBalancerArn=lb_arn),
                        f"Delete ELBv2 {lb_name}"
                    )
                    self._record_result('Load Balancers (v2)', lb_name, success)
                    # Wait a bit for deletion to propagate before deleting TGs
                    time.sleep(SLEEP_SHORT) 
                else:
                    logging.info(f"[Dry-Run] Would delete ELBv2 {lb_name}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting ELBv2: {e}")

    def delete_target_groups(self, region):
        elbv2 = self.session.client('elbv2', region_name=region)
        try:
            tgs = elbv2.describe_target_groups().get('TargetGroups', [])
            for tg in tgs:
                tg_arn = tg['TargetGroupArn']
                tg_name = tg['TargetGroupName']
                logging.info(f"[{region}] Deleting Target Group {tg_name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: elbv2.delete_target_group(TargetGroupArn=tg_arn),
                        f"Delete Target Group {tg_name}"
                    )
                    self._record_result('Target Groups', tg_name, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Target Group {tg_name}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Target Groups: {e}")

    def delete_load_balancers_v1(self, region):
        elb = self.session.client('elb', region_name=region)
        try:
            lbs = elb.describe_load_balancers().get('LoadBalancerDescriptions', [])
            for lb in lbs:
                lb_name = lb['LoadBalancerName']
                logging.info(f"[{region}] Deleting CLB {lb_name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: elb.delete_load_balancer(LoadBalancerName=lb_name),
                        f"Delete CLB {lb_name}"
                    )
                    self._record_result('Classic Load Balancers', lb_name, success)
                else:
                    logging.info(f"[Dry-Run] Would delete CLB {lb_name}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting CLBs: {e}")
