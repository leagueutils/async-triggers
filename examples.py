import asyncio
import logging

from triggers import CronSchedule, CronTrigger, IntervalTrigger, on_error, start_triggers


cron = CronSchedule('0 0 * * *')
event_loop = asyncio.get_event_loop()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
_logger = logging.getLogger()


@on_error()
async def default_error_handler(function_name, arg, exception):
    print('Default handler:', function_name, arg, exception)


async def special_error_handler(function_name, arg, exception):
    print('Special handler:', function_name, arg, exception)


@CronTrigger(cron_schedule='0 0 * * 5', iter_args=['Foo', 'Bar'], on_startup=False, loop=event_loop, logger=_logger)
async def example_trigger_1(iter_arg):
    """This trigger showcases the `on_startup=False` option and the use of `iter_args`"""

    print(f'Hello from inside the first example trigger function. The value is {iter_arg}')


@CronTrigger(cron_schedule=cron, iter_args=['Baz'], loop=event_loop, logger=_logger)
async def example_trigger_2(some_variable_name):
    """This trigger showcases the use of a `CronSchedule` object and `iter_args`"""

    print(f'Hello from the second example trigger. The value is {some_variable_name}')


@IntervalTrigger.hourly(loop=event_loop, logger=_logger, error_handler=special_error_handler)
async def test_special_error_handling():
    """This trigger showcases the convenience class methods and the use of a dedicated error handler"""

    print('This is about to fail in a very special way')
    return 1/0


@IntervalTrigger(seconds=10, iter_args=[1, 0], autostart=True, loop=event_loop, logger=_logger)
async def test_default_error_handling(divisor: int):
    """This trigger demonstrates the use of `autostart=True` (this is fine because it has no dependencies
    on other resources) in combination with `iter_args` and the default error handler defined by @on_error.
    It also is the trigger with the lowest repeat timer to showcase the fact that triggers indeed do repeat
    """

    print('We are safe' if divisor != 0 else 'Boom')
    return 2/divisor


if __name__ == "__main__":
    try:
        # wait a few seconds to simulate other resources loading
        event_loop.run_until_complete(asyncio.sleep(3))

        # note how this print statement will show up in your console AFTER the auto-started trigger fired
        print('NOTE: Auto-started trigger "test_default_error_handling" has already fired at this point')

        # then start trigger execution
        event_loop.run_until_complete(start_triggers())

        # set the loop to run forever so that it keeps executing the triggers
        # NOTE: this line is blocking, no code after will be executed
        event_loop.run_forever()
        print('This line will never make it to your console')
    except KeyboardInterrupt:
        pass
