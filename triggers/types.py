from typing import Any, Callable, Coroutine

# async def ... function types
CoroFunction = Callable[..., Coroutine[Any, Any, Any]]
ErrorHandler = Callable[[str, Any, Exception], Coroutine[Any, Any, Any]]
