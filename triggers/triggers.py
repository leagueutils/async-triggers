import asyncio
import datetime
import functools
import logging
import warnings
from abc import ABC, abstractmethod
from traceback import format_exception
from typing import Any, List, Optional, Union

from .cron import CronSchedule
from .exceptions import StopRunning, get_default_handler
from .types import CoroFunction, ErrorHandler

trigger_registry = []  # target for start_triggers()


class BaseTrigger(ABC):
    """
    Abstract base class for all repeating trigger decorators. This class can only be inherited from,
    it cannot be instantiated. Any subclasses have to implement the `next_run` property

    Arguments:

    max_trigger_count:
        an optional integer. If specified, the trigger will exit after it has been called that many times.
        If omitted, the trigger will repeat indefinitely

    iter_args:
        an optional list of arguments. The decorated function will be called once per list element,
        and the element will be passed to the decorated function as the first positional argument

    on_startup:
        whether to trigger a run of the decorated function on startup. Defaults to `True`

    autostart:
        whether to automatically start the trigger. Auto-starting it may cause required components to not
        have fully loaded and initialized. If you choose to disable autostart (which is the default),
        you can use `triggers.start_triggers()` to manually kick the trigger execution off once you
        have loaded all required resources

    error_handler:
        an optional function that will be called on each error incurred during the trigger execution

    logger:
        an optional logger instance implementing the logging.Logger functionality. Debug and error logs
        about the trigger execution will be logged to this logger

    loop:
        an optional event loop that the trigger execution will be appended to. If no loop is provided,
        the trigger will provision one using `asyncio.get_event_loop()`

    kwargs:
        any additional keyword arguments that will be passed to the decorated function every time it is called

    """

    def __init__(
        self,
        *,  # disable positional arguments
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: Optional[bool] = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        if not error_handler and not get_default_handler() and not logger:
            warnings.warn(
                'No logger or error handler are defined. Without either of these components, any errors '
                'raised during the trigger executions will be silently ignored. If you declared a global '
                'error handler using the `@on_error()` decorator, you can safely ignore this warning or '
                'remove it entirely by placing the handler declaration before the trigger declarations',
                category=RuntimeWarning,
                stacklevel=2,
            )

        self.iter_args = iter_args
        self.on_startup = on_startup
        self.autostart = autostart
        self.error_handler = error_handler
        self.logger = logger
        self.loop = loop or asyncio.get_event_loop()
        self.kwargs = kwargs
        self.max_trigger_count = max_trigger_count

        self._trigger_count = 0
        self.task = None  # placeholder for the repeat task created in self.__wrapper

    def __call__(self, func: CoroFunction):
        return self.__wrapper(func)

    def __wrapper(self, func: CoroFunction):
        """The main workhorse. Handles the repetition of the decorated function as well as logging and error handling"""

        # fill any passed kwargs
        fixture = functools.partial(func, **self.kwargs)

        @functools.wraps(fixture)
        async def wrapped() -> None:
            async def inner():
                # maybe wait for next trigger cycle
                if not self.on_startup:
                    next_run = self.next_run
                    if self.logger:
                        self.logger.info(
                            f'`on_startup` is set to `False`. First run of {self.__class__.__name__} for '
                            f'{func.__name__}: {next_run.isoformat()}'
                        )
                    await self.sleep_until(next_run)

                # repeat indefinitely
                while True:
                    if self.logger:
                        self.logger.info(f'Running {self.__class__.__name__} for {func.__name__}')

                    if self.max_trigger_count is not None:
                        self._trigger_count += 1

                    # call the decorated function
                    try:
                        if self.iter_args:
                            results = await asyncio.gather(*map(fixture, self.iter_args), return_exceptions=True)

                            # check for exceptions
                            terminate = False
                            for arg, res in zip(self.iter_args, results):
                                if isinstance(res, StopRunning):
                                    terminate = True
                                if isinstance(res, Exception):
                                    await self.__handle_exception(func, arg, res)
                            if terminate:
                                raise StopRunning()
                        else:
                            await fixture()
                    except StopRunning:
                        if self.logger:
                            self.logger.info(
                                f'{self.__class__.__name__} received StopRunning for {func.__name__}. Terminating'
                            )
                        break
                    except Exception as e:
                        await self.__handle_exception(func, None, e)

                    # stop after the maximum number of triggers has been reached
                    if self.max_trigger_count is not None and self._trigger_count >= self.max_trigger_count:
                        if self.logger:
                            self.logger.info(
                                f'{self.__class__.__name__} has reached the execution limit of {self.max_trigger_count}'
                                f' executions for {func.__name__}. Terminating'
                            )
                        break

                    # sleep until next execution time
                    try:
                        next_run = self.next_run
                    except StopRunning:
                        if self.logger:
                            self.logger.info(
                                f'{self.__class__.__name__} received StopRunning for {func.__name__}. Terminating'
                            )
                        break
                    if self.logger and datetime.datetime.now().astimezone() <= next_run:
                        self.logger.info(
                            f'{self.__class__.__name__} finished for {func.__name__}. Next run: {next_run.isoformat()}'
                        )
                    elif self.logger:  # i.e. next_run is in the past
                        self.logger.warning(
                            f'{self.__class__.__name__} missed the scheduled run time for {func.__name__}. Running now'
                        )

                    await self.sleep_until(next_run)

            # create a reference to the repeating task to prevent it from accidentally being garbage collected
            self.task = self.loop.create_task(inner())

        if self.autostart:  # immediately start the trigger
            if self.logger:
                self.logger.info(f'{self.__class__.__name__} for {func.__name__} auto-started')
            self.loop.create_task(wrapped())
        else:  # add trigger to registry
            trigger_registry.append(wrapped())
            if self.logger:
                self.logger.info(f'{self.__class__.__name__} for {func.__name__} registered for manual start')

        return wrapped

    async def __handle_exception(self, func: CoroFunction, arg: Any, exc: Exception):
        """Handle exceptions during trigger calls. This will attempt to call the provided logger and
        any available error handler

        :param func: the decorated function that caused the exception
        :param arg: the `iter_args` element that was passed to the function on the call
        :param exc: the exception
        :return: None
        """

        if self.logger:
            self.logger.error(
                f'function: {func.__name__}, failing iter_arg: {arg}\n' ''.join(
                    format_exception(type(exc), exc, exc.__traceback__)
                )
            )

        error_handler = self.error_handler or get_default_handler()
        if error_handler:
            await error_handler(func.__name__, arg, exc)

    @staticmethod
    async def sleep_until(wakeup_date: datetime):
        """Sleep until a defined point in time. If that point is in the past, don't sleep at all

        :param wakeup_date: a timezone-aware datetime at which the trigger should wake up again
        """

        await asyncio.sleep(max((wakeup_date - datetime.datetime.now().astimezone()).total_seconds(), 0))

    @property
    @abstractmethod
    def next_run(self) -> datetime.datetime:
        """Calculate the date and time (timezone-aware) of the next run. Needs to be overwritten in subclasses"""
        raise NotImplementedError('All `BaseTrigger` subclasses need to implement `next_run`')


class IntervalTrigger(BaseTrigger):
    """
    A decorator class to repeat a function every `seconds` seconds after the previous execution finishes

    Attributes
    ----------

    seconds:
        how many seconds to wait between trigger runs

    max_trigger_count:
        an optional integer. If specified, the trigger will exit after it has been called that many times.
        If omitted, the trigger will repeat indefinitely

    iter_args:
        an optional list of arguments. The decorated function will be called once per list element,
        and the element will be passed to the decorated function as the first positional argument. If
        no iter_args are defined, nothing (especially not `None`) will be injected into the decorated function

    on_startup:
        whether to trigger a run of the decorated function on startup. Defaults to `True`

    autostart:
        whether to automatically start the trigger. Auto-starting it may cause required components to not
        have fully loaded and initialized. If you choose to disable autostart (which is the default),
        you can use `triggers.start_triggers()` to manually kick the trigger execution off once you
        have loaded all required resources

    error_handler:
        an optional coroutine function that will be called on each error incurred during the trigger execution.
        The handler will receive three arguments:

            function_name: str
                the name of the failing trigger's decorated function
            arg: Optional[Any]
                the failing `iter_args` element or None if no `iter_args` are defined
            exception: Exception
                the exception that occurred

    logger:
        an optional logger instance implementing the logging.Logger functionality. Debug, warning and error logs
        about the trigger execution will be sent to this logger

    loop:
        an optional event loop that the trigger execution will be appended to. If no loop is provided,
        the trigger will provision one using `asyncio.get_event_loop()`

    kwargs:
        any additional keyword arguments that will be passed to the decorated function every time it is called

    Example
    -------
        @IntervalTrigger(seconds=600, iter_args=['Foo', 'Bar'])
        async def do_something(an_argument):
            print(f'The argument is {an_argument}')
    """

    def __init__(
        self,
        *,  # disable positional arguments
        seconds: int,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        super().__init__(
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

        if not isinstance(seconds, int) or seconds <= 0:
            raise ValueError(f'`seconds` must be a positive integer, got {seconds}')
        self._interval_seconds = seconds

    def __str__(self):
        return f'triggers.IntervalTrigger(seconds={self._interval_seconds})'

    @property
    def next_run(self) -> datetime.datetime:
        """Calculate the date and time of the next run based on the current time and the defined interval

        :returns: the next run date (timezone-aware)
        """

        return datetime.datetime.now().astimezone() + datetime.timedelta(seconds=self._interval_seconds)

    @classmethod
    def hourly(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs with a one-hour break between executions"""

        return cls(
            seconds=3600,
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

    @classmethod
    def daily(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs with a 24-hour break between executions"""

        return cls(
            seconds=86400,
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )


class CronTrigger(BaseTrigger):
    """
    A decorator class to repeat a function based on a Cron schedule

    Attributes
    ----------

    cron_schedule:
        the Cron schedule to follow

    max_trigger_count:
        an optional integer. If specified, the trigger will exit after it has been called that many times.
        If omitted, the trigger will repeat indefinitely

    iter_args:
        an optional list of arguments. The decorated function will be called once per list element,
        and the element will be passed to the decorated function as the first positional argument. If
        no iter_args are defined, nothing (especially not `None`) will be injected into the decorated function

    on_startup:
        whether to trigger a run of the decorated function on startup. Defaults to `True`

    autostart:
        whether to automatically start the trigger. Auto-starting it may cause required components to not
        have fully loaded and initialized. If you choose to disable autostart (which is the default),
        you can use `triggers.start_triggers()` to manually kick the trigger execution off once you
        have loaded all required resources

    error_handler:
        an optional coroutine function that will be called on each error incurred during the trigger execution.
        The handler will receive three arguments:

            function_name: str
                the name of the failing trigger's decorated function
            arg: Optional[Any]
                the failing `iter_args` element or None if no iter_args are defined
            exception: Exception
                the exception that occurred

    logger:
        an optional logger instance implementing the logging.Logger functionality. Debug, warning and error logs
        about the trigger execution will be sent to this logger

    loop:
        an optional event loop that the trigger execution will be appended to. If no loop is provided,
        the trigger will provision one using `asyncio.get_event_loop()`

    kwargs:
        any additional keyword arguments that will be passed to the decorated function every time it is called

    Example
    -------

        @CronTrigger(cron_schedule='0 0 * * *', iter_args=['Foo', 'Bar'])
        async def do_something(an_argument):
            print(f'The argument is {an_argument}')
    """

    def __init__(
        self,
        *,  # disable positional arguments
        cron_schedule: Union[CronSchedule, str],
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        super().__init__(
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

        if isinstance(cron_schedule, str):
            cron_schedule = CronSchedule(cron_schedule)
        self.cron_schedule = cron_schedule

    def __str__(self):
        return f'triggers.CronTrigger(cron_schedule="{self.cron_schedule.cron_str}")'

    @property
    def next_run(self) -> datetime.datetime:
        """Calculate the date and time of the next run based on the current time and the defined Cron schedule

        :returns: the next run date (timezone-aware)
        """

        # prevent multiple runs in one minute
        now = datetime.datetime.now().astimezone()
        return self.cron_schedule.next_run_after(now.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1))

    @classmethod
    def hourly(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs at the start of every hour"""

        return cls(
            cron_schedule='0 * * * *',
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

    @classmethod
    def daily(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs at the start of every day"""

        return cls(
            cron_schedule='0 0 * * *',
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

    @classmethod
    def weekly(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs at the start of every week (Sunday at 00:00)"""

        return cls(
            cron_schedule='0 0 * * 0',
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

    @classmethod
    def monthly(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs at the start of every month"""

        return cls(
            cron_schedule='0 0 1 * *',
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )


class ScheduledTrigger(BaseTrigger):
    """
    A decorator class to repeat a function at specified times

    Attributes
    ----------

    run_times:
        one or more timezone-aware `datetime.datetime`s when the trigger should run

    max_trigger_count:
        an optional integer. If specified, the trigger will exit after it has been called that many times.
        If omitted, the trigger will repeat indefinitely

    iter_args:
        an optional list of arguments. The decorated function will be called once per list element,
        and the element will be passed to the decorated function as the first positional argument. If
        no iter_args are defined, nothing (especially not `None`) will be injected into the decorated function

    on_startup:
        whether to trigger a run of the decorated function on startup. Defaults to `True`

    autostart:
        whether to automatically start the trigger. Auto-starting it may cause required components to not
        have fully loaded and initialized. If you choose to disable autostart (which is the default),
        you can use `triggers.start_triggers()` to manually kick the trigger execution off once you
        have loaded all required resources

    error_handler:
        an optional coroutine function that will be called on each error incurred during the trigger execution.
        The handler will receive three arguments:

            function_name: str
                the name of the failing trigger's decorated function
            arg: Optional[Any]
                the failing `iter_args` element or None if no iter_args are defined
            exception: Exception
                the exception that occurred

    logger:
        an optional logger instance implementing the logging.Logger functionality. Debug, warning and error logs
        about the trigger execution will be sent to this logger

    loop:
        an optional event loop that the trigger execution will be appended to. If no loop is provided,
        the trigger will provision one using `asyncio.get_event_loop()`

    kwargs:
        any additional keyword arguments that will be passed to the decorated function every time it is called

    Example
    -------

        @ScheduledTrigger(run_times=datetime.datetime(2025, 1, 1).astimezone(), iter_args=['Foo', 'Bar'])
        async def do_something(an_argument):
            print(f'The argument is {an_argument}')
    """

    def __init__(
        self,
        *,  # disable positional arguments
        run_times: Union[datetime.datetime, List[datetime.datetime]],
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        super().__init__(
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

        if isinstance(run_times, datetime.datetime):
            self.run_times = [run_times]
        else:
            self.run_times = sorted(run_times)

    @property
    def next_run(self) -> datetime.datetime:
        """Return the next scheduled run time from the list defined during init.
        This intentionally doesn't check if the run time is already in the past - the main loop will deal with
        that and log appropriate warnings.

        :returns: the next run date (timezone-aware)
        """

        try:
            return self.run_times.pop(0)
        except IndexError as e:
            raise StopRunning() from e

    @classmethod
    def in_one_hour(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs one hour from the start of the main script"""

        return cls(
            run_times=datetime.datetime.now().astimezone() + datetime.timedelta(hours=1),
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

    @classmethod
    def in_one_day(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs one day from the start of the main script"""

        return cls(
            run_times=datetime.datetime.now().astimezone() + datetime.timedelta(days=1),
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )

    @classmethod
    def tomorrow(
        cls,
        max_trigger_count: Optional[int] = None,
        iter_args: Optional[list] = None,
        on_startup: bool = True,
        autostart: bool = False,
        error_handler: Optional[ErrorHandler] = None,
        logger: Optional[logging.Logger] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
        **kwargs,
    ):
        """A shortcut to create a trigger that runs at the start of the next day"""

        now = datetime.datetime.now().astimezone()
        tomorrow = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return cls(
            run_times=tomorrow,
            max_trigger_count=max_trigger_count,
            iter_args=iter_args,
            on_startup=on_startup,
            autostart=autostart,
            error_handler=error_handler,
            logger=logger,
            loop=loop,
            **kwargs,
        )


async def start_triggers():
    """Manually start all triggers with `autostart=False` (which is the default value)

    Example
    --------
        # define a trigger
        @CronTrigger(cron_schedule='0 0 * * *', iter_args=['Foo', 'Bar], autostart=False)
        async def do_something(a_random_argument: Any):
            print(f'The argument is {a_random_argument}')

        if __name__ = '__main__':
            # load your required resources here
            event_loop = asyncio.get_event_loop()

            # then start trigger execution
            event_loop.run_until_complete(start_triggers())

            # set the loop to run forever so that it keeps executing the triggers
            event_loop.run_forever()
    """

    tasks = [asyncio.create_task(trigger) for trigger in trigger_registry]
    return await asyncio.gather(*tasks)
