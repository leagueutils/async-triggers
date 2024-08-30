import asyncio
import datetime
import logging

from triggers import IntervalTrigger, ScheduledTrigger, apply_trigger, start_triggers

event_loop = asyncio.get_event_loop()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
_logger = logging.getLogger()


async def target_function():
    print('I was called')


async def target_with_arg(argument):
    print(f'The argument is {argument}')


if __name__ == '__main__':
    try:
        # define a few triggers
        trigger = IntervalTrigger(seconds=3, max_trigger_count=3, logger=_logger, autostart=True)
        schedule = ScheduledTrigger(
            run_times=[datetime.datetime.now().astimezone() + datetime.timedelta(seconds=7)],
            iter_args=['Foo', 'Bar'],
            logger=_logger,
        )

        # and programmatically apply them to a function
        apply_trigger(target_function, trigger)
        apply_trigger(target_with_arg, schedule)

        # then start trigger execution
        event_loop.run_until_complete(start_triggers())

        # set the loop to run forever so that it keeps executing the triggers
        # NOTE: this line is blocking, no code after will be executed
        event_loop.run_forever()
        print('This line will never make it to your console')
    except KeyboardInterrupt:
        pass
