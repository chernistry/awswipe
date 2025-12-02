import logging
import time
import functools

def setup_logging(verbose_level=0):
    if verbose_level >= 2:
        level = logging.DEBUG
    elif verbose_level == 1:
        level = logging.INFO
    else:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        logging.info(f"{func.__name__} took {elapsed:.2f} seconds")
        return result
    return wrapper
