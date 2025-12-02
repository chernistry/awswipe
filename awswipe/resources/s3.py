import logging
from botocore.exceptions import ClientError
from awswipe.resources.base import ResourceCleaner
from awswipe.core.retry import retry_delete
from awswipe.core.logging import timed

class S3Cleaner(ResourceCleaner):
    @timed
    def cleanup(self, region=None):
        # S3 is global, so we ignore region or only run if it's the "global" pass
        # The original code called delete_s3_buckets_global() once.
        self.delete_s3_buckets_global()

    def delete_s3_buckets_global(self):
        s3 = self.session.client('s3')
        try:
            buckets = s3.list_buckets().get('Buckets', [])
            for bucket in buckets:
                b_name = bucket['Name']
                logging.info('Processing S3 bucket: %s', b_name)
                self._empty_s3_bucket(s3, b_name)
                
                if not self.config.dry_run:
                    success = retry_delete(lambda: s3.delete_bucket(Bucket=b_name), f"Delete S3 Bucket {b_name}")
                    self._record_result('S3 Buckets', b_name, success, '' if success else 'Cannot delete bucket; may require MFA')
                else:
                    logging.info(f"[Dry-Run] Would delete bucket {b_name}")

        except ClientError as e:
            logging.error('Error listing S3 buckets: %s', e)

    def _empty_s3_bucket(self, s3, bucket_name):
        logging.info('Emptying bucket: %s', bucket_name)
        try:
            uploads = s3.list_multipart_uploads(Bucket=bucket_name).get('Uploads', [])
            for upload in uploads:
                key, upload_id = upload['Key'], upload['UploadId']
                if not self.config.dry_run:
                    retry_delete(lambda: s3.abort_multipart_upload(Bucket=bucket_name, Key=key, UploadId=upload_id), f"Abort MPU for {key}")
                else:
                    logging.info(f"[Dry-Run] Would abort MPU for {key}")
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
                    if not self.config.dry_run:
                        success = retry_delete(lambda: s3.delete_objects(Bucket=bucket_name, Delete=del_objs), f"Deleting objects in {bucket_name}")
                        if not success:
                            break
                    else:
                        logging.info(f"[Dry-Run] Would delete {len(batch)} objects in {bucket_name}")
                    objs = objs[1000:]
        except ClientError as e:
            logging.warning('Could not fully list/delete objects in %s: %s', bucket_name, e)
