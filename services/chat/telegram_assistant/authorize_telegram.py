from __future__ import annotations

import asyncio
import getpass

from telethon.errors import SessionPasswordNeededError

from .run_telegram_assistant import build_client


async def main() -> None:
    client = build_client()
    await client.connect()
    try:
        if await client.is_user_authorized():
            print("Telegram session is already authorized.")
            return

        phone = getattr(client, "phone", None)
        if not phone:
            raise RuntimeError("Telegram phone is missing in .env or config.yaml")

        await client.send_code_request(phone)
        code = input("Enter Telegram code: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = getpass.getpass("Enter Telegram 2FA password: ")
            await client.sign_in(password=password)

        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session authorization did not complete")
        print("Telegram session authorized.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
