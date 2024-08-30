import functools
from typing import Any, Callable, Optional

from .types import ErrorHandler

default_error_handler: Optional[ErrorHandler] = None  # target for the @on_error() decorator


class StopRunning(Exception):
    """An exception that signals to the trigger that it should stop repeating the decorated function"""

    pass


def on_error() -> Callable[[ErrorHandler], ErrorHandler]:
    """A decorator function that designates a function as the global fallback error handler for all exceptions
    during trigger executions.

    :returns: the decorated handler function

    Notes
    -----
    This handler declaration should occur before any trigger declarations to avoid a RuntimeWarning about a
    potentially undeclared error handler, though that warning can safely be ignored.

    Any function decorated by this must be a coroutine and accept three parameters:

        function_name: :class:`str`
            the name of the failing trigger's decorated function
        arg: Optional[:class:`Any`]
            the failing `iter_args` element or None if no iter_args are defined
        exception: :class:`Exception`
            the exception that occurred

    Example
    --------
        @on_error()
        async def handle_trigger_exception(function_name: str, arg: Any, exception: Exception):
            # log the error, do some data cleanup, ...
            pass

    """

    def wrapper(func: ErrorHandler):
        # register the error handler
        global default_error_handler
        default_error_handler = func

        @functools.wraps(func)
        async def wrapped(function_name: str, arg: Any, error: Exception):
            await func(function_name, arg, error)

        return wrapped

    return wrapper


def get_default_handler():
    """Utility function to get the default error handler defined in this file. If default_error_handler were
    imported directly, it would always be None, no matter what assignments happen later
    """

    return default_error_handler
