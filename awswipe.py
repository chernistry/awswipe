#!/usr/bin/env python3
import argparse
import logging
import time
import random
import functools
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import boto3
from botocore.exceptions import ClientError, WaiterError

SLEEP_SHORT = 2
SLEEP_MEDIUM = 5
SLEEP_LONG = 10
SLEEP_EXTRA_LONG = 30

# Initial basicConfig (will be overridden by -v options later)
logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

def retry_delete(operation, description, max_attempts=5, base_delay=SLEEP_MEDIUM):
    attempts = 0
    while attempts < max_attempts:
        try:
            operation()
            logging.info('%s succeeded', description)
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code in ['DependencyViolation', 'InvalidIPAddress.InUse',
                              'Throttling', 'ThrottlingException', 'RequestLimitExceeded']:
                attempts += 1
                delay = base_delay * (2 ** (attempts - 1)) + random.uniform(0, 1)
                logging.warning('%s failed with %s; attempt %d/%d. Retrying in %.2f seconds...',
                                description, error_code, attempts, max_attempts, delay)
                time.sleep(delay)
            else:
                logging.error('%s failed: %s', description, e)
                return False
    logging.error('%s failed after %s attempts.', description, max_attempts)
    return False

def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        logging.info(f"{func.__name__} took {elapsed:.2f} seconds")
        return result
    return wrapper

class SuperAWSResourceCleaner:
    def __init__(self):
        self.session = boto3.session.Session()
        self.report = {}
        try:
            sts = self.session.client('sts')
            self.account_id = sts.get_caller_identity()['Account']
        except ClientError as e:
            logging.error("Error retrieving account ID: %s", e)
            self.account_id = None

    def _record_result(self, resource_type, resource_id, success, message=''):
        if resource_type not in self.report:
            self.report[resource_type] = {'deleted': [], 'failed': []}
        if success:
            self.report[resource_type]['deleted'].append(resource_id)
        else:
            msg = f"{resource_id} ({message})" if message else resource_id
            self.report[resource_type]['failed'].append(msg)

    def print_report(self):
        print('\n=== AWS Super Cleanup Report ===')
        for resource_type, results in self.report.items():
            print(f"\nResource: {resource_type}")
            print('  Deleted:')
            if results['deleted']:
                for item in results['deleted']:
                    print(f"    - {item}")
            else:
                print('    None')
            print('  Failed:')
            if results['failed']:
                for item in results['failed']:
                    print(f"    - {item}")
            else:
                print('    None')

    @lru_cache(maxsize=1)
    def get_all_regions(self):
        ec2 = self.session.client('ec2')
        try:
            regions_info = ec2.describe_regions()['Regions']
            regions = [region['RegionName'] for region in regions_info]
            logging.info('Retrieved regions: %s', regions)
            return regions
        except ClientError as e:
            logging.error('Failed to get regions: %s', e)
            return []

    @timed
    def delete_s3_buckets_global(self):
        s3 = self.session.client('s3')
        try:
            buckets = s3.list_buckets().get('Buckets', [])
            for bucket in buckets:
                b_name = bucket['Name']
                logging.info('Processing S3 bucket: %s', b_name)
                self._empty_s3_bucket(s3, b_name)
                success = retry_delete(lambda: s3.delete_bucket(Bucket=b_name),
                                       f"Delete S3 Bucket {b_name}")
                self._record_result('S3 Buckets', b_name, success,
                                    '' if success else 'Cannot delete bucket; may require MFA')
        except ClientError as e:
            logging.error('Error listing S3 buckets: %s', e)

    def _empty_s3_bucket(self, s3, bucket_name):
        logging.info('Emptying bucket: %s', bucket_name)
        try:
            mp_resp = s3.list_multipart_uploads(Bucket=bucket_name)
            uploads = mp_resp.get('Uploads', [])
            for upload in uploads:
                key = upload['Key']
                upload_id = upload['UploadId']
                retry_delete(lambda: s3.abort_multipart_upload(Bucket=bucket_name, Key=key, UploadId=upload_id),
                             f"Abort MPU for {key}")
        except ClientError:
            pass
        paginator = s3.get_paginator('list_object_versions')
        try:
            for page in paginator.paginate(Bucket=bucket_name):
                objs = []
                for v in page.get('Versions', []):
                    objs.append({'Key': v['Key'], 'VersionId': v['VersionId']})
                for d in page.get('DeleteMarkers', []):
                    objs.append({'Key': d['Key'], 'VersionId': d['VersionId']})
                while objs:
                    batch = objs[:1000]
                    del_objs = {'Objects': batch, 'Quiet': True}
                    success = retry_delete(lambda: s3.delete_objects(Bucket=bucket_name, Delete=del_objs),
                                           f"Deleting objects in {bucket_name}")
                    objs = objs[1000:]
                    if not success:
                        break
        except ClientError as e:
            logging.warning('Could not fully list/delete objects in %s: %s', bucket_name, e)

    @timed
    def cleanup_region(self, region):
        logging.info(f"=== Cleaning region {region} ===")
        try:
            ecs_client = self.session.client('ecs', region_name=region)
            ecr_client = self.session.client('ecr', region_name=region)
            efs_client = self.session.client('efs', region_name=region)
            apig_client = self.session.client('apigateway', region_name=region)
            apigv2_client = self.session.client('apigatewayv2', region_name=region)
            sqs_client = self.session.client('sqs', region_name=region)
            sns_client = self.session.client('sns', region_name=region)
            sfn_client = self.session.client('stepfunctions', region_name=region)
            asg_client = self.session.client('autoscaling', region_name=region)
            ec2_client = self.session.client('ec2', region_name=region)
            elbv2_client = self.session.client('elbv2', region_name=region)
            elbv1_client = self.session.client('elb', region_name=region)
            rds_client = self.session.client('rds', region_name=region)
            lambda_client = self.session.client('lambda', region_name=region)
            cf_client = self.session.client('cloudformation', region_name=region)
            sm_client = self.session.client('secretsmanager', region_name=region)
            ssm_client = self.session.client('ssm', region_name=region)
            logs_client = self.session.client('logs', region_name=region)
            elasticache_client = self.session.client('elasticache', region_name=region)
            redshift_client = self.session.client('redshift', region_name=region)

            self.delete_ecs_clusters_services(ecs_client, region)
            self.delete_ecr_repos(ecr_client, region)
            self.delete_efs(efs_client, region)
            self.delete_api_gateways(apig_client, apigv2_client, region)
            self.delete_sqs_queues(sqs_client, region)
            self.delete_sns_topics(sns_client, region)
            self.delete_stepfunctions(sfn_client, region)
            self.delete_auto_scaling_groups(asg_client, region)
            self.detach_instance_security_groups(ec2_client, region)
            self.detach_instance_network_interfaces(ec2_client, region)
            self.delete_elastic_ips(ec2_client, region)
            self.terminate_ec2_instances(ec2_client, region)
            time.sleep(SLEEP_MEDIUM)
            self.delete_load_balancers(elbv2_client, region)
            self.delete_classic_load_balancers(elbv1_client, region)
            self.delete_all_vpcs(ec2_client, region)
            self.delete_all_security_groups(ec2_client, region)
            self.delete_rds_instances(rds_client, region)
            self.delete_dhcp_options(ec2_client, region)
            self.delete_managed_prefix_lists(ec2_client, region)
            self.delete_network_acls(ec2_client, region)
            self.delete_lambda_functions(lambda_client, region)
            self.delete_cloudformation_stacks(cf_client, region)
            self.delete_secrets(sm_client, region)
            self.delete_ssm_parameters(ssm_client, region)
            self.delete_log_groups(logs_client, region)
            self.delete_elasticache_clusters(elasticache_client, region)
            self.delete_redshift_clusters(redshift_client, region)
            self.delete_ebs_volumes_and_snapshots(ec2_client, region)
        except Exception as e:
            logging.error(f"Fatal error in region {region}: {e}")

    def delete_ecs_clusters_services(self, ecs, region):
        try:
            clusters_resp = ecs.list_clusters()
            cluster_arns = clusters_resp.get('clusterArns', [])
            for cluster_arn in cluster_arns:
                services_resp = ecs.list_services(cluster=cluster_arn)
                service_arns = services_resp.get('serviceArns', [])
                for svc_arn in service_arns:
                    logging.info(f"[{region}] Deleting ECS service {svc_arn}")
                    success = retry_delete(lambda: ecs.delete_service(cluster=cluster_arn, service=svc_arn, force=True),
                                           f"Delete ECS service {svc_arn}")
                    self._record_result('ECS Services', svc_arn, success)
                logging.info(f"[{region}] Deleting ECS cluster {cluster_arn}")
                success = retry_delete(lambda: ecs.delete_cluster(cluster=cluster_arn),
                                       f"Delete ECS cluster {cluster_arn}")
                self._record_result('ECS Clusters', cluster_arn, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing/deleting ECS clusters/services: {e}")

    def delete_ecr_repos(self, ecr, region):
        try:
            repos_resp = ecr.describe_repositories()
            repos = repos_resp.get('repositories', [])
            for repo in repos:
                repo_name = repo['repositoryName']
                logging.info(f"[{region}] Deleting ECR repo {repo_name}")
                success = retry_delete(lambda: ecr.delete_repository(repositoryName=repo_name, force=True),
                                       f"Delete ECR repository {repo_name}")
                self._record_result('ECR Repos', repo_name, success)
        except ClientError as e:
            if 'RepositoryNotFoundException' in str(e):
                logging.info(f"[{region}] No ECR repositories found.")
            else:
                logging.error(f"[{region}] Error describing ECR repositories: {e}")

    def delete_efs(self, efs, region):
        try:
            resp = efs.describe_file_systems()
            file_systems = resp.get('FileSystems', [])
            for fs in file_systems:
                fs_id = fs['FileSystemId']
                mt_resp = efs.describe_mount_targets(FileSystemId=fs_id)
                for mt in mt_resp.get('MountTargets', []):
                    mt_id = mt['MountTargetId']
                    logging.info(f"[{region}] Deleting EFS mount target {mt_id}")
                    success = retry_delete(lambda: efs.delete_mount_target(MountTargetId=mt_id),
                                           f"Delete EFS mount target {mt_id}")
                    self._record_result('EFS Mount Targets', mt_id, success)
                logging.info(f"[{region}] Deleting EFS file system {fs_id}")
                success = retry_delete(lambda: efs.delete_file_system(FileSystemId=fs_id),
                                       f"Delete EFS file system {fs_id}")
                self._record_result('EFS File Systems', fs_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing/deleting EFS: {e}")

    def delete_api_gateways(self, apig, apigv2, region):
        try:
            apis = apig.get_rest_apis().get('items', [])
            for api in apis:
                api_id = api['id']
                logging.info(f"[{region}] Deleting API Gateway (REST) {api_id}")
                success = retry_delete(lambda: apig.delete_rest_api(restApiId=api_id),
                                       f"Delete API Gateway (REST) {api_id}")
                self._record_result('API Gateway (REST)', api_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing/deleting REST APIs: {e}")
        try:
            v2_apis = apigv2.get_apis().get('Items', [])
            for v2api in v2_apis:
                api_id = v2api['ApiId']
                logging.info(f"[{region}] Deleting API Gateway (HTTP/WebSocket) {api_id}")
                success = retry_delete(lambda: apigv2.delete_api(ApiId=api_id),
                                       f"Delete API Gateway (HTTP/WebSocket) {api_id}")
                self._record_result('API Gateway (HTTPv2)', api_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing/deleting HTTP/WebSocket APIs: {e}")

    def delete_sqs_queues(self, sqs, region):
        try:
            resp = sqs.list_queues()
            queue_urls = resp.get('QueueUrls', [])
            for q_url in queue_urls:
                logging.info(f"[{region}] Deleting SQS queue {q_url}")
                success = retry_delete(lambda: sqs.delete_queue(QueueUrl=q_url),
                                       f"Delete SQS queue {q_url}")
                self._record_result('SQS Queues', q_url, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing/deleting SQS queues: {e}")

    def delete_sns_topics(self, sns, region):
        try:
            resp = sns.list_topics()
            topics = resp.get('Topics', [])
            for t in topics:
                topic_arn = t['TopicArn']
                subs_resp = sns.list_subscriptions_by_topic(TopicArn=topic_arn)
                subs = subs_resp.get('Subscriptions', [])
                for s in subs:
                    sub_arn = s['SubscriptionArn']
                    if sub_arn != 'PendingConfirmation':
                        logging.info(f"[{region}] Unsubscribing {sub_arn}")
                        success = retry_delete(lambda: sns.unsubscribe(SubscriptionArn=sub_arn),
                                               f"Unsubscribe {sub_arn}")
                        self._record_result('SNS Subscriptions', sub_arn, success)
                logging.info(f"[{region}] Deleting SNS topic {topic_arn}")
                success = retry_delete(lambda: sns.delete_topic(TopicArn=topic_arn),
                                       f"Delete SNS topic {topic_arn}")
                self._record_result('SNS Topics', topic_arn, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing/deleting SNS topics: {e}")

    def delete_stepfunctions(self, sfn, region):
        try:
            resp = sfn.list_state_machines()
            sms = resp.get('stateMachines', [])
            for sm in sms:
                sm_arn = sm['stateMachineArn']
                logging.info(f"[{region}] Deleting StepFunction machine {sm_arn}")
                success = retry_delete(lambda: sfn.delete_state_machine(stateMachineArn=sm_arn),
                                       f"Delete StepFunction {sm_arn}")
                self._record_result('Step Functions', sm_arn, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing/deleting StepFunctions: {e}")

    def delete_auto_scaling_groups(self, asg, region):
        try:
            groups = asg.describe_auto_scaling_groups().get('AutoScalingGroups', [])
            for g in groups:
                asg_name = g['AutoScalingGroupName']
                logging.info(f"[{region}] Deleting ASG {asg_name}")
                success = retry_delete(lambda: asg.delete_auto_scaling_group(AutoScalingGroupName=asg_name,
                                                                             ForceDelete=True),
                                       f"Delete AutoScaling Group {asg_name}")
                self._record_result('Auto Scaling Groups', asg_name, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing ASGs: {e}")

    def detach_instance_security_groups(self, ec2, region):
        try:
            resp = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}])
            for r in resp.get('Reservations', []):
                for inst in r.get('Instances', []):
                    inst_id = inst['InstanceId']
                    vpc_id = inst.get('VpcId')
                    if not vpc_id:
                        continue
                    sg_resp = ec2.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]},
                                                                    {'Name': 'group-name', 'Values': ['default']}])
                    default_sgs = sg_resp.get('SecurityGroups', [])
                    if not default_sgs:
                        continue
                    default_sg = default_sgs[0]['GroupId']
                    logging.info(f"[{region}] Forcing {inst_id} SG to default {default_sg}")
                    try:
                        ec2.modify_instance_attribute(InstanceId=inst_id, Groups=[default_sg])
                    except ClientError as e:
                        logging.error(f"Error forcing default SG on {inst_id}: {e}")
                    time.sleep(SLEEP_SHORT)
        except ClientError as e:
            logging.error(f"[{region}] Error detaching instance security groups: {e}")

    def detach_instance_network_interfaces(self, ec2, region):
        try:
            resp = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}])
            for r in resp.get('Reservations', []):
                for inst in r.get('Instances', []):
                    inst_id = inst['InstanceId']
                    for ni in inst.get('NetworkInterfaces', []):
                        if ni.get('Status', '').lower() == 'attaching':
                            continue
                        attachment = ni.get('Attachment', {})
                        if attachment and attachment.get('DeviceIndex', 0) != 0:
                            attach_id = attachment['AttachmentId']
                            ni_id = ni['NetworkInterfaceId']
                            logging.info(f"[{region}] Detaching NIC {ni_id} from {inst_id}")
                            try:
                                ec2.detach_network_interface(AttachmentId=attach_id, Force=True)
                            except ClientError as e:
                                logging.error(f"Error detaching NIC {ni_id}: {e}")
                            time.sleep(SLEEP_SHORT)
        except ClientError as e:
            logging.error(f"[{region}] Error detaching NICs: {e}")

    def delete_elastic_ips(self, ec2, region):
        try:
            addresses = ec2.describe_addresses().get('Addresses', [])
            for addr in addresses:
                alloc_id = addr.get('AllocationId')
                public_ip = addr.get('PublicIp')
                if not alloc_id:
                    continue
                logging.info(f"[{region}] Releasing EIP {public_ip}")
                success = retry_delete(lambda: ec2.release_address(AllocationId=alloc_id),
                                       f"Release EIP {public_ip}")
                self._record_result('Elastic IPs', public_ip, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing EIPs: {e}")

    def terminate_ec2_instances(self, ec2, region):
        try:
            resp = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['running', 'stopped']}])
            inst_ids = []
            for r in resp.get('Reservations', []):
                for inst in r.get('Instances', []):
                    inst_ids.append(inst['InstanceId'])
            if not inst_ids:
                logging.info(f"[{region}] No EC2 instances to terminate.")
                return
            logging.info(f"[{region}] Terminating instances {inst_ids}")
            ec2.terminate_instances(InstanceIds=inst_ids)
            for i_id in inst_ids:
                self._record_result('EC2 Instances', i_id, True)
            waiter = ec2.get_waiter('instance_terminated')
            try:
                waiter.wait(InstanceIds=inst_ids, WaiterConfig={'Delay': 5, 'MaxAttempts': 60})
                logging.info(f"[{region}] Instances are fully terminated: {inst_ids}")
            except WaiterError as e:
                logging.warning(f"[{region}] Waiter for termination timed out: {e}")
        except ClientError as e:
            logging.error(f"[{region}] Error terminating EC2 instances: {e}")

    def delete_load_balancers(self, elbv2, region):
        try:
            lbs = elbv2.describe_load_balancers().get('LoadBalancers', [])
            for lb in lbs:
                lb_arn = lb['LoadBalancerArn']
                lb_name = lb['LoadBalancerName']
                logging.info(f"[{region}] Deleting ALB/NLB {lb_name}")
                success = retry_delete(lambda: elbv2.delete_load_balancer(LoadBalancerArn=lb_arn),
                                       f"Delete LB {lb_name}")
                self._record_result('Load Balancers (ALB/NLB)', lb_name, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing ELBv2: {e}")

    def delete_classic_load_balancers(self, elbv1, region):
        try:
            lbs = elbv1.describe_load_balancers().get('LoadBalancerDescriptions', [])
            for lb in lbs:
                lb_name = lb['LoadBalancerName']
                logging.info(f"[{region}] Deleting Classic ELB {lb_name}")
                success = retry_delete(lambda: elbv1.delete_load_balancer(LoadBalancerName=lb_name),
                                       f"Delete classic ELB {lb_name}")
                self._record_result('Classic Load Balancers', lb_name, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing classic ELBs: {e}")

    def delete_all_vpcs(self, ec2, region):
        try:
            vpcs = ec2.describe_vpcs().get('Vpcs', [])
            for v in vpcs:
                vpc_id = v['VpcId']
                logging.info(f"[{region}] Deleting sub-resources for VPC {vpc_id}")
                self.delete_vpc_endpoints(ec2, vpc_id, region)
                self.delete_vpn_gateways(ec2, vpc_id, region)
                self.delete_vpc_peering_connections(ec2, vpc_id, region)
                self.delete_network_interfaces(ec2, vpc_id, region)
                self.delete_nat_gateways(ec2, vpc_id, region)
                self.delete_internet_gateways(ec2, vpc_id, region)
                self.delete_route_tables(ec2, vpc_id, region)
                self.delete_vpc_security_groups(ec2, vpc_id, region)
                self.delete_subnets(ec2, vpc_id, region)
                logging.info(f"[{region}] Deleting VPC {vpc_id}")
                success = retry_delete(lambda: ec2.delete_vpc(VpcId=vpc_id),
                                       f"Delete VPC {vpc_id}")
                self._record_result('VPCs', vpc_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing VPCs: {e}")

    def delete_vpc_endpoints(self, ec2, vpc_id, region):
        try:
            eps = ec2.describe_vpc_endpoints(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]).get('VpcEndpoints', [])
            for ep in eps:
                ep_id = ep['VpcEndpointId']
                logging.info(f"[{region}] Deleting VPC endpoint {ep_id}")
                success = retry_delete(lambda: ec2.delete_vpc_endpoints(VpcEndpointIds=[ep_id]),
                                       f"Delete VPC endpoint {ep_id}")
                self._record_result('VPC Endpoints', ep_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing VPC endpoints: {e}")

    def delete_vpn_gateways(self, ec2, vpc_id, region):
        try:
            vgws = ec2.describe_vpn_gateways(Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]).get('VpnGateways', [])
            for vgw in vgws:
                vgw_id = vgw['VpnGatewayId']
                logging.info(f"[{region}] Detaching & deleting VPN GW {vgw_id}")
                for att in vgw.get('VpcAttachments', []):
                    retry_delete(lambda: ec2.detach_vpn_gateway(VpnGatewayId=vgw_id, VpcId=vpc_id),
                                 f"Detach VPN GW {vgw_id}")
                success = retry_delete(lambda: ec2.delete_vpn_gateway(VpnGatewayId=vgw_id),
                                       f"Delete VPN GW {vgw_id}")
                self._record_result('VPN Gateways', vgw_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing VPN GWs: {e}")

    def delete_vpc_peering_connections(self, ec2, vpc_id, region):
        try:
            req = ec2.describe_vpc_peering_connections(Filters=[{'Name': 'requester-vpc-info.vpc-id', 'Values': [vpc_id]}]).get('VpcPeeringConnections', [])
            acc = ec2.describe_vpc_peering_connections(Filters=[{'Name': 'accepter-vpc-info.vpc-id', 'Values': [vpc_id]}]).get('VpcPeeringConnections', [])
            for peering in req + acc:
                pcx_id = peering['VpcPeeringConnectionId']
                logging.info(f"[{region}] Deleting VPC peering {pcx_id}")
                success = retry_delete(lambda: ec2.delete_vpc_peering_connection(VpcPeeringConnectionId=pcx_id),
                                       f"Delete VPC peering {pcx_id}")
                self._record_result('VPC Peering Connections', pcx_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing VPC peering: {e}")

    def delete_network_interfaces(self, ec2, vpc_id, region):
        try:
            nis = ec2.describe_network_interfaces(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]).get('NetworkInterfaces', [])
            for ni in nis:
                ni_id = ni['NetworkInterfaceId']
                logging.info(f"[{region}] Deleting network interface {ni_id}")
                success = retry_delete(lambda: ec2.delete_network_interface(NetworkInterfaceId=ni_id),
                                       f"Delete NIC {ni_id}")
                self._record_result('Network Interfaces', ni_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing network interfaces: {e}")

    def delete_nat_gateways(self, ec2, vpc_id, region):
        try:
            ngws = ec2.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]).get('NatGateways', [])
            for ngw in ngws:
                ngw_id = ngw['NatGatewayId']
                logging.info(f"[{region}] Deleting NAT GW {ngw_id}")
                success = retry_delete(lambda: ec2.delete_nat_gateway(NatGatewayId=ngw_id),
                                       f"Delete NAT GW {ngw_id}")
                self._record_result('NAT Gateways', ngw_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing NAT GWs: {e}")

    def delete_internet_gateways(self, ec2, vpc_id, region):
        try:
            igws = ec2.describe_internet_gateways(Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}]).get('InternetGateways', [])
            for igw in igws:
                igw_id = igw['InternetGatewayId']
                logging.info(f"[{region}] Detaching & deleting IGW {igw_id}")
                retry_delete(lambda: ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id),
                             f"Detach IGW {igw_id}")
                success = retry_delete(lambda: ec2.delete_internet_gateway(InternetGatewayId=igw_id),
                                       f"Delete IGW {igw_id}")
                self._record_result('Internet Gateways', igw_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing IGWs: {e}")

    def delete_route_tables(self, ec2, vpc_id, region):
        try:
            rts = ec2.describe_route_tables(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]).get('RouteTables', [])
            for rt in rts:
                rt_id = rt['RouteTableId']
                if any(a.get('Main', False) for a in rt.get('Associations', [])):
                    logging.info(f"[{region}] Skipping main route table {rt_id}")
                    continue
                logging.info(f"[{region}] Deleting route table {rt_id}")
                success = retry_delete(lambda: ec2.delete_route_table(RouteTableId=rt_id),
                                       f"Delete route table {rt_id}")
                self._record_result('Route Tables', rt_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing route tables: {e}")

    def delete_vpc_security_groups(self, ec2, vpc_id, region):
        try:
            sgs = ec2.describe_security_groups(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]).get('SecurityGroups', [])
            for sg in sgs:
                if sg['GroupName'] == 'default':
                    continue
                sg_id = sg['GroupId']
                logging.info(f"[{region}] Deleting SG {sg_id}")
                success = retry_delete(lambda: ec2.delete_security_group(GroupId=sg_id),
                                       f"Delete SG {sg_id}")
                self._record_result('Security Groups', sg_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing SGs in VPC {vpc_id}: {e}")

    def delete_subnets(self, ec2, vpc_id, region):
        try:
            subs = ec2.describe_subnets(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]).get('Subnets', [])
            for s in subs:
                sn_id = s['SubnetId']
                logging.info(f"[{region}] Deleting subnet {sn_id}")
                success = retry_delete(lambda: ec2.delete_subnet(SubnetId=sn_id),
                                       f"Delete subnet {sn_id}")
                self._record_result('Subnets', sn_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing subnets: {e}")

    def delete_all_security_groups(self, ec2, region):
        try:
            sgs = ec2.describe_security_groups().get('SecurityGroups', [])
            for sg in sgs:
                if sg['GroupName'] == 'default':
                    continue
                sg_id = sg['GroupId']
                logging.info(f"[{region}] Deleting leftover SG {sg_id}")
                success = retry_delete(lambda: ec2.delete_security_group(GroupId=sg_id),
                                       f"Delete leftover SG {sg_id}")
                self._record_result('Security Groups', sg_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing leftover SGs: {e}")

    def delete_rds_instances(self, rds, region):
        try:
            dbs = rds.describe_db_instances().get('DBInstances', [])
            for db in dbs:
                db_id = db['DBInstanceIdentifier']
                logging.info(f"[{region}] Deleting RDS {db_id}")
                success = True
                try:
                    rds.delete_db_instance(DBInstanceIdentifier=db_id, SkipFinalSnapshot=True)
                except ClientError as e:
                    success = False
                    logging.error(f"[{region}] Error deleting RDS {db_id}: {e}")
                self._record_result('RDS Instances', db_id, success)
                time.sleep(SLEEP_LONG)
        except ClientError as e:
            logging.error(f"[{region}] Error describing RDS: {e}")

    def delete_dhcp_options(self, ec2, region):
        try:
            resp = ec2.describe_dhcp_options().get('DhcpOptions', [])
            for dopt in resp:
                dopt_id = dopt['DhcpOptionsId']
                if dopt_id == 'default':
                    continue
                logging.info(f"[{region}] Deleting DHCP options {dopt_id}")
                success = retry_delete(lambda: ec2.delete_dhcp_options(DhcpOptionsId=dopt_id),
                                       f"Delete DHCP options {dopt_id}")
                self._record_result('DHCP Options', dopt_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing DHCP options: {e}")

    def delete_managed_prefix_lists(self, ec2, region):
        sts = self.session.client('sts')
        try:
            acct_id = sts.get_caller_identity()['Account']
        except ClientError:
            acct_id = None
        try:
            pls = ec2.describe_managed_prefix_lists().get('PrefixLists', [])
            for pl in pls:
                pl_id = pl['PrefixListId']
                owner_id = pl['OwnerId']
                if acct_id and owner_id != acct_id:
                    logging.info(f"[{region}] Skipping AWS-managed prefix list {pl_id}")
                    continue
                logging.info(f"[{region}] Deleting prefix list {pl_id}")
                success = retry_delete(lambda: ec2.delete_managed_prefix_list(PrefixListId=pl_id),
                                       f"Delete prefix list {pl_id}")
                self._record_result('Managed Prefix Lists', pl_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing prefix lists: {e}")

    def delete_network_acls(self, ec2, region):
        try:
            acls = ec2.describe_network_acls().get('NetworkAcls', [])
            for acl in acls:
                if acl.get('IsDefault'):
                    continue
                acl_id = acl['NetworkAclId']
                logging.info(f"[{region}] Deleting network ACL {acl_id}")
                success = retry_delete(lambda: ec2.delete_network_acl(NetworkAclId=acl_id),
                                       f"Delete network ACL {acl_id}")
                self._record_result('Network ACLs', acl_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing NACLs: {e}")

    def delete_lambda_functions(self, lamb, region):
        try:
            paginator = lamb.get_paginator('list_functions')
            for page in paginator.paginate():
                fns = page.get('Functions', [])
                for fn in fns:
                    fn_name = fn['FunctionName']
                    try:
                        mappings = lamb.list_event_source_mappings(FunctionName=fn_name).get('EventSourceMappings', [])
                        for mapping in mappings:
                            mapping_uuid = mapping['UUID']
                            logging.info(f"[{region}] Deleting event source mapping {mapping_uuid} for lambda {fn_name}")
                            success = retry_delete(lambda: lamb.delete_event_source_mapping(UUID=mapping_uuid),
                                                   f"Delete event source mapping {mapping_uuid}")
                            self._record_result('Lambda Event Source Mappings', mapping_uuid, success)
                    except ClientError as e:
                        logging.error(f"[{region}] Error listing event source mappings for {fn_name}: {e}")
                    logging.info(f"[{region}] Deleting lambda function {fn_name}")
                    success = retry_delete(lambda: lamb.delete_function(FunctionName=fn_name),
                                           f"Delete lambda {fn_name}")
                    self._record_result('Lambda Functions', fn_name, success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing lambda functions: {e}")

    def delete_cloudformation_stacks(self, cf, region):
        try:
            stacks_resp = cf.list_stacks(StackStatusFilter=['CREATE_COMPLETE', 'UPDATE_COMPLETE'])
            stacks = stacks_resp.get('StackSummaries', [])
            for st in stacks:
                st_name = st['StackName']
                logging.info(f"[{region}] Deleting CF stack {st_name}")
                success = True
                try:
                    cf.delete_stack(StackName=st_name)
                except ClientError as e:
                    logging.error(f"Error deleting CF stack {st_name}: {e}")
                    success = False
                self._record_result('CloudFormation Stacks', st_name, success)
                time.sleep(SLEEP_LONG)
        except ClientError as e:
            logging.error(f"[{region}] Error listing CF stacks: {e}")

    def delete_secrets(self, sm, region):
        try:
            paginator = sm.get_paginator('list_secrets')
            for page in paginator.paginate():
                secrets = page.get('SecretList', [])
                for s in secrets:
                    s_name = s['Name']
                    logging.info(f"[{region}] Deleting secret {s_name}")
                    success = True
                    try:
                        sm.delete_secret(SecretId=s_name, ForceDeleteWithoutRecovery=True)
                    except ClientError as e:
                        logging.error(f"Error deleting secret {s_name}: {e}")
                        success = False
                    self._record_result('Secrets Manager Secrets', s_name, success)
                    time.sleep(SLEEP_SHORT)
        except ClientError as e:
            logging.error(f"[{region}] Error listing secrets: {e}")

    def delete_ssm_parameters(self, ssm, region):
        try:
            paginator = ssm.get_paginator('describe_parameters')
            param_names = []
            for page in paginator.paginate():
                for param in page.get('Parameters', []):
                    param_names.append(param['Name'])
            while param_names:
                batch = param_names[:10]
                del_call = lambda: ssm.delete_parameters(Names=batch)
                success = retry_delete(del_call, f"Delete SSM parameters {batch}")
                for name in batch:
                    self._record_result('SSM Parameters', name, success)
                param_names = param_names[10:]
        except ClientError as e:
            logging.error(f"[{region}] Error listing/deleting SSM params: {e}")

    def delete_log_groups(self, logs, region):
        try:
            paginator = logs.get_paginator('describe_log_groups')
            for page in paginator.paginate():
                lgs = page.get('logGroups', [])
                for lg in lgs:
                    lg_name = lg['logGroupName']
                    logging.info(f"[{region}] Deleting log group {lg_name}")
                    success = retry_delete(lambda: logs.delete_log_group(logGroupName=lg_name),
                                           f"Delete log group {lg_name}")
                    self._record_result('CloudWatch Log Groups', lg_name, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing log groups: {e}")

    def delete_elasticache_clusters(self, elasticache, region):
        try:
            clusters = elasticache.describe_cache_clusters(ShowCacheNodeInfo=True).get('CacheClusters', [])
            for cluster in clusters:
                cluster_id = cluster['CacheClusterId']
                logging.info(f"[{region}] Deleting Elasticache cluster {cluster_id}")
                success = retry_delete(lambda: elasticache.delete_cache_cluster(CacheClusterId=cluster_id),
                                       f"Delete Elasticache cluster {cluster_id}")
                self._record_result('Elasticache Clusters', cluster_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Elasticache clusters: {e}")

    def delete_redshift_clusters(self, redshift, region):
        try:
            clusters = redshift.describe_clusters().get('Clusters', [])
            for cluster in clusters:
                cluster_id = cluster['ClusterIdentifier']
                logging.info(f"[{region}] Deleting Redshift cluster {cluster_id}")
                success = retry_delete(lambda: redshift.delete_cluster(ClusterIdentifier=cluster_id,
                                                                       SkipFinalClusterSnapshot=True),
                                       f"Delete Redshift cluster {cluster_id}")
                self._record_result('Redshift Clusters', cluster_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Redshift clusters: {e}")

    def delete_ebs_volumes_and_snapshots(self, ec2, region):
        try:
            volumes = ec2.describe_volumes(Filters=[{'Name': 'status', 'Values': ['available']}]).get('Volumes', [])
            for volume in volumes:
                vol_id = volume['VolumeId']
                logging.info(f"[{region}] Deleting EBS volume {vol_id}")
                success = retry_delete(lambda: ec2.delete_volume(VolumeId=vol_id),
                                       f"Delete EBS Volume {vol_id}")
                self._record_result('EBS Volumes', vol_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing/deleting EBS volumes: {e}")
        try:
            snapshots = ec2.describe_snapshots(OwnerIds=[self.account_id]).get('Snapshots', [])
            for snap in snapshots:
                snap_id = snap['SnapshotId']
                logging.info(f"[{region}] Deleting EBS snapshot {snap_id}")
                success = retry_delete(lambda: ec2.delete_snapshot(SnapshotId=snap_id),
                                       f"Delete EBS Snapshot {snap_id}")
                self._record_result('EBS Snapshots', snap_id, success)
        except ClientError as e:
            logging.error(f"[{region}] Error describing/deleting EBS snapshots: {e}")

    def delete_eks_clusters_global(self):
        regions = [self.session.region_name] if self.session.region_name else self.get_all_regions()
        for region in regions:
            eks_client = self.session.client('eks', region_name=region)
            try:
                clusters = eks_client.list_clusters().get('clusters', [])
                for c in clusters:
                    logging.info(f"[{region}] Deleting EKS cluster {c}")
                    self.delete_eks_nodegroups(eks_client, region, c)
                    success = True
                    try:
                        eks_client.delete_cluster(name=c)
                    except ClientError as e:
                        logging.error(f"[{region}] Error deleting EKS cluster {c}: {e}")
                        success = False
                    self._record_result('EKS Clusters', f"{c} ({region})", success)
                    time.sleep(SLEEP_LONG)
            except ClientError as e:
                logging.error(f"[{region}] Error listing EKS clusters: {e}")

    def delete_eks_nodegroups(self, eks_client, region, cluster_name):
        try:
            ngs = eks_client.list_nodegroups(clusterName=cluster_name).get('nodegroups', [])
            for ng in ngs:
                logging.info(f"[{region}] Deleting EKS nodegroup {ng} in cluster {cluster_name}")
                try:
                    eks_client.delete_nodegroup(clusterName=cluster_name, nodegroupName=ng)
                except ClientError as e:
                    logging.error(f"[{region}] Error deleting nodegroup {ng}: {e}")
                self.wait_for_nodegroup_deletion(eks_client, region, cluster_name, ng)
        except ClientError as e:
            logging.error(f"[{region}] Error listing nodegroups for {cluster_name}: {e}")
        try:
            fps = eks_client.list_fargate_profiles(clusterName=cluster_name).get('fargateProfileNames', [])
            for fp in fps:
                logging.info(f"[{region}] Deleting EKS fargate profile {fp} in cluster {cluster_name}")
                try:
                    eks_client.delete_fargate_profile(clusterName=cluster_name, fargateProfileName=fp)
                except ClientError as e:
                    logging.error(f"[{region}] Error deleting fargate profile {fp}: {e}")
                time.sleep(SLEEP_MEDIUM)
        except ClientError as e:
            logging.error(f"[{region}] Error listing fargate profiles: {e}")

    def wait_for_nodegroup_deletion(self, eks_client, region, cluster, ng):
        for attempt in range(30):
            try:
                resp = eks_client.describe_nodegroup(clusterName=cluster, nodegroupName=ng)
                status = resp['nodegroup']['status']
                if status in ['DELETING', 'CREATE_FAILED', 'ACTIVE', 'UPDATING']:
                    logging.info(f"[{region}] EKS nodegroup {ng} in cluster {cluster} => {status}. Wait.")
                    time.sleep(SLEEP_LONG)
                else:
                    logging.info(f"[{region}] Nodegroup {ng} => {status}. Assuming done.")
                    return
            except ClientError:
                logging.info(f"[{region}] Nodegroup {ng} no longer exists.")
                return

    def delete_all_iam_roles_global(self):
        iam = self.session.client('iam')
        try:
            roles_resp = iam.list_roles()
            roles = roles_resp.get('Roles', [])
            for role in roles:
                rname = role['RoleName']
                if rname.startswith('AWSServiceRoleFor'):
                    continue
                try:
                    iam.get_role(RoleName=rname)
                except ClientError as e:
                    if e.response['Error']['Code'] == 'NoSuchEntity':
                        continue
                self._remove_policies_from_role(iam, rname)
                self._remove_role_from_instance_profiles(iam, rname)
                success = True
                try:
                    iam.delete_role(RoleName=rname)
                except ClientError as e:
                    logging.error(f"Error deleting IAM role {rname}: {e}")
                    success = False
                self._record_result('IAM Roles', rname, success)
                time.sleep(SLEEP_SHORT)
        except ClientError as e:
            logging.error(f"Error listing IAM roles: {e}")

    def _remove_policies_from_role(self, iam, role_name):
        try:
            att_pols = iam.list_attached_role_policies(RoleName=role_name).get('AttachedPolicies', [])
            for p in att_pols:
                p_arn = p['PolicyArn']
                retry_delete(lambda: iam.detach_role_policy(RoleName=role_name, PolicyArn=p_arn),
                             f"Detach policy {p_arn} from {role_name}")
        except ClientError as e:
            logging.error(f"Error detaching policies from {role_name}: {e}")
        try:
            inlines = iam.list_role_policies(RoleName=role_name).get('PolicyNames', [])
            for pol in inlines:
                retry_delete(lambda: iam.delete_role_policy(RoleName=role_name, PolicyName=pol),
                             f"Delete inline policy {pol} from {role_name}")
        except ClientError as e:
            logging.error(f"Error removing inline policies from {role_name}: {e}")

    def _remove_role_from_instance_profiles(self, iam, role_name):
        paginator = iam.get_paginator('list_instance_profiles_for_role')
        for page in paginator.paginate(RoleName=role_name):
            profiles = page.get('InstanceProfiles', [])
            for p in profiles:
                p_name = p['InstanceProfileName']
                retry_delete(lambda: iam.remove_role_from_instance_profile(InstanceProfileName=p_name, RoleName=role_name),
                             f"Remove {role_name} from {p_name}")
                success = retry_delete(lambda: iam.delete_instance_profile(InstanceProfileName=p_name),
                                       f"Delete instance profile {p_name}")
                self._record_result('Instance IAM Profiles', p_name, success)

    def delete_service_linked_roles_global(self):
        iam = self.session.client('iam')
        try:
            roles = iam.list_roles()['Roles']
            for role in roles:
                role_name = role['RoleName']
                if role_name.startswith('AWSServiceRoleFor'):
                    logging.info(f"Deleting service-linked role {role_name}")
                    try:
                        iam.delete_service_linked_role(RoleName=role_name)
                        self._record_result('Service-Linked Roles', role_name, True)
                    except ClientError as e:
                        logging.error(f"Error deleting service-linked role {role_name}: {e}")
                        self._record_result('Service-Linked Roles', role_name, False, str(e))
        except ClientError as e:
            logging.error(f"Error listing IAM roles for service-linked deletion: {e}")

    def deregister_ssm_managed_instances(self, ssm):
        try:
            info = ssm.describe_instance_information().get('InstanceInformationList', [])
            for instance in info:
                instance_id = instance['InstanceId']
                logging.info(f"Deregistering SSM managed instance {instance_id}")
                success = retry_delete(lambda: ssm.deregister_managed_instance(InstanceId=instance_id),
                                       f"Deregister SSM managed instance {instance_id}")
                self._record_result('SSM Managed Instances', instance_id, success)
        except ClientError as e:
            logging.error(f"Error deregistering SSM managed instances: {e}")

    def delete_aws_backup_vaults_global(self):
        backup_client = self.session.client('backup')
        try:
            vaults = backup_client.list_backup_vaults().get('BackupVaultList', [])
            for vault in vaults:
                vault_name = vault['BackupVaultName']
                rec_points = backup_client.list_recovery_points_by_backup_vault(BackupVaultName=vault_name).get('RecoveryPoints', [])
                for rp in rec_points:
                    rp_id = rp['RecoveryPointArn']
                    logging.info(f"Deleting recovery point {rp_id} in vault {vault_name}")
                    retry_delete(lambda: backup_client.delete_recovery_point(BackupVaultName=vault_name, RecoveryPointArn=rp_id),
                                 f"Delete recovery point {rp_id}")
                logging.info(f"Deleting backup vault {vault_name}")
                success = retry_delete(lambda: backup_client.delete_backup_vault(BackupVaultName=vault_name),
                                       f"Delete backup vault {vault_name}")
                self._record_result('AWS Backup Vaults', vault_name, success)
        except ClientError as e:
            logging.error(f"Error deleting AWS Backup vaults: {e}")

    def delete_elastic_beanstalk_environments_global(self):
        eb = self.session.client('elasticbeanstalk')
        try:
            envs = eb.describe_environments()['Environments']
            for env in envs:
                env_id = env['EnvironmentId']
                env_name = env['EnvironmentName']
                logging.info(f"Terminating Elastic Beanstalk environment {env_name} ({env_id})")
                success = retry_delete(lambda: eb.terminate_environment(EnvironmentName=env_name, TerminateResources=True),
                                       f"Terminate Elastic Beanstalk environment {env_name}")
                self._record_result('Elastic Beanstalk Environments', env_name, success)
        except ClientError as e:
            logging.error(f"Error terminating Elastic Beanstalk environments: {e}")

    @timed
    def delete_global_accelerators_global(self):
        ga = self.session.client('globalaccelerator', region_name='us-west-2')
        try:
            accelerators = ga.list_accelerators().get('Accelerators', [])
            for accelerator in accelerators:
                accelerator_arn = accelerator['AcceleratorArn']
                accelerator_name = accelerator.get('Name', 'Unnamed Accelerator')
                try:
                    ga.update_accelerator(AcceleratorArn=accelerator_arn, Enabled=False)
                    logging.info(f"Disabled Global Accelerator: {accelerator_name} ({accelerator_arn})")
                except ClientError as e:
                    logging.error(f"Failed to disable Global Accelerator {accelerator_name} ({accelerator_arn}): {e}")
                    self._record_result('Global Accelerators', accelerator_name, False, f"Failed to disable: {e}")
                    continue
                try:
                    ga.delete_accelerator(AcceleratorArn=accelerator_arn)
                    logging.info(f"Deleted Global Accelerator: {accelerator_name} ({accelerator_arn})")
                    self._record_result('Global Accelerators', accelerator_name, True)
                except ClientError as e:
                    logging.error(f"Failed to delete Global Accelerator {accelerator_name} ({accelerator_arn}): {e}")
                    self._record_result('Global Accelerators', accelerator_name, False, str(e))
        except ClientError as e:
            logging.error(f"Error listing Global Accelerators: {e}")

    def delete_route53_hosted_zones_global(self):
        r53 = self.session.client('route53')
        try:
            zones = r53.list_hosted_zones().get('HostedZones', [])
            for zone in zones:
                zone_id = zone['Id'].split('/')[-1]
                record_sets = r53.list_resource_record_sets(HostedZoneId=zone_id).get('ResourceRecordSets', [])
                changes = []
                for record in record_sets:
                    if record['Type'] in ['NS', 'SOA']:
                        continue
                    changes.append({'Action': 'DELETE', 'ResourceRecordSet': record})
                if changes:
                    logging.info(f"Deleting records for hosted zone {zone_id}")
                    retry_delete(lambda: r53.change_resource_record_sets(HostedZoneId=zone_id,
                                                                         ChangeBatch={'Changes': changes}),
                                 f"Delete records in hosted zone {zone_id}")
                logging.info(f"Deleting hosted zone {zone_id}")
                success = retry_delete(lambda: r53.delete_hosted_zone(Id=zone_id),
                                       f"Delete hosted zone {zone_id}")
                self._record_result('Route53 Hosted Zones', zone_id, success)
        except ClientError as e:
            logging.error(f"Error deleting Route53 hosted zones: {e}")

    def delete_cloudfront_distributions_global(self):
        cf = self.session.client('cloudfront')
        try:
            distributions = cf.list_distributions().get('DistributionList', {}).get('Items', [])
            for dist in distributions:
                dist_id = dist['Id']
                config_resp = cf.get_distribution_config(Id=dist_id)
                etag = config_resp['ETag']
                config = config_resp['DistributionConfig']
                if config.get('Enabled', True):
                    config['Enabled'] = False
                    logging.info(f"Disabling CloudFront distribution {dist_id}")
                    retry_delete(lambda: cf.update_distribution(DistributionConfig=config, Id=dist_id, IfMatch=etag),
                                 f"Disable CloudFront distribution {dist_id}")
                    time.sleep(SLEEP_LONG)
                logging.info(f"Deleting CloudFront distribution {dist_id}")
                config_resp = cf.get_distribution_config(Id=dist_id)
                etag = config_resp['ETag']
                success = retry_delete(lambda: cf.delete_distribution(Id=dist_id, IfMatch=etag),
                                       f"Delete CloudFront distribution {dist_id}")
                self._record_result('CloudFront Distributions', dist_id, success)
        except ClientError as e:
            logging.error(f"Error deleting CloudFront distributions: {e}")

    def purge_aws(self, region=None):
        if region:
            regions = [region]
            logging.info(f"Cleaning only region {region}")
        else:
            regions = self.get_all_regions()
            if not regions:
                logging.error('No regions found. Exiting.')
                return
        with ThreadPoolExecutor(max_workers=min(10, len(regions))) as executor:
            future_map = {executor.submit(self.cleanup_region, r): r for r in regions}
            for fut in as_completed(future_map):
                r = future_map[fut]
                try:
                    fut.result()
                    logging.info(f"Completed region {r}")
                except Exception as ex:
                    logging.error(f"Region {r} encountered fatal error: {ex}")
        self.delete_eks_clusters_global()
        self.delete_all_iam_roles_global()
        self.delete_service_linked_roles_global()
        self.delete_global_accelerators_global()
        self.delete_route53_hosted_zones_global()
        self.delete_cloudfront_distributions_global()
        self.delete_elastic_beanstalk_environments_global()
        self.delete_aws_backup_vaults_global()
        ssm_global = self.session.client('ssm')
        self.deregister_ssm_managed_instances(ssm_global)
        self.delete_s3_buckets_global()
        logging.info('=== AWS Super Cleanup complete! ===')
        self.print_report()

def parse_args():
    parser = argparse.ArgumentParser(description='Super AWS Cleanup Script')
    parser.add_argument('--region', help='Optional region to clean. If not provided, all regions are processed.', default=None)
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Increase verbosity level (-v for INFO, -vv for DEBUG)')
    return parser.parse_args()

def main():
    args = parse_args()
    if args.verbose >= 2:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.verbose == 1:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.WARNING)
    cleaner = SuperAWSResourceCleaner()
    cleaner.purge_aws(region=args.region)

if __name__ == '__main__':
    main()
