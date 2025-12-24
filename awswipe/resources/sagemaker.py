import logging
import time
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete, SLEEP_SHORT

class SageMakerCleaner(ResourceCleaner):
    """Cleaner for Amazon SageMaker resources (endpoints, notebook instances, domains)."""
    
    prerequisites = []
    
    def cleanup(self, region):
        if not self.is_service_available(region, 'sagemaker'):
            logging.info(f"[{region}] SageMaker not available, skipping")
            return
        
        client = self.session.client('sagemaker', region_name=region)
        
        self._delete_endpoints(client, region)
        self._delete_endpoint_configs(client, region)
        self._delete_models(client, region)
        self._delete_notebook_instances(client, region)
        self._delete_apps(client, region)
        self._delete_user_profiles(client, region)
        self._delete_domains(client, region)
    
    def _delete_endpoints(self, client, region):
        try:
            endpoints = client.list_endpoints()['Endpoints']
            for ep in endpoints:
                name = ep['EndpointName']
                logging.info(f"[{region}] Deleting SageMaker endpoint {name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda n=name: client.delete_endpoint(EndpointName=n),
                        f"Delete SageMaker endpoint {name}"
                    )
                    self._record_result('SageMaker Endpoints', f"{name} ({region})", success)
                else:
                    logging.info(f"[Dry-Run] Would delete SageMaker endpoint {name}")
        except ClientError as e:
            logging.error(f"[{region}] Error listing SageMaker endpoints: {e}")
    
    def _delete_endpoint_configs(self, client, region):
        try:
            configs = client.list_endpoint_configs()['EndpointConfigs']
            for cfg in configs:
                name = cfg['EndpointConfigName']
                logging.info(f"[{region}] Deleting SageMaker endpoint config {name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda n=name: client.delete_endpoint_config(EndpointConfigName=n),
                        f"Delete SageMaker endpoint config {name}"
                    )
                    self._record_result('SageMaker Endpoint Configs', f"{name} ({region})", success)
                else:
                    logging.info(f"[Dry-Run] Would delete SageMaker endpoint config {name}")
        except ClientError as e:
            logging.error(f"[{region}] Error listing SageMaker endpoint configs: {e}")
    
    def _delete_models(self, client, region):
        try:
            models = client.list_models()['Models']
            for model in models:
                name = model['ModelName']
                logging.info(f"[{region}] Deleting SageMaker model {name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda n=name: client.delete_model(ModelName=n),
                        f"Delete SageMaker model {name}"
                    )
                    self._record_result('SageMaker Models', f"{name} ({region})", success)
                else:
                    logging.info(f"[Dry-Run] Would delete SageMaker model {name}")
        except ClientError as e:
            logging.error(f"[{region}] Error listing SageMaker models: {e}")
    
    def _delete_notebook_instances(self, client, region):
        try:
            notebooks = client.list_notebook_instances()['NotebookInstances']
            for nb in notebooks:
                name = nb['NotebookInstanceName']
                status = nb['NotebookInstanceStatus']
                
                if status == 'InService':
                    logging.info(f"[{region}] Stopping SageMaker notebook {name}")
                    if not self.config.dry_run:
                        client.stop_notebook_instance(NotebookInstanceName=name)
                        self._wait_notebook_stopped(client, name, region)
                
                if status != 'Deleting':
                    logging.info(f"[{region}] Deleting SageMaker notebook {name}")
                    if not self.config.dry_run:
                        success = retry_delete(
                            lambda n=name: client.delete_notebook_instance(NotebookInstanceName=n),
                            f"Delete SageMaker notebook {name}"
                        )
                        self._record_result('SageMaker Notebooks', f"{name} ({region})", success)
                    else:
                        logging.info(f"[Dry-Run] Would delete SageMaker notebook {name}")
        except ClientError as e:
            logging.error(f"[{region}] Error listing SageMaker notebooks: {e}")
    
    def _wait_notebook_stopped(self, client, name, region):
        for _ in range(30):
            try:
                resp = client.describe_notebook_instance(NotebookInstanceName=name)
                if resp['NotebookInstanceStatus'] == 'Stopped':
                    return
                time.sleep(SLEEP_SHORT)
            except ClientError:
                return
        logging.warning(f"[{region}] Timeout waiting for notebook {name} to stop")
    
    def _delete_apps(self, client, region):
        try:
            domains = client.list_domains()['Domains']
            for domain in domains:
                domain_id = domain['DomainId']
                apps = client.list_apps(DomainIdEquals=domain_id)['Apps']
                for app in apps:
                    if app['Status'] == 'Deleted':
                        continue
                    logging.info(f"[{region}] Deleting SageMaker app {app['AppName']} in domain {domain_id}")
                    if not self.config.dry_run:
                        try:
                            client.delete_app(
                                DomainId=domain_id,
                                UserProfileName=app.get('UserProfileName', ''),
                                AppType=app['AppType'],
                                AppName=app['AppName']
                            )
                            self._record_result('SageMaker Apps', f"{app['AppName']} ({region})", True)
                        except ClientError as e:
                            logging.error(f"[{region}] Error deleting app {app['AppName']}: {e}")
                            self._record_result('SageMaker Apps', f"{app['AppName']} ({region})", False, str(e))
        except ClientError as e:
            logging.error(f"[{region}] Error listing SageMaker apps: {e}")
    
    def _delete_user_profiles(self, client, region):
        try:
            domains = client.list_domains()['Domains']
            for domain in domains:
                domain_id = domain['DomainId']
                profiles = client.list_user_profiles(DomainIdEquals=domain_id)['UserProfiles']
                for profile in profiles:
                    name = profile['UserProfileName']
                    logging.info(f"[{region}] Deleting SageMaker user profile {name}")
                    if not self.config.dry_run:
                        success = retry_delete(
                            lambda d=domain_id, n=name: client.delete_user_profile(DomainId=d, UserProfileName=n),
                            f"Delete SageMaker user profile {name}"
                        )
                        self._record_result('SageMaker User Profiles', f"{name} ({region})", success)
        except ClientError as e:
            logging.error(f"[{region}] Error listing SageMaker user profiles: {e}")
    
    def _delete_domains(self, client, region):
        try:
            domains = client.list_domains()['Domains']
            for domain in domains:
                domain_id = domain['DomainId']
                logging.info(f"[{region}] Deleting SageMaker domain {domain_id}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda d=domain_id: client.delete_domain(
                            DomainId=d,
                            RetentionPolicy={'HomeEfsFileSystem': 'Delete'}
                        ),
                        f"Delete SageMaker domain {domain_id}"
                    )
                    self._record_result('SageMaker Domains', f"{domain_id} ({region})", success)
                else:
                    logging.info(f"[Dry-Run] Would delete SageMaker domain {domain_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error listing SageMaker domains: {e}")
