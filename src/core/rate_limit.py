import datetime

from pydantic import BaseModel

from src.core import time_utils


class TokenBucketResult(BaseModel):
    allowed: bool
    retry_in: int
    new_tokens: int
    new_last_reset: datetime.datetime


class TokenBucketRateLimiter:
    """
    Pure algorithmic implementation of a Token Bucket rate limiter.
    This class handles NO persistence or IO. It only performs the math.
    """

    def __init__(self, max_tokens: int = 5000000, window_seconds: int = 60):
        self.max_tokens = max_tokens
        self.window_seconds = window_seconds

    def evaluate(
        self,
        current_tokens: int,
        last_reset: datetime.datetime,
        required_tokens: int,
    ) -> TokenBucketResult:
        """
        Evaluates a request against the token bucket mathematically.

        Args:
            current_tokens (int): The tokens currently in the bucket before evaluation.
            last_reset (datetime.datetime): The timestamp when the bucket was last refilled.
            required_tokens (int): The tokens required for the current operation.

        Returns:
            TokenBucketResult: A structured result indicating if the operation is allowed,
                               when to retry if not, and the new state of the bucket.
        """
        # 1. Refill the bucket if the window has expired
        if time_utils.has_window_expired(last_reset, self.window_seconds):
            current_tokens = self.max_tokens
            last_reset = datetime.datetime.now(datetime.UTC)

        # 2. Check if we have enough tokens
        if current_tokens >= required_tokens:
            return TokenBucketResult(
                allowed=True,
                retry_in=0,
                new_tokens=current_tokens - required_tokens,
                new_last_reset=last_reset,
            )
        else:
            retry_in = time_utils.calculate_seconds_until_reset(
                last_reset, self.window_seconds
            )
            return TokenBucketResult(
                allowed=False,
                retry_in=retry_in,
                new_tokens=current_tokens,  # Tokens remain unchanged
                new_last_reset=last_reset,
            )
