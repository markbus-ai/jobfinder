import asyncio
from typing import Optional


class MemoryQueue:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def enqueue(self, chat_id: str, text: str, reply_markup=None):
        """Mete un mensaje en la cola de memoria."""
        message = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup}
        await self.queue.put(message)

    async def dequeue(self) -> Optional[dict]:
        """Saca un mensaje de la cola (blocking get)."""
        return await self.queue.get()
