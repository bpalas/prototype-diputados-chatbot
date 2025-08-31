import logging
import time
from functools import wraps
from typing import Callable, Iterable, Type


def retry(
    tries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Iterable[Type[Exception]] = (Exception,),
    logger: logging.Logger | None = None,
) -> Callable:
    """Simple retry decorator with exponential backoff.

    Parameters
    ----------
    tries: int
        Number of attempts before raising the exception.
    delay: float
        Initial delay between retries in seconds.
    backoff: float
        Multiplicative factor by which the delay increases after each attempt.
    exceptions: Iterable[Type[Exception]]
        A tuple or list of exception classes that trigger a retry.
    logger: logging.Logger | None
        Optional logger. If None, a module-level logger is used.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            _tries, _delay = tries, delay
            _logger = logger or logging.getLogger(func.__module__)

            while _tries > 1:
                try:
                    return func(*args, **kwargs)
                except tuple(exceptions) as e:
                    _tries -= 1
                    _logger.warning(
                        "%s failed with %s. Retrying in %.1f seconds...", func.__name__, e, _delay
                    )
                    time.sleep(_delay)
                    _delay *= backoff

            # Final attempt
            try:
                return func(*args, **kwargs)
            except tuple(exceptions) as e:
                _logger.error("%s failed after %d attempts: %s", func.__name__, tries, e)
                raise

        return wrapper

    return decorator
