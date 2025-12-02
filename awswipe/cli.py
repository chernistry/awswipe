import argparse
import logging
import time
from awswipe.core.config import Config
from awswipe.core.logging import setup_logging
from awswipe.cleaner import SuperAWSResourceCleaner

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
    setup_logging(args.verbose)
    
    config = Config(
        region=args.region,
        dry_run=not args.live_run,
        verbose=args.verbose
    )
    
    cleaner = SuperAWSResourceCleaner(config)
    
    if not config.dry_run:
        logging.warning("--- LIVE RUN MODE ENABLED --- Resources WILL be deleted. --- ")
        try:
            for i in range(5, 0, -1):
                print(f"Starting deletion in {i} seconds... (Ctrl+C to cancel)", end='\r')
                time.sleep(1)
            print("                                                          ", end='\r') 
        except KeyboardInterrupt:
            logging.info("Live run cancelled by user.")
            return
    
    cleaner.purge_aws()

if __name__ == '__main__':
    main()
