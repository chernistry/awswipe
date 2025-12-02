"""AWSwipe CLI entry point."""
import argparse
import logging
import time
from awswipe.core.config import load_config
from awswipe.core.logging import setup_logging, get_run_id
from awswipe.cleaner import SuperAWSResourceCleaner


def parse_args():
    parser = argparse.ArgumentParser(description='AWSwipe - AWS Resource Cleanup Tool')
    parser.add_argument('--config', '-c', help='Path to YAML config file')
    parser.add_argument('--region', help='Region to clean (overrides config)')
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Verbosity: -v=INFO, -vv=DEBUG')
    parser.add_argument('--json-logs', action='store_true',
                        help='Output logs in JSON format')
    parser.add_argument('--live-run', action='store_true',
                        help='Actually delete resources (default: dry-run)')
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Load config from file or defaults
    config = load_config(args.config)
    
    # CLI args override config
    if args.region:
        config.regions = [args.region]
    if args.verbose:
        config.verbosity = args.verbose
    if args.json_logs:
        config.json_logs = True
    if args.live_run:
        config.dry_run = False
    
    setup_logging(config.verbosity, config.json_logs)
    logging.info(f"AWSwipe run_id={get_run_id()} dry_run={config.dry_run}")
    
    cleaner = SuperAWSResourceCleaner(config)
    
    if not config.dry_run:
        logging.warning("LIVE RUN MODE - Resources WILL be deleted")
        try:
            for i in range(5, 0, -1):
                print(f"Starting in {i}s... (Ctrl+C to cancel)", end='\r')
                time.sleep(1)
            print(" " * 40, end='\r')
        except KeyboardInterrupt:
            logging.info("Cancelled by user")
            return
    
    cleaner.purge_aws()


if __name__ == '__main__':
    main()
