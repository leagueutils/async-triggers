# Changelog

This page contains a fairly detailed, fairly complete, fairly readable summary of what changed with each version of the
library.

## v1.1.1
Fixed a behaviour where if a trigger with `iter_args` was stopped by raising `triggers.StopRunning()`, the error handler
would be invoked.

## v1.1.0
This release adds:
- an execution limit for triggers. By specifying the `max_trigger_count` parameter, a trigger can be instructed to
  terminate after a certain number of executions.
- a way to dynamically terminate trigger execution from within the decorated function. By raising
 `triggers.StopRunning()`, the containing trigger will be instructed to exit after finishing the current iteration.
- a `ScheduledTrigger` class that allows triggers to run on one or more predefined dates.
- a  programmatic interface (`triggers.apply_trigger()`) to schedule triggers at runtime

## v1.0.0
Initial spin-off from [coc.py](https://github.com/mathsman5133/coc.py). Already comes with an `IntervalTrigger` and a
`CronTrigger`, error handling, logging and a framework for extension.
