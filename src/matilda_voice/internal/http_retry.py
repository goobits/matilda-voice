"""HTTP retry and circuit breaker utilities for TTS providers.

This module provides retry logic for HTTP requests to external APIs:
- Exponential backoff with jitter
- Configurable retry limits and status codes
- Circuit breaker pattern (optional, for future use)
- Safe defaults to avoid duplicate charges on non-idempotent endpoints
"""

import contextlib
import logging
import random
import threading
import time
from typing import Any, Callable, Iterable, Iterator, Optional, Set, Tuple, Type

import httpx

from ..exceptions import NetworkError, ProviderError

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_BACKOFF_FACTOR = 2.0

# HTTP status codes that should trigger a retry
RETRYABLE_STATUS_CODES: Set[int] = {
    429,  # Too Many Requests (rate limit)
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
}

# HTTP status codes that indicate quota/billing issues (don't retry)
QUOTA_STATUS_CODES: Set[int] = {
    402,  # Payment Required
    403,  # Forbidden (often quota exceeded)
}

# HTTP status codes that are client errors (don't retry, will never succeed)
NON_RETRYABLE_CLIENT_CODES: Set[int] = {
    400,  # Bad Request
    401,  # Unauthorized
    404,  # Not Found
    405,  # Method Not Allowed
    406,  # Not Acceptable
    410,  # Gone
    422,  # Unprocessable Entity
}


def calculate_backoff(
    attempt: int,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
) -> float:
    """Calculate exponential backoff delay with jitter.

    Args:
        attempt: The current attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap in seconds
        backoff_factor: Multiplier for exponential growth

    Returns:
        Delay in seconds with added jitter
    """
    delay = min(base_delay * (backoff_factor**attempt), max_delay)
    # Add jitter (±25% of delay)
    jitter = delay * 0.25 * (2 * random.random() - 1)
    return max(0.1, delay + jitter)


def should_retry(status_code: int) -> Tuple[bool, Optional[str]]:
    """Determine if a request should be retried based on status code.

    Args:
        status_code: HTTP status code

    Returns:
        Tuple of (should_retry, reason)
    """
    if status_code in RETRYABLE_STATUS_CODES:
        return True, f"HTTP {status_code} is retryable"

    if status_code in QUOTA_STATUS_CODES:
        return False, f"HTTP {status_code} indicates quota/billing issue"

    if status_code in NON_RETRYABLE_CLIENT_CODES:
        return False, f"HTTP {status_code} is a client error (won't succeed on retry)"

    if 200 <= status_code < 300:
        return False, "Success"

    # Unknown status codes: be conservative, don't retry
    return False, f"HTTP {status_code} - unknown, not retrying"


def request_with_retry(
    method: str,
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    idempotent: bool = True,
    provider_name: str = "API",
    **kwargs: Any,
) -> httpx.Response:
    """Make an HTTP request with retry logic.

    This function wraps httpx.request with automatic retries for transient failures.
    It uses exponential backoff with jitter to avoid thundering herd problems.

    Args:
        method: HTTP method (GET, POST, etc.)
        url: Request URL
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay between retries in seconds (default: 1.0)
        max_delay: Maximum delay cap in seconds (default: 30.0)
        backoff_factor: Multiplier for exponential backoff (default: 2.0)
        idempotent: If False, only retry on connection errors, not HTTP errors.
                   This prevents duplicate charges on non-idempotent endpoints.
        provider_name: Name of the provider for logging
        **kwargs: Additional arguments passed to httpx.request

    Returns:
        httpx.Response object

    Raises:
        NetworkError: If all retries are exhausted due to connection errors
        QuotaError: If quota/billing error is encountered
        ProviderError: If a non-retryable HTTP error occurs

    Example:
        response = request_with_retry(
            "POST",
            "https://api.example.com/tts",
            json={"text": "Hello"},
            headers={"Authorization": "Bearer xxx"},
            idempotent=False,  # TTS synthesis creates new audio each time
        )
    """
    last_exception: Optional[BaseException] = None
    last_response: Optional[httpx.Response] = None
    breaker = get_circuit_breaker(provider_name)

    effective_retries = 1 if not idempotent else max_retries
    for attempt in range(effective_retries + 1):
        if not breaker.allow_request():
            raise ProviderError(f"{provider_name} circuit breaker is open; request blocked")
        try:
            response = httpx.request(method, url, **kwargs)

            # Check if we should retry based on status code
            retry, reason = should_retry(response.status_code)

            if not retry:
                if 200 <= response.status_code < 300:
                    breaker.record_success()
                # Success or non-retryable error
                return response

            # For non-idempotent requests (like TTS synthesis), don't retry HTTP errors
            # to avoid duplicate charges
            if not idempotent and response.status_code not in {429}:
                logger.warning(f"[{provider_name}] HTTP {response.status_code} on non-idempotent request, not retrying")
                return response

            # Retryable error
            last_response = response
            breaker.record_failure()

            if attempt < max_retries:
                delay = calculate_backoff(attempt, base_delay, max_delay, backoff_factor)
                logger.warning(
                    f"[{provider_name}] {reason}. Attempt {attempt + 1}/{max_retries + 1}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"[{provider_name}] {reason}. All {max_retries + 1} attempts exhausted.")

        except httpx.TimeoutException as e:
            last_exception = e
            breaker.record_failure()
            if attempt < max_retries:
                delay = calculate_backoff(attempt, base_delay, max_delay, backoff_factor)
                logger.warning(
                    f"[{provider_name}] Request timeout. Attempt {attempt + 1}/{max_retries + 1}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"[{provider_name}] Request timeout. All {max_retries + 1} attempts exhausted.")

        except httpx.RequestError as e:
            last_exception = e
            breaker.record_failure()
            if attempt < max_retries:
                delay = calculate_backoff(attempt, base_delay, max_delay, backoff_factor)
                logger.warning(
                    f"[{provider_name}] Network error: {e}. Attempt {attempt + 1}/{max_retries + 1}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"[{provider_name}] Network error: {e}. All {max_retries + 1} attempts exhausted.")

    # All retries exhausted
    if last_exception:
        raise NetworkError(
            f"{provider_name} request failed after {max_retries + 1} attempts: {last_exception}"
        ) from last_exception

    if last_response is not None:
        # Return the last response so caller can handle the error
        return last_response

    # This shouldn't happen, but just in case
    raise NetworkError(f"{provider_name} request failed after {max_retries + 1} attempts")


@contextlib.contextmanager
def stream_with_retry(
    method: str,
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    idempotent: bool = True,
    provider_name: str = "API",
    **kwargs: Any,
) -> Iterator[httpx.Response]:
    """Context manager for streaming HTTP requests with retry logic."""
    last_exception: Optional[BaseException] = None
    breaker = get_circuit_breaker(provider_name)

    for attempt in range(max_retries + 1):
        if not breaker.allow_request():
            raise ProviderError(f"{provider_name} circuit breaker is open; request blocked")
        try:
            with httpx.stream(method, url, **kwargs) as response:
                retry, reason = should_retry(response.status_code)

                if not retry:
                    if 200 <= response.status_code < 300:
                        breaker.record_success()
                    yield response
                    return

                if not idempotent and response.status_code not in {429}:
                    logger.warning(
                        f"[{provider_name}] HTTP {response.status_code} on non-idempotent stream, not retrying"
                    )
                    yield response
                    return

                breaker.record_failure()
                if attempt < max_retries:
                    delay = calculate_backoff(attempt, base_delay, max_delay, backoff_factor)
                    logger.warning(
                        f"[{provider_name}] {reason}. Attempt {attempt + 1}/{max_retries + 1}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    continue

                logger.error(f"[{provider_name}] {reason}. All {max_retries + 1} attempts exhausted.")
                raise NetworkError(f"{provider_name} stream failed after {max_retries + 1} attempts")

        except httpx.TimeoutException as e:
            last_exception = e
            breaker.record_failure()
            if attempt < max_retries:
                delay = calculate_backoff(attempt, base_delay, max_delay, backoff_factor)
                logger.warning(
                    f"[{provider_name}] Stream timeout. Attempt {attempt + 1}/{max_retries + 1}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"[{provider_name}] Stream timeout. All {max_retries + 1} attempts exhausted.")

        except httpx.RequestError as e:
            last_exception = e
            breaker.record_failure()
            if attempt < max_retries:
                delay = calculate_backoff(attempt, base_delay, max_delay, backoff_factor)
                logger.warning(
                    f"[{provider_name}] Stream network error: {e}. Attempt {attempt + 1}/{max_retries + 1}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"[{provider_name}] Stream network error: {e}. All {max_retries + 1} attempts exhausted.")

    if last_exception:
        raise NetworkError(
            f"{provider_name} stream failed after {max_retries + 1} attempts: {last_exception}"
        ) from last_exception

    raise NetworkError(f"{provider_name} stream failed after {max_retries + 1} attempts")


def call_with_retry(
    func: Callable[[], Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    idempotent: bool = True,
    provider_name: str = "API",
    retry_on: Optional[Iterable[Type[BaseException]]] = None,
) -> Any:
    """Call a function with retry + circuit breaker.

    This is for SDK calls that don't expose HTTP status codes.
    """
    last_exception: Optional[BaseException] = None
    breaker = get_circuit_breaker(provider_name)
    retryable = tuple(retry_on) if retry_on is not None else (ConnectionError, TimeoutError)

    for attempt in range(max_retries + 1):
        if not breaker.allow_request():
            raise ProviderError(f"{provider_name} circuit breaker is open; request blocked")

        try:
            result = func()
            breaker.record_success()
            return result
        except retryable as e:
            last_exception = e
            breaker.record_failure()
            if not idempotent and attempt == 0:
                logger.warning(f"[{provider_name}] Non-idempotent call failed ({e}); retrying once.")
            if attempt < max_retries:
                delay = calculate_backoff(attempt, base_delay, max_delay, backoff_factor)
                logger.warning(
                    f"[{provider_name}] Call failed: {e}. Attempt {attempt + 1}/{max_retries + 1}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"[{provider_name}] Call failed: {e}. All {max_retries + 1} attempts exhausted.")
        except Exception as e:
            logger.exception(f"[{provider_name}] Unexpected error during call")
            last_exception = e
            breaker.record_failure()
            raise

    if last_exception:
        raise NetworkError(
            f"{provider_name} call failed after {max_retries + 1} attempts: {last_exception}"
        ) from last_exception

    raise NetworkError(f"{provider_name} call failed after {max_retries + 1} attempts")


class CircuitBreaker:
    """Basic circuit breaker to prevent cascading failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_success_threshold: int = 2,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_success_threshold = half_open_success_threshold
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_successes = 0
        self._state = "closed"
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        """Return True if a request is allowed in the current state."""
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if self._last_failure_time is None:
                    return False
                if (time.time() - self._last_failure_time) >= self._recovery_timeout:
                    self._state = "half_open"
                    self._half_open_successes = 0
                    return True
                return False
            return True

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            if self._state == "half_open":
                self._half_open_successes += 1
                if self._half_open_successes >= self._half_open_success_threshold:
                    self._state = "closed"
                    self._failure_count = 0
                    self._last_failure_time = None
                    self._half_open_successes = 0
            elif self._state == "closed":
                self._failure_count = 0
                self._last_failure_time = None

    def record_failure(self) -> None:
        """Record a failed request."""
        with self._lock:
            if self._state == "half_open":
                self._state = "open"
                self._failure_count = self._failure_threshold
                self._last_failure_time = time.time()
                self._half_open_successes = 0
                return

            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self._failure_threshold:
                self._state = "open"


_circuit_breakers: dict[str, CircuitBreaker] = {}
_circuit_lock = threading.Lock()


def get_circuit_breaker(provider_name: str) -> CircuitBreaker:
    """Get or create a circuit breaker for a provider."""
    with _circuit_lock:
        breaker = _circuit_breakers.get(provider_name)
        if breaker is None:
            breaker = CircuitBreaker()
            _circuit_breakers[provider_name] = breaker
        return breaker
