import asyncio
import json
from typing import Optional

class MemoryQueue:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def enqueue(self, chat_id: str, text: str):
        """Mete un mensaje en la cola de memoria."""
        message = {"chat_id": chat_id, "text": text}
        await self.queue.put(message)

    async def dequeue(self) -> Optional[dict]:
        """Saca un mensaje de la cola (blocking get)."""
        # get() bloquea de forma asíncrona hasta que haya un item
        return await self.queue.get()
