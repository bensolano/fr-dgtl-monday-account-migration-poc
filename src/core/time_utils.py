import datetime
import time


def calculate_exponential_backoff(retry_count: int, base: int = 2) -> float:
    """
    Calculates the absolute Unix timestamp for the next retry using exponential backoff.

    Args:
        retry_count (int): The current number of retries attempted.
        base (int, optional): The base for the exponent. Defaults to 2.

    Returns:
        float: The exact Unix timestamp (time.time() + delay) for the retry.
    """
    delay = base**retry_count
    return time.time() + delay


def calculate_seconds_until_reset(
    last_reset: datetime.datetime, window_seconds: int = 60
) -> int:
    """
    Calculates the remaining seconds until a time window resets.

    Args:
        last_reset (datetime.datetime): The timestamp when the window last reset.
        window_seconds (int, optional): The duration of the window. Defaults to 60.

    Returns:
        int: The number of seconds remaining (minimum 1).
    """
    elapsed = (datetime.datetime.now(datetime.UTC) - last_reset).total_seconds()
    return max(1, int(window_seconds - elapsed))


def has_window_expired(last_reset: datetime.datetime, window_seconds: int = 60) -> bool:
    """
    Checks if the time window has expired.

    Args:
        last_reset (datetime.datetime): The timestamp when the window last reset.
        window_seconds (int, optional): The duration of the window. Defaults to 60.

    Returns:
        bool: True if the window has expired, False otherwise.
    """
    elapsed = (datetime.datetime.now(datetime.UTC) - last_reset).total_seconds()
    return elapsed > window_seconds
