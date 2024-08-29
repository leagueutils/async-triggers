# Async Triggers

## Disclaimer
This library originated as an extension for [coc.py](https://github.com/mathsman5133/coc.py). I decided to spin it
off into a standalone lib because I want to use the scheduling capabilities without adding a bunch of other
dependencies to my projects.

## Overview

Repetition and scheduling are incredibly important, but often enough, you'll find yourself needing to do some simple
repetition logic, and employing the use of `APScheduler` or similar modules feels excessive for the job. That is
where this library comes into play.

It provides you with powerful and easy to use decorators that turn your coroutines into periodically repeating tasks
without the need for any additional modifications. It is as simple as putting a trigger decorator on your existing
coroutine functions. The library comes with:

- two types of triggers: `IntervalTrigger`  and `CronTrigger`,
- customisable error handlers for each trigger and a global `@on_error()` fallback handler,
- extensive logging that can seamlessly be integrated with your existing logger,
- integrated tools to apply your repeating function across an iterable, and
- a framework that is easy to extend, allowing you to create your own custom triggers if you need to.

## API Reference

### IntervalTrigger

The `IntervalTrigger` class will continuously loop the decorated function, sleeping for a defined number of seconds
between executions. For convenience, this trigger defines ``.hourly()``  and ``.daily()`` class methods to instantiate
triggers with a sleep time of 1 hour and 24 hours, respectively.

### CronTrigger

The `CronTrigger` class allows you to specify a standard dialect Cron schedule string to dictate the trigger's
executions. The full Cron dialect (except named aliases for months (e.g. Jan, Feb, ...) and weekdays (e.g. Mon, Tue,
...)) is supported, allowing you to specify highly specialised schedules. For convenience, a set of class methods to
instantiate triggers with common patters have been provided:

- `hourly()` implements the `0 * * * *` schedule,
- `daily()` implements `0 0 * * *`,
- `weekly()` implements `0 0 * * 0`, and
- `monthly()` implements `0 0 1 * *`.

### Starting the Triggers

By default, triggers don't start on their own. This is because you typically want to load other resources before
running a trigger, e.g. booting up a database connection. If a trigger fired right away, the initial runs would
likely fail due to unavailability of these resources (due to how Python works, a trigger would run the moment the
interpreter reaches the definition, usually well before you intend to actually start). This can be seen illustrated in
the examples as well. That is why by default, all triggers are  set to `autostart=False`.

The library provides a `start_triggers()` function to manually kick off trigger execution from within your code once
you're ready to start processing. If you don't need any additional resources to load in first or have otherwise made
sure that your triggers won't fire early, you can set them to `autostart=True` and omit the call to `start_triggers()`.
If you have a mixture of auto-started and not auto-started triggers, `start_triggers()` will only start the ones that
aren't already running.

### Error Handling

The library offers two ways to deal with error handling:

- passing a handler function directly to the trigger's `error_handler` parameter. This allows you to specify
  individual error handlers for each repeated task if you need to.
- designating a global error handler by decorating a function with `on_error()`. This will be used
  as a fallback by all triggers that don't have a dedicated error handler passed to them during initialisation.

An error handler function must be defined with `async def` and accept three parameters in the following order:

- a function_name string. The name of the failing trigger's decorated function will be passed to this parameter.
- an arg of arbitrary type (defined by what is passed to the trigger's iter_args parameter). The failing element of
  the trigger's iter_args will be passed to this argument, if any are defined. Otherwise, this parameter will receive
  `None`.
- an exception. This parameter will be passed the exception that occurred during the execution of the trigger.

Additional arguments can statically be passed to the error handler making use of ``functools.partial``, if needed.

### Logging

Each trigger can be provided with a class implementing the `logging.Logger` functionality. If set, the logger will
receive the following events:

- **info**: trigger execution starts and finishes, along with the next scheduled run times.
- **warning**: if a trigger missed it's next scheduled run time.
- **error**: if an exception occurs during the execution of a trigger. If both a logger and an error handler are set
  up, both will receive information about this event.

### Other Parameters

Triggers allow you to specify a list of elements you want the decorated function to be spread over. If you specify
the `iter_args` parameter when initialising a trigger, it will call the decorated function once for each element of
that parameter. Each element will be positionally passed into the function's first argument. If you prefer to keep
your logic inside the function or load it from somewhere else, simply don't pass the `iter_args` parameter. That will
let the trigger know not to inject any positional args.

The boolean `on_startup` flag allows you to control the trigger behaviour on startup. If it is set to `True`, the
trigger will fire immediately and resume its predefined schedule afterward. If `on_startup` is `False`, the trigger
will remain dormant until its first scheduled run time.

The `autostart` option allows you to decide whether a trigger should automatically start on application startup.
If autostart is disabled, triggers can be started using`start_triggers()` once all dependencies and required resources
are loaded. Refer to the "Starting the Triggers" section for details.

The `loop` parameter allows you to pass your own asyncio event loop to attach the trigger execution to. If omitted,
the current event loop will be used.

You can also specify additional key word arguments (`**kwargs`). Any extra arguments will be passed to the decorated
function as key word arguments on each call.

### Examples
The [examples.py](https://github.com/leagueutils/async-triggers/blob/main/examples.py) file has usage examples


### Extending this Extension

If you find yourself in need of scheduling logic that none of the included triggers can provide, you can easily
create a trigger class that fits your needs by importing the `BaseTrigger` from this extension, creating a
subclass and overwriting the `next_run`  property. The property needs to return a *timezone-aware*
`datetime.datetime` object indicating when the trigger should run next based on the current system time.


```python3
import asyncio
import logging
from datetime import datetime, timedelta
from random import randint
from triggers import BaseTrigger, types
from typing import Optional

class RandomTrigger(BaseTrigger):
   def __init__(self,
                *,  # disable positional arguments
                min_seconds: int,
                max_seconds: int,
                iter_args: Optional[list] = None,
                on_startup: bool = True,
                autostart: bool = False,
                error_handler: Optional[types.CoroFunction] = None,
                logger: Optional[logging.Logger] = None,
                loop: Optional[asyncio.AbstractEventLoop] = None,
                **kwargs):

       super().__init__(iter_args=iter_args, on_startup=on_startup, autostart=autostart,
                        error_handler=error_handler, logger=logger, loop=loop, **kwargs)
       self.min_seconds = min_seconds
       self.max_seconds = max_seconds

   @property
   def next_run(self) -> datetime:
       """randomly triggers every X to Y seconds"""
       return datetime.now().astimezone() + timedelta(seconds=randint(self.min_seconds, self.max_seconds))
```
