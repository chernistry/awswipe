import time
import random
import logging
from botocore.exceptions import ClientError

SLEEP_SHORT = 2
SLEEP_MEDIUM = 5
SLEEP_LONG = 10
SLEEP_EXTRA_LONG = 30

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
