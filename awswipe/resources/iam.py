import logging
import time
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete, SLEEP_SHORT

class IamCleaner(ResourceCleaner):
    def cleanup(self, region=None):
        # IAM is global
        self.delete_all_iam_roles_global()
        self.delete_service_linked_roles_global()

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
                
                if not self.config.dry_run:
                    success = True
                    try:
                        iam.delete_role(RoleName=rname)
                    except ClientError as e:
                        logging.error(f"Error deleting IAM role {rname}: {e}")
                        success = False
                    self._record_result('IAM Roles', rname, success)
                    time.sleep(SLEEP_SHORT)
                else:
                    logging.info(f"[Dry-Run] Would delete IAM role {rname}")

        except ClientError as e:
            logging.error(f"Error listing IAM roles: {e}")

    def _remove_policies_from_role(self, iam, role_name):
        try:
            att_pols = iam.list_attached_role_policies(RoleName=role_name).get('AttachedPolicies', [])
            for p in att_pols:
                p_arn = p['PolicyArn']
                if not self.config.dry_run:
                    retry_delete(lambda: iam.detach_role_policy(RoleName=role_name, PolicyArn=p_arn), f"Detach policy {p_arn} from {role_name}")
                else:
                    logging.info(f"[Dry-Run] Would detach policy {p_arn} from {role_name}")
        except ClientError as e:
            logging.error(f"Error detaching policies from {role_name}: {e}")
        try:
            inlines = iam.list_role_policies(RoleName=role_name).get('PolicyNames', [])
            for pol in inlines:
                if not self.config.dry_run:
                    retry_delete(lambda: iam.delete_role_policy(RoleName=role_name, PolicyName=pol), f"Delete inline policy {pol} from {role_name}")
                else:
                    logging.info(f"[Dry-Run] Would delete inline policy {pol} from {role_name}")
        except ClientError as e:
            logging.error(f"Error removing inline policies from {role_name}: {e}")

    def _remove_role_from_instance_profiles(self, iam, role_name):
        paginator = iam.get_paginator('list_instance_profiles_for_role')
        for page in paginator.paginate(RoleName=role_name):
            profiles = page.get('InstanceProfiles', [])
            for p in profiles:
                p_name = p['InstanceProfileName']
                if not self.config.dry_run:
                    retry_delete(lambda: iam.remove_role_from_instance_profile(InstanceProfileName=p_name, RoleName=role_name), f"Remove {role_name} from {p_name}")
                    success = retry_delete(lambda: iam.delete_instance_profile(InstanceProfileName=p_name), f"Delete instance profile {p_name}")
                    self._record_result('Instance IAM Profiles', p_name, success)
                else:
                    logging.info(f"[Dry-Run] Would remove role from instance profile {p_name} and delete profile")

    def delete_service_linked_roles_global(self):
        iam = self.session.client('iam')
        try:
            roles = iam.list_roles()['Roles']
            for role in roles:
                role_name = role['RoleName']
                if role_name.startswith('AWSServiceRoleFor'):
                    logging.info(f"Deleting service-linked role {role_name}")
                    if not self.config.dry_run:
                        try:
                            iam.delete_service_linked_role(RoleName=role_name)
                            self._record_result('Service-Linked Roles', role_name, True)
                        except ClientError as e:
                            logging.error(f"Error deleting service-linked role {role_name}: {e}")
                            self._record_result('Service-Linked Roles', role_name, False, str(e))
                    else:
                        logging.info(f"[Dry-Run] Would delete service-linked role {role_name}")
        except ClientError as e:
            logging.error(f"Error listing IAM roles for service-linked deletion: {e}")
