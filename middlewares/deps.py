from aiogram.dispatcher.middlewares.base import BaseMiddleware
from typing import Callable, Awaitable, Dict, Any


class DependencyMiddleware(BaseMiddleware):
    def __init__(self, **deps):
        super().__init__()
        self.deps = deps

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        data.update(self.deps)
        return await handler(event, data)
