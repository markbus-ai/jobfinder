import asyncio
from telegram import Bot
from telegram.constants import ParseMode
from RedisServices import RedisQueue

# Supongamos que esta es tu cola (puede ser Redis, Rabbit o SQS)
message_queue = asyncio.Queue()


async def worker(token: str):
    """
    Este es el proceso que se queda escuchando la cola
    y manda los mensajes a Telegram.
    """
    bot = Bot(token=token)
    message_queue = RedisQueue()
    print("Worker activo: escuchando mensajes en la cola...")

    while True:
        # 1. Espera un mensaje de la cola
        job = await message_queue.dequeue()

        # job debería ser un dict con: chat_id y text
        try:
            await bot.send_message(
                chat_id=job["chat_id"],
                text=job["text"],
                parse_mode=ParseMode.HTML,
            )
            print(f"Mensaje enviado a {job['chat_id']}")
        except Exception as e:
            print(f"Error al enviar: {e}")
        finally:
            # 2. Avisa que el trabajo terminó
            message_queue.task_done()


# Función para simular que algo mete cosas en la cola
async def producer():
    while True:
        await asyncio.sleep(5)
        await message_queue.put(
            {
                "chat_id": "TU_USER_ID",
                "text": "<b>Notificación:</b> Nuevo evento en la cola",
            }
        )


async def main():
    token = "8477475085:AAFJ1p7bmEk5eaE_3iwLmNL-6UvjD6F8qMg"
    # Corremos el worker y el producer (o tu integración con Rabbit/Redis)
    await asyncio.gather(worker(token), producer())


if __name__ == "__main__":
    asyncio.run(main())
