import logging
import time
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from botocore.exceptions import ClientError, WaiterError, EndpointConnectionError

from awswipe.core.config import Config
from awswipe.core.retry import retry_delete, SLEEP_LONG, SLEEP_SHORT
from awswipe.core.logging import timed
from awswipe.resources.s3 import S3Cleaner
from awswipe.resources.iam import IamCleaner
from awswipe.resources.ec2 import EC2Cleaner
from awswipe.resources.ebs import EBSCleaner
from awswipe.resources.lambda_ import LambdaCleaner
from awswipe.resources.elb import ELBCleaner
from awswipe.resources.autoscaling import ASGCleaner
from awswipe.resources.vpc import VPCCleaner
from awswipe.resources.sagemaker import SageMakerCleaner

class SuperAWSResourceCleaner:
    def __init__(self, config: Config):
        self.config = config
        self.session = boto3.session.Session()
        self.report = {}
        try:
            sts = self.session.client('sts')
            self.account_id = sts.get_caller_identity()['Account']
        except ClientError as e:
            logging.error("Error retrieving account ID: %s", e)
            self.account_id = None
        
        # Initialize sub-cleaners
        self.s3_cleaner = S3Cleaner(self.session, self.config, self.report)
        self.iam_cleaner = IamCleaner(self.session, self.config, self.report)
        self.ec2_cleaner = EC2Cleaner(self.session, self.config, self.report)
        self.ebs_cleaner = EBSCleaner(self.session, self.config, self.report)
        self.lambda_cleaner = LambdaCleaner(self.session, self.config, self.report)
        self.elb_cleaner = ELBCleaner(self.session, self.config, self.report)
        self.asg_cleaner = ASGCleaner(self.session, self.config, self.report)
        self.vpc_cleaner = VPCCleaner(self.session, self.config, self.report)
        self.sagemaker_cleaner = SageMakerCleaner(self.session, self.config, self.report)

    def _record_result(self, resource_type, resource_id, success, message=''):
        if self.config.dry_run:
            return
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
    def cleanup_region(self, region):
        from awswipe.core.dependency_graph import DependencyGraph
        
        graph = DependencyGraph()
        
        # Register cleaners and their prerequisites
        # We map 'resource_type' string to the cleaner instance method
        cleaners_map = {
            's3': self.s3_cleaner, # Global, but maybe regional buckets?
            'iam': self.iam_cleaner, # Global
            'ec2': self.ec2_cleaner,
            'ebs': self.ebs_cleaner,
            'lambda': self.lambda_cleaner,
            'elb': self.elb_cleaner,
            'asg': self.asg_cleaner,
            'vpc': self.vpc_cleaner,
            'sagemaker': self.sagemaker_cleaner,
            # Add placeholders for others if they don't have cleaners yet but are dependencies
            'rds': None,
            'elasticache': None,
            'efs': None,
        }
        
        # Add nodes to graph
        for name, cleaner in cleaners_map.items():
            if cleaner:
                graph.add_node(name, cleaner.prerequisites)
            else:
                # For placeholders, we assume no prerequisites for now, or we just don't add them
                # If they are prerequisites of others, they will be added by add_node logic
                pass

        execution_order = graph.get_execution_order()
        logging.info(f"[{region}] Cleanup execution order: {execution_order}")
        
        for resource in execution_order:
            if resource in cleaners_map and cleaners_map[resource]:
                logging.info(f"[{region}] Cleaning {resource}")
                cleaners_map[resource].cleanup(region)
            elif hasattr(self, f'delete_{resource}'):
                 # Fallback for legacy methods or placeholders that map to legacy methods
                 # We need to ensure legacy methods are available or mapped
                 logging.info(f"[{region}] Cleaning {resource} (legacy)")
                 getattr(self, f'delete_{resource}')(region)
            else:
                 logging.debug(f"[{region}] No cleaner for {resource}, skipping")

        # Legacy cleanup for things not in the graph yet
        # We can keep the old list for things NOT in execution_order
        # But for now, let's trust the graph for the main resources we migrated.
        
        # What about resources NOT in the graph but in the old list?
        # 'kms_keys', 'efs', 'elasticache', 'rds', 'dynamodb', 'sqs', 'sns', 'codebuild_projects'
        # We should add them to the graph or run them separately.
        # Ideally, we migrate them to cleaners or add them to the graph with legacy mapping.
        
        legacy_resources = [
            'kms_keys', 'efs', 'elasticache', 'rds', 'dynamodb', 'sqs', 'sns', 'codebuild_projects'
        ]
        # These usually don't have strong dependencies on the new stuff, except maybe VPC?
        # RDS/ElastiCache/EFS are in VPC, so they should run BEFORE VPC.
        # VPCCleaner depends on them.
        # So we should add them to the graph.
        
        # Let's add them to the graph with empty prerequisites for now (or correct ones if known)
        # And ensure we have a way to call them.
        
        # Update cleaners_map with legacy methods mapping if possible, or just handle in loop
        # But 'delete_rds' expects 'region' arg.
        
        # Let's add them to the graph.
        for res in legacy_resources:
            graph.add_node(res, []) # Assume no prereqs for now
            
        # Re-calculate order
        execution_order = graph.get_execution_order()
        logging.info(f"[{region}] Final execution order: {execution_order}")

        for resource in execution_order:
            if resource in cleaners_map and cleaners_map[resource]:
                cleaners_map[resource].cleanup(region)
            elif hasattr(self, f'delete_{resource}'):
                getattr(self, f'delete_{resource}')(region)
            elif hasattr(self, f'delete_{resource}_global'):
                 # Some might be global? No, cleanup_region is regional.
                 pass

    # --- Delegated Methods ---
    def delete_s3_buckets_global(self):
        self.s3_cleaner.cleanup()

    def delete_all_iam_roles_global(self):
        self.iam_cleaner.delete_all_iam_roles_global()

    def delete_service_linked_roles_global(self):
        self.iam_cleaner.delete_service_linked_roles_global()

    def delete_ec2(self, region):
        self.ec2_cleaner.cleanup(region)

    def delete_ebs(self, region):
        self.ebs_cleaner.cleanup(region)

    def delete_lambda(self, region):
        self.lambda_cleaner.cleanup(region)

    def delete_elb(self, region):
        self.elb_cleaner.cleanup(region)

    def delete_asg(self, region):
        self.asg_cleaner.cleanup(region)

    def delete_vpc(self, region):
        self.vpc_cleaner.cleanup(region)

    # --- Existing Methods (kept for now) ---
    
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
                    if not self.config.dry_run:
                        try:
                            eks_client.delete_cluster(name=c)
                        except ClientError as e:
                            logging.error(f"[{region}] Error deleting EKS cluster {c}: {e}")
                            success = False
                        self._record_result('EKS Clusters', f"{c} ({region})", success)
                        time.sleep(SLEEP_LONG)
                    else:
                        logging.info(f"[Dry-Run] Would delete EKS cluster {c}")
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
                        if not self.config.dry_run:
                            try:
                                eks_client.delete_nodegroup(clusterName=cluster, nodegroupName=ng)
                                self.wait_for_nodegroup_deletion(eks_client, region, cluster, ng)
                            except ClientError as e:
                                code = e.response.get('Error', {}).get('Code', '')
                                if code != 'ResourceNotFoundException':
                                    logging.error(f"[{region}] Failed to delete nodegroup {ng}: {e}")
                        else:
                            logging.info(f"[Dry-Run] Would delete nodegroup {ng}")
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

    def deregister_ssm_managed_instances(self, ssm):
        try:
            info = ssm.describe_instance_information().get('InstanceInformationList', [])
            for instance in info:
                instance_id = instance['InstanceId']
                logging.info(f"Deregistering SSM managed instance {instance_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ssm.deregister_managed_instance(InstanceId=instance_id),
                                           f"Deregister SSM managed instance {instance_id}")
                    self._record_result('SSM Managed Instances', instance_id, success)
                else:
                    logging.info(f"[Dry-Run] Would deregister SSM instance {instance_id}")
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
                    if not self.config.dry_run:
                        retry_delete(lambda: backup_client.delete_recovery_point(BackupVaultName=vault_name, RecoveryPointArn=rp_id),
                                     f"Delete recovery point {rp_id}")
                    else:
                        logging.info(f"[Dry-Run] Would delete recovery point {rp_id}")
                
                logging.info(f"Deleting backup vault {vault_name}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: backup_client.delete_backup_vault(BackupVaultName=vault_name),
                                           f"Delete backup vault {vault_name}")
                    self._record_result('AWS Backup Vaults', vault_name, success)
                else:
                    logging.info(f"[Dry-Run] Would delete backup vault {vault_name}")
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
                if not self.config.dry_run:
                    success = retry_delete(lambda: eb.terminate_environment(EnvironmentName=env_name, TerminateResources=True),
                                           f"Terminate Elastic Beanstalk environment {env_name}")
                    self._record_result('Elastic Beanstalk Environments', env_name, success)
                else:
                    logging.info(f"[Dry-Run] Would terminate EB environment {env_name}")
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
                if not self.config.dry_run:
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
                else:
                    logging.info(f"[Dry-Run] Would disable and delete Global Accelerator {accelerator_name}")
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
                
                if not self.config.dry_run:
                    if changes:
                        logging.info(f"Deleting records for hosted zone {zone_id}")
                        retry_delete(lambda: r53.change_resource_record_sets(HostedZoneId=zone_id,
                                                                             ChangeBatch={'Changes': changes}),
                                     f"Delete records in hosted zone {zone_id}")
                    logging.info(f"Deleting hosted zone {zone_id}")
                    success = retry_delete(lambda: r53.delete_hosted_zone(Id=zone_id),
                                           f"Delete hosted zone {zone_id}")
                    self._record_result('Route53 Hosted Zones', zone_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete records and hosted zone {zone_id}")
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
                
                if not self.config.dry_run:
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
                else:
                    logging.info(f"[Dry-Run] Would disable and delete CloudFront distribution {dist_id}")
        except ClientError as e:
            logging.error(f"Error deleting CloudFront distributions: {e}")

    def delete_bedrock_resources(self, bedrock, region):
        try:
            models = bedrock.list_models().get('Models', [])
            for model in models:
                model_arn = model['Arn']
                logging.info(f"[{region}] Deleting Bedrock model {model_arn}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: bedrock.delete_model(arn=model_arn), f"Delete Bedrock model {model_arn}")
                    self._record_result('Bedrock Models', model_arn, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Bedrock model {model_arn}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Bedrock models: {e}")

    def delete_codebuild_projects(self, region):
        try:
            codebuild = self.session.client('codebuild', region_name=region)
            projects = codebuild.list_projects().get('projects', [])
            for project in projects:
                logging.info(f"[{region}] Deleting CodeBuild project {project}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: codebuild.delete_project(name=project),
                        f"Delete CodeBuild project {project}"
                    )
                    self._record_result('CodeBuild Projects', project, success)
                else:
                    logging.info(f"[Dry-Run] Would delete CodeBuild project {project}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting CodeBuild projects: {e}")

    def delete_apprunner_services(self, region):
        try:
            if not self.is_service_available(region, 'apprunner'):
                return
            client = self.session.client('apprunner', region_name=region)
            services = client.list_services().get('ServiceSummaryList', [])
            for svc in services:
                if not self.config.dry_run:
                    client.delete_service(ServiceArn=svc['ServiceArn'])
                    self._record_result('AppRunner Services', svc['ServiceArn'], True)
                else:
                    logging.info(f"[Dry-Run] Would delete AppRunner service {svc['ServiceArn']}")
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
                if not self.config.dry_run:
                    client.delete_app(appId=app['appId'])
                    self._record_result('Amplify Apps', app['appId'], True)
                else:
                    logging.info(f"[Dry-Run] Would delete Amplify app {app['appId']}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Amplify apps: {e}")

    @timed
    def delete_kms_keys(self, region):
        try:
            kms_client = self.session.client('kms', region_name=region)
            paginator = kms_client.get_paginator('list_keys')
            keys = []
            for page in paginator.paginate():
                keys.extend(page['Keys'])
            
            for key in keys:
                key_id = key['KeyId']
                try:
                    key_info = kms_client.describe_key(KeyId=key_id)
                    if key_info['KeyMetadata']['KeyManager'] == 'AWS' or key_info['KeyMetadata'].get('DeletionDate'):
                        continue
                    
                    if key_info['KeyMetadata']['KeyState'] not in ['PendingDeletion', 'PendingReplicaDeletion']:
                        logging.info(f"[{region}] Disabling KMS key {key_id}")
                        if not self.config.dry_run:
                            kms_client.disable_key(KeyId=key_id)
                            logging.info(f"[{region}] Scheduling KMS key {key_id} for deletion")
                            success = retry_delete(
                                lambda: kms_client.schedule_key_deletion(KeyId=key_id, PendingWindowInDays=7),
                                f"Schedule KMS key {key_id} deletion"
                            )
                            self._record_result('KMS Keys', f"{key_id} ({region})", success)
                        else:
                            logging.info(f"[Dry-Run] Would disable and schedule deletion for KMS key {key_id}")
                except ClientError as e:
                    logging.error(f"[{region}] Error processing KMS key {key_id}: {e}")
                    self._record_result('KMS Keys', f"{key_id} ({region})", False, str(e))
        except ClientError as e:
            logging.error(f"[{region}] Error accessing KMS: {e}")

    def purge_aws(self):
        if "all" in self.config.regions:
            regions = self.get_all_regions()
            if not regions:
                logging.error('No regions found. Exiting.')
                return
        else:
            regions = self.config.regions
            logging.info(f"Cleaning regions: {regions}")

        if self.config.dry_run:
            logging.info("Running in dry-run mode - no resources will be deleted")

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

    def resolve_dependencies(self, resource_type):
        DEPENDENCY_GRAPH = {
            'vpc': ['ec2', 'rds', 'elasticache', 'elb', 'lambda', 'asg', 'ebs'],
            'eks_cluster': ['nodegroup', 'fargate_profile'],
            'rds': ['db_subnet_group', 'option_group'],
            'iam_role': ['lambda', 'ec2', 'eks'],
            'kms_keys': [],
            'asg': ['ec2'],
            'ec2': ['ebs', 'elb'], # EC2 instances might be attached to ELBs or have EBS volumes
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
