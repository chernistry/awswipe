import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete

class LambdaCleaner(ResourceCleaner):
    def cleanup(self, region=None):
        self.delete_functions(region)
        self.delete_layers(region)

    def delete_functions(self, region):
        lambda_client = self.session.client('lambda', region_name=region)
        try:
            paginator = lambda_client.get_paginator('list_functions')
            functions = []
            for page in paginator.paginate():
                functions.extend(page['Functions'])
            
            for func in functions:
                f_name = func['FunctionName']
                logging.info(f"[{region}] Deleting Lambda function {f_name}")
                if not self.config.dry_run:
                    success = retry_delete(
                        lambda: lambda_client.delete_function(FunctionName=f_name),
                        f"Delete Lambda function {f_name}"
                    )
                    self._record_result('Lambda Functions', f_name, success)
                else:
                    logging.info(f"[Dry-Run] Would delete Lambda function {f_name}")
        except ClientError as e:
            logging.error(f"[{region}] Error deleting Lambda functions: {e}")

    def delete_layers(self, region):
        client = self.session.client('lambda', region_name=region)
        try:
            layers = []
            paginator = client.get_paginator('list_layers')
            for page in paginator.paginate():
                layers.extend(page['Layers'])
            
            if not layers:
                return

            if self.config.dry_run:
                for layer in layers:
                    logging.info(f"[Dry-Run] Would delete Lambda layer {layer['LayerName']}")
                return

            # Parallel deletion for layers as there can be many versions
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(
                    self._delete_layer_version, client, layer, region
                ) for layer in layers]
                
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        logging.error(f"[{region}] Error deleting layer: {e}")
        except ClientError as e:
            logging.error(f"[{region}] Error listing Lambda layers: {e}")

    def _delete_layer_version(self, client, layer, region):
        layer_name = layer['LayerName']
        version = layer['LatestMatchingVersion']['VersionNumber']
        logging.info(f"[{region}] Deleting Lambda layer {layer_name} version {version}")
        try:
            client.delete_layer_version(LayerName=layer_name, VersionNumber=version)
            self._record_result('Lambda Layers', f"{layer_name}:{version}", True)
        except ClientError as e:
            logging.error(f"[{region}] Error deleting layer {layer_name}: {e}")
            self._record_result('Lambda Layers', f"{layer_name}:{version}", False, str(e))
