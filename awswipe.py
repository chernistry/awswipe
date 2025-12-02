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
from botocore.exceptions import ClientError, WaiterError, EndpointConnectionError

SLEEP_SHORT, SLEEP_MEDIUM, SLEEP_LONG, SLEEP_EXTRA_LONG = 2, 5, 10, 30

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def retry_delete(operation, description, max_attempts=8):
    base_delay = 1.2
    for attempt in range(max_attempts):
        try:
            return operation()
        except ClientError as e:
            code = e.response.get('Error', {}).get('Code', '')
            if code in ['Throttling', 'RequestLimitExceeded']:
                jitter = random.uniform(0.5, 1.5)
                delay = min(base_delay * (2 ** attempt) * jitter, 60)
                time.sleep(delay)
            else:
                raise
    raise Exception(f"Max retries ({max_attempts}) exceeded for {description}")

def retry_delete_with_backoff(operation, description, max_attempts=8, base_delay=SLEEP_SHORT):
    attempts = 0
    while attempts < max_attempts:
        try:
            operation()
            logging.info(f'{description} succeeded')
            return True
        except ClientError as e:
            code = e.response.get('Error', {}).get('Code', '')
            if code in ['Throttling', 'RequestLimitExceeded']:
                delay = base_delay * (2 ** (attempts - 1)) + random.uniform(0, 1)
                logging.warning(f'{description} failed with {code}; retrying in {delay:.2f} seconds...')
                time.sleep(delay)
            else:
                logging.error(f'{description} failed: {e}')
                return False
        attempts += 1
    logging.error(f'{description} failed after {max_attempts} attempts')
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
            regions = [r['RegionName'] for r in ec2.describe_regions()['Regions']]
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
                success = retry_delete(lambda: s3.delete_bucket(Bucket=b_name), f"Delete S3 Bucket {b_name}")
                self._record_result('S3 Buckets', b_name, success, '' if success else 'Cannot delete bucket; may require MFA')
        except ClientError as e:
            logging.error('Error listing S3 buckets: %s', e)

    def _empty_s3_bucket(self, s3, bucket_name):
        logging.info('Emptying bucket: %s', bucket_name)
        try:
            uploads = s3.list_multipart_uploads(Bucket=bucket_name).get('Uploads', [])
            for upload in uploads:
                key, upload_id = upload['Key'], upload['UploadId']
                retry_delete(lambda: s3.abort_multipart_upload(Bucket=bucket_name, Key=key, UploadId=upload_id), f"Abort MPU for {key}")
        except ClientError:
            pass
        paginator = s3.get_paginator('list_object_versions')
        try:
            for page in paginator.paginate(Bucket=bucket_name):
                objs = [{'Key': v['Key'], 'VersionId': v['VersionId']} for v in page.get('Versions', [])]
                objs += [{'Key': d['Key'], 'VersionId': d['VersionId']} for d in page.get('DeleteMarkers', [])]
                while objs:
                    batch = objs[:1000]
                    del_objs = {'Objects': batch, 'Quiet': True}
                    success = retry_delete(lambda: s3.delete_objects(Bucket=bucket_name, Delete=del_objs), f"Deleting objects in {bucket_name}")
                    objs = objs[1000:]
                    if not success:
                        break
        except ClientError as e:
            logging.warning('Could not fully list/delete objects in %s: %s', bucket_name, e)

    @timed
    def cleanup_region(self, region):
        visited = set()
        def dfs(resource):
            for dependency in self.resolve_dependencies(resource):
                if dependency not in visited:
                    dfs(dependency)
            if hasattr(self, f'delete_{resource}'):
                getattr(self, f'delete_{resource}')(region)
            visited.add(resource)
        
        cleanup_order = [
            'kms_keys',  # Processed LAST in regional cleanup due to reversed iteration
            # Add other fundamental/shared resources that should be deleted very late (appearing early in this list)
            # e.g., 'vpc' would typically be here or handled with very specific dependency logic

            # Services to be deleted EARLIER in the region (appearing later in this list)
            'efs',
            'elasticache',
            'rds',
            'dynamodb',
            'sqs',
            'sns',
            'codebuild_projects',
            # 's3', # S3 buckets are global and handled by delete_s3_buckets_global.
                     # If specific regional S3 constructs (like Access Points) need cleanup,
                     # a dedicated delete_s3_regional_resources(self, region) method and entry here would be needed.
            # 'iam_roles_global', # IAM roles are global and handled by delete_all_iam_roles_global()
        ]
        
        for resource in reversed(cleanup_order):
            if resource not in visited:
                dfs(resource)

    def delete_eks_clusters_global(self):
        regions = [self.session.region_name] if self.session.region_name else self.get_all_regions()
        for region in regions:
            if not self.is_service_available(region, 'eks'):
                logging.info(f"[{region}] EKS not available, skipping")
                continue
            eks_client = self.session.client('eks', region_name=region)
            try:
                clusters = eks_client.list_clusters().get('clusters', [])
                for c in clusters:
                    logging.info(f"[{region}] Deleting EKS cluster {c}")
                    self.delete_eks_nodegroups(region, c)
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

    def delete_eks_nodegroups(self, region, cluster_name=None):
        eks_client = self.session.client('eks', region_name=region)
        try:
            clusters = [cluster_name] if cluster_name else eks_client.list_clusters().get('clusters', [])
            for cluster in clusters:
                try:
                    ngs = eks_client.list_nodegroups(clusterName=cluster).get('nodegroups', [])
                    for ng in ngs:
                        logging.info(f"[{region}] Deleting nodegroup {ng} in cluster {cluster}")
                        try:
                            eks_client.delete_nodegroup(clusterName=cluster, nodegroupName=ng)
                            self.wait_for_nodegroup_deletion(eks_client, region, cluster, ng)
                        except ClientError as e:
                            code = e.response.get('Error', {}).get('Code', '')
                            if code != 'ResourceNotFoundException':
                                logging.error(f"[{region}] Failed to delete nodegroup {ng}: {e}")
                except ClientError as e:
                    logging.error(f"[{region}] Error listing nodegroups for cluster {cluster}: {e}")
        except ClientError as e:
            logging.error(f"[{region}] EKS nodegroups cleanup failed: {e}")

    def wait_for_nodegroup_deletion(self, eks_client, region, cluster, ng):
        for _ in range(30):
            try:
                resp = eks_client.describe_nodegroup(clusterName=cluster, nodegroupName=ng)
                status = resp['nodegroup']['status']
                if status == 'DELETING':
                    time.sleep(SLEEP_LONG)
                else:
                    return
            except ClientError as e:
                if 'NotFoundException' in str(e):
                    return
                else:
                    logging.error(f"[{region}] Error checking nodegroup {ng}: {e}")
                    return
        logging.warning(f"[{region}] Timeout waiting for nodegroup {ng} deletion")

    def delete_all_iam_roles_global(self):
        iam = self.session.client('iam')
        try:
            roles = iam.list_roles().get('Roles', [])
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
                retry_delete(lambda: iam.detach_role_policy(RoleName=role_name, PolicyArn=p_arn), f"Detach policy {p_arn} from {role_name}")
        except ClientError as e:
            logging.error(f"Error detaching policies from {role_name}: {e}")
        try:
            inlines = iam.list_role_policies(RoleName=role_name).get('PolicyNames', [])
            for pol in inlines:
                retry_delete(lambda: iam.delete_role_policy(RoleName=role_name, PolicyName=pol), f"Delete inline policy {pol} from {role_name}")
        except ClientError as e:
            logging.error(f"Error removing inline policies from {role_name}: {e}")

    def _remove_role_from_instance_profiles(self, iam, role_name):
        paginator = iam.get_paginator('list_instance_profiles_for_role')
        for page in paginator.paginate(RoleName=role_name):
            profiles = page.get('InstanceProfiles', [])
            for p in profiles:
                p_name = p['InstanceProfileName']
                retry_delete(lambda: iam.remove_role_from_instance_profile(InstanceProfileName=p_name, RoleName=role_name), f"Remove {role_name} from {p_name}")
                success = retry_delete(lambda: iam.delete_instance_profile(InstanceProfileName=p_name), f"Delete instance profile {p_name}")
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

    def delete_bedrock_resources(self, bedrock, region):
        try:
            models = bedrock.list_models().get('Models', [])
            for model in models:
                model_arn = model['Arn']
                logging.info(f"[{region}] Deleting Bedrock model {model_arn}")
                success = retry_delete(lambda: bedrock.delete_model(arn=model_arn), f"Delete Bedrock model {model_arn}")
                self._record_result('Bedrock Models', model_arn, success)
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Bedrock models: {e}")

    def delete_codebuild_projects(self, region):
        try:
            codebuild = self.session.client('codebuild', region_name=region)
            projects = codebuild.list_projects().get('projects', [])
            for project in projects:
                logging.info(f"[{region}] Deleting CodeBuild project {project}")
                success = retry_delete(
                    lambda: codebuild.delete_project(name=project),
                    f"Delete CodeBuild project {project}"
                )
                self._record_result('CodeBuild Projects', project, success)
        except ClientError as e:
            logging.error(f"[{region}] Error deleting CodeBuild projects: {e}")

    def delete_apprunner_services(self, region):
        try:
            if not self.is_service_available(region, 'apprunner'):
                return
            client = self.session.client('apprunner', region_name=region)
            services = client.list_services().get('ServiceSummaryList', [])
            for svc in services:
                client.delete_service(ServiceArn=svc['ServiceArn'])
                self._record_result('AppRunner Services', svc['ServiceArn'], True)
        except client.exceptions.ResourceNotFoundException:
            pass
        except ClientError as e:
            if e.response['Error']['Code'] == 'InternalFailure':
                logging.warning(f"[{region}] AppRunner temporary unavailable")
            else:
                raise

    def delete_amplify_apps(self, region):
        client = self.session.client('amplify', region_name=region)
        try:
            apps = client.list_apps()['apps']
            for app in apps:
                client.delete_app(appId=app['appId'])
                self._record_result('Amplify Apps', app['appId'], True)
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Amplify apps: {e}")

    # New function to delete KMS keys
    @timed
    def delete_kms_keys(self, region):
        """
        Delete KMS keys in a region. This will first schedule all customer-managed 
        keys for deletion with a 7-day waiting period (minimum required by AWS).
        """
        try:
            kms_client = self.session.client('kms', region_name=region)
            
            # List all KMS keys in the region
            paginator = kms_client.get_paginator('list_keys')
            keys = []
            
            for page in paginator.paginate():
                keys.extend(page['Keys'])
            
            for key in keys:
                key_id = key['KeyId']
                
                try:
                    # Get key details to determine if it's customer-managed (AWS managed keys can't be deleted)
                    key_info = kms_client.describe_key(KeyId=key_id)
                    
                    # Skip AWS managed keys and keys already scheduled for deletion
                    if key_info['KeyMetadata']['KeyManager'] == 'AWS' or key_info['KeyMetadata'].get('DeletionDate'):
                        continue
                    
                    # Check if key is enabled and not already pending deletion
                    if key_info['KeyMetadata']['KeyState'] not in ['PendingDeletion', 'PendingReplicaDeletion']:
                        # Disable the key first
                        logging.info(f"[{region}] Disabling KMS key {key_id}")
                        kms_client.disable_key(KeyId=key_id)
                        
                        # Schedule key for deletion (minimum 7 days waiting period)
                        logging.info(f"[{region}] Scheduling KMS key {key_id} for deletion")
                        success = retry_delete(
                            lambda: kms_client.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=7),
                            f"Schedule KMS key {key_id} deletion"
                        )
                        self._record_result('KMS Keys', f"{key_id} ({region})", success)
                    
                except ClientError as e:
                    logging.error(f"[{region}] Error processing KMS key {key_id}: {e}")
                    self._record_result('KMS Keys', f"{key_id} ({region})", False, str(e))
                    
        except ClientError as e:
            logging.error(f"[{region}] Error accessing KMS: {e}")

    def purge_aws(self, region=None, dry_run=True):
        if region:
            regions = [region]
            logging.info(f"Cleaning only region {region}")
        else:
            regions = self.get_all_regions()
            if not regions:
                logging.error('No regions found. Exiting.')
                return

        # Add dry-run capability
        if dry_run:
            logging.info("Running in dry-run mode - no resources will be deleted")
            self._record_result = lambda *args, **kwargs: None

        with ThreadPoolExecutor(max_workers=min(20, len(regions))) as executor:
            future_map = {executor.submit(self.cleanup_region, r): r for r in regions}
            for fut in as_completed(future_map):
                r = future_map[fut]
                try:
                    fut.result()
                    logging.info(f"Completed region {r}")
                except Exception as ex:
                    logging.error(f"Region {r} encountered fatal error: {ex}")
                    self._record_result('Region Errors', r, False, str(ex))

        # Add parallel cleanup for global services
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(self.delete_eks_clusters_global),
                executor.submit(self.delete_all_iam_roles_global),
                executor.submit(self.delete_service_linked_roles_global),
                executor.submit(self.delete_global_accelerators_global),
                executor.submit(self.delete_route53_hosted_zones_global),
                executor.submit(self.delete_cloudfront_distributions_global),
                executor.submit(self.delete_elastic_beanstalk_environments_global),
                executor.submit(self.delete_aws_backup_vaults_global),
            ]

            if region:
                # If a specific region is provided, add AppRunner and Amplify tasks for that region.
                futures.append(executor.submit(self.delete_apprunner_services, region))
                futures.append(executor.submit(self.delete_amplify_apps, region))
            else:
                # If no specific region is provided, 'regions' contains all available regions.
                # Add AppRunner and Amplify tasks for each of these regions.
                for r_item in regions: 
                    futures.append(executor.submit(self.delete_apprunner_services, r_item))
                    futures.append(executor.submit(self.delete_amplify_apps, r_item))
            
            for fut in as_completed(futures):
                try:
                    fut.result()
                except Exception as ex:
                    logging.error(f"Global cleanup error: {ex}")

        ssm_global = self.session.client('ssm')
        self.deregister_ssm_managed_instances(ssm_global)
        self.delete_s3_buckets_global()
        logging.info('=== AWS Super Cleanup complete! ===')
        self.print_report()

    def delete_opensearch_domains(self, es, region):
        domains = es.list_domain_names().get('DomainNames', [])
        for domain in domains:
            domain_name = domain['DomainName']
            logging.info(f"[{region}] Deleting OpenSearch domain {domain_name}")
            success = retry_delete(lambda: es.delete_elasticsearch_domain(DomainName=domain_name),
                                  f"Delete OpenSearch domain {domain_name}")
            self._record_result('OpenSearch Domains', domain_name, success)

    def delete_sagemaker_resources(self, sagemaker, region):
        models = sagemaker.list_models().get('Models', [])
        for model in models:
            model_name = model['ModelName']
            logging.info(f"[{region}] Deleting SageMaker model {model_name}")
            success = retry_delete(lambda: sagemaker.delete_model(ModelName=model_name),
                                  f"Delete SageMaker model {model_name}")
            self._record_result('SageMaker Models', model_name, success)

    def delete_lambda_layers(self, region):
        client = self.session.client('lambda', region_name=region)
        layers = []
        paginator = client.get_paginator('list_layers')
        for page in paginator.paginate():
            layers.extend(page['Layers'])
        
        with ThreadPoolExecutor(10) as executor:
            futures = [executor.submit(
                client.delete_layer_version,
                LayerName=layer['LayerName'],
                VersionNumber=layer['LatestMatchingVersion']['VersionNumber']
            ) for layer in layers]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logging.error(f"Error deleting layer version: {e}")

    def resolve_dependencies(self, resource_type):
        DEPENDENCY_GRAPH = {
            'vpc': ['ec2', 'rds', 'elasticache', 'elb'],
            'eks_cluster': ['nodegroup', 'fargate_profile'],
            'rds': ['db_subnet_group', 'option_group'],
            'iam_role': ['lambda', 'ec2', 'eks'],
            'kms_keys': []  # Add KMS keys with no dependencies
        }
        return DEPENDENCY_GRAPH.get(resource_type, [])

    @lru_cache
    def is_service_available(self, region, service_name):
        try:
            client = self.session.client('service-quotas', region_name=region)
            client.list_services()
            return True
        except EndpointConnectionError:
            return False

    def regional_operation(self, func):
        def wrapper(self, region):
            if not self.is_service_available(region, func.__name__[7:]):
                logging.info(f"Skipping {func.__name__} in {region}")
                return
            try:
                return func(self, region)
            except WaiterError as e:
                logging.error(f"Timeout waiting for {func.__name__} in {region}: {e}")
        return wrapper

    def delete_tagged_resources(self, tag_key='Purge', tag_value='true'):
        client = self.session.client('resourcegroupstaggingapi')
        resources = client.get_resources(
            TagFilters=[{'Key': tag_key, 'Values': [tag_value]}]
        )['ResourceTagMappingList']
        
        for resource in resources:
            arn = resource['ResourceARN']
            service = arn.split(':')[2]
            delete_method = getattr(self, f'delete_{service}_resource', None)
            if delete_method:
                delete_method(arn)

    def delete_stacks(self):
        client = self.session.client('cloudformation')
        stacks = client.list_stacks()['StackSummaries']
        for stack in stacks:
            if stack['StackStatus'] not in ['DELETE_COMPLETE']:
                client.delete_stack(StackName=stack['StackName'])

    def pre_delete_checks(self, resource_type, resource_id):
        if resource_type == 'rds':
            client = boto3.client('rds')
            instance = client.describe_db_instances(DBInstanceIdentifier=resource_id)
            if instance['DeletionProtection']:
                raise Exception("Deletion protection enabled")

def parse_args():
    parser = argparse.ArgumentParser(description='Super AWS Cleanup Script')
    parser.add_argument('--region', help='Optional region to clean. If not provided, all regions are processed.', default=None)
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Increase verbosity level (-v for INFO, -vv for DEBUG)')
    parser.add_argument('--live-run', action='store_true', default=False,
                        help='Perform actual deletion of resources. USE WITH EXTREME CAUTION!')
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
    
    if args.live_run:
        logging.warning("--- LIVE RUN MODE ENABLED --- Resources WILL be deleted. --- ")
        # Add a small delay to allow user to cancel if run by mistake
        try:
            for i in range(5, 0, -1):
                print(f"Starting deletion in {i} seconds... (Ctrl+C to cancel)", end='\r')
                time.sleep(1)
            print("                                                          ", end='\r') # Clear line
        except KeyboardInterrupt:
            logging.info("Live run cancelled by user.")
            return
    
    cleaner.purge_aws(region=args.region, dry_run=not args.live_run)

if __name__ == '__main__':
    main()

def adaptive_concurrency():
    current_limit = 10
    while True:
        try:
            # Выполнение операций
            current_limit = min(current_limit * 1.5, 100)
        except ThrottlingException:
            current_limit = max(current_limit * 0.7, 1)
