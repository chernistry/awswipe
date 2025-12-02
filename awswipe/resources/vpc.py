import logging
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete, SLEEP_SHORT
import time

class VPCCleaner(ResourceCleaner):
    @property
    def prerequisites(self):
        # VPC should be cleaned last, after all resources that might use ENIs
        return ['ec2', 'ebs', 'lambda', 'elb', 'asg', 'rds', 'elasticache', 'efs']

    def cleanup(self, region=None):
        self.delete_nat_gateways(region)
        self.delete_internet_gateways(region)
        self.delete_vpc_endpoints(region)
        self.delete_peering_connections(region)
        self.delete_subnets(region)
        self.delete_route_tables(region)
        self.delete_network_acls(region)
        self.delete_security_groups(region)
        self.delete_vpcs(region)

    def delete_nat_gateways(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            nats = ec2.describe_nat_gateways(Filters=[{'Name': 'state', 'Values': ['available', 'failed']}]).get('NatGateways', [])
            for nat in nats:
                nat_id = nat['NatGatewayId']
                logging.info(f"[{region}] Deleting NAT Gateway {nat_id}")
                if not self.config.dry_run:
                    retry_delete(lambda: ec2.delete_nat_gateway(NatGatewayId=nat_id), f"Delete NAT {nat_id}")
                    self._record_result('NAT Gateways', nat_id, True)
                else:
                    logging.info(f"[Dry-Run] Would delete NAT Gateway {nat_id}")
            
            # Wait for deletion if not dry run
            if nats and not self.config.dry_run:
                logging.info(f"[{region}] Waiting for NAT Gateways to delete...")
                time.sleep(SLEEP_SHORT * 2) # Simple wait, ideally use waiter
        except ClientError as e:
            logging.error(f"[{region}] Error deleting NAT Gateways: {e}")

    def delete_internet_gateways(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            igws = ec2.describe_internet_gateways().get('InternetGateways', [])
            for igw in igws:
                igw_id = igw['InternetGatewayId']
                for att in igw.get('Attachments', []):
                    vpc_id = att['VpcId']
                    logging.info(f"[{region}] Detaching IGW {igw_id} from {vpc_id}")
                    if not self.config.dry_run:
                        retry_delete(lambda: ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id), f"Detach IGW {igw_id}")
                    else:
                        logging.info(f"[Dry-Run] Would detach IGW {igw_id}")
                
                logging.info(f"[{region}] Deleting IGW {igw_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ec2.delete_internet_gateway(InternetGatewayId=igw_id), f"Delete IGW {igw_id}")
                    self._record_result('Internet Gateways', igw_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete IGW {igw_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Internet Gateways: {e}")

    def delete_vpc_endpoints(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            eps = ec2.describe_vpc_endpoints().get('VpcEndpoints', [])
            if not eps:
                return
            ep_ids = [ep['VpcEndpointId'] for ep in eps]
            logging.info(f"[{region}] Deleting VPC Endpoints: {ep_ids}")
            if not self.config.dry_run:
                success = retry_delete(lambda: ec2.delete_vpc_endpoints(VpcEndpointIds=ep_ids), f"Delete VPC Endpoints {ep_ids}")
                for ep_id in ep_ids:
                    self._record_result('VPC Endpoints', ep_id, success)
            else:
                logging.info(f"[Dry-Run] Would delete VPC Endpoints {ep_ids}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting VPC Endpoints: {e}")

    def delete_peering_connections(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            pcxs = ec2.describe_vpc_peering_connections().get('VpcPeeringConnections', [])
            for pcx in pcxs:
                pcx_id = pcx['VpcPeeringConnectionId']
                logging.info(f"[{region}] Deleting VPC Peering Connection {pcx_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ec2.delete_vpc_peering_connection(VpcPeeringConnectionId=pcx_id), f"Delete Peering {pcx_id}")
                    self._record_result('VPC Peering Connections', pcx_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete VPC Peering Connection {pcx_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting VPC Peering Connections: {e}")

    def delete_subnets(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            subnets = ec2.describe_subnets().get('Subnets', [])
            for subnet in subnets:
                sn_id = subnet['SubnetId']
                logging.info(f"[{region}] Deleting Subnet {sn_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ec2.delete_subnet(SubnetId=sn_id), f"Delete Subnet {sn_id}")
                    self._record_result('Subnets', sn_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Subnet {sn_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Subnets: {e}")

    def delete_route_tables(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            rts = ec2.describe_route_tables().get('RouteTables', [])
            for rt in rts:
                rt_id = rt['RouteTableId']
                # Skip main route tables
                is_main = any(assoc.get('Main', False) for assoc in rt.get('Associations', []))
                if is_main:
                    continue
                
                # Delete associations first
                for assoc in rt.get('Associations', []):
                    if not assoc.get('Main', False):
                        assoc_id = assoc['RouteTableAssociationId']
                        if not self.config.dry_run:
                            retry_delete(lambda: ec2.disassociate_route_table(AssociationId=assoc_id), f"Disassociate RT {rt_id}")
                        else:
                            logging.info(f"[Dry-Run] Would disassociate RT {rt_id}")

                logging.info(f"[{region}] Deleting Route Table {rt_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ec2.delete_route_table(RouteTableId=rt_id), f"Delete RT {rt_id}")
                    self._record_result('Route Tables', rt_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Route Table {rt_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Route Tables: {e}")

    def delete_network_acls(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            nacls = ec2.describe_network_acls().get('NetworkAcls', [])
            for nacl in nacls:
                nacl_id = nacl['NetworkAclId']
                if nacl['IsDefault']:
                    continue
                logging.info(f"[{region}] Deleting Network ACL {nacl_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ec2.delete_network_acl(NetworkAclId=nacl_id), f"Delete NACL {nacl_id}")
                    self._record_result('Network ACLs', nacl_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Network ACL {nacl_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Network ACLs: {e}")

    def delete_security_groups(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            sgs = ec2.describe_security_groups().get('SecurityGroups', [])
            # First pass: remove all ingress/egress rules to break dependencies
            for sg in sgs:
                sg_id = sg['GroupId']
                if sg['GroupName'] == 'default':
                    continue
                
                if not self.config.dry_run:
                    if sg.get('IpPermissions'):
                        retry_delete(lambda: ec2.revoke_security_group_ingress(GroupId=sg_id, IpPermissions=sg['IpPermissions']), f"Revoke ingress {sg_id}")
                    if sg.get('IpPermissionsEgress'):
                        retry_delete(lambda: ec2.revoke_security_group_egress(GroupId=sg_id, IpPermissions=sg['IpPermissionsEgress']), f"Revoke egress {sg_id}")
                else:
                    logging.info(f"[Dry-Run] Would revoke rules for SG {sg_id}")

            # Second pass: delete groups
            for sg in sgs:
                sg_id = sg['GroupId']
                if sg['GroupName'] == 'default':
                    continue
                logging.info(f"[{region}] Deleting Security Group {sg_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ec2.delete_security_group(GroupId=sg_id), f"Delete SG {sg_id}")
                    self._record_result('Security Groups', sg_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Security Group {sg_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Security Groups: {e}")

    def delete_vpcs(self, region):
        ec2 = self.session.client('ec2', region_name=region)
        try:
            vpcs = ec2.describe_vpcs().get('Vpcs', [])
            for vpc in vpcs:
                vpc_id = vpc['VpcId']
                if vpc['IsDefault']:
                    continue # Skip default VPC for now, or make it configurable
                logging.info(f"[{region}] Deleting VPC {vpc_id}")
                if not self.config.dry_run:
                    success = retry_delete(lambda: ec2.delete_vpc(VpcId=vpc_id), f"Delete VPC {vpc_id}")
                    self._record_result('VPCs', vpc_id, success)
                else:
                    logging.info(f"[Dry-Run] Would delete VPC {vpc_id}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting VPCs: {e}")
