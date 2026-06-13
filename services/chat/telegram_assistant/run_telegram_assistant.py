from __future__ import annotations

import os
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient, events
import yaml

from .api_bridge import LocalAPIBridge
from .archive import build_archive_path, extract_document_text, sha256_file, write_metadata
from .assistant import LawyerTelegramAssistant
from .message_log import append_message_log, build_message_id_reply, text_preview


# parents[0]=telegram_assistant, parents[1]=chat, parents[2]=services, parents[3]=v2
PROJECT_ROOT = Path(__file__).resolve().parents[3]

ROOT_ENV = Path(os.getenv("LEGASVEX_ENV_FILE") or (PROJECT_ROOT / ".env"))
ROOT_CONFIG = Path(os.getenv("LEGASVEX_CONFIG_FILE") or (PROJECT_ROOT / "config.yaml"))


def should_handle_chat(
    chat_title: str,
    chat_id: str,
    allowed_chat: str = "",
    is_private: bool = False,
    allow_private: bool = False,
    allow_all_chats: bool = False,
) -> bool:
    if allow_all_chats:
        return not is_private or allow_private
    allowed = allowed_chat.strip()
    if not allowed:
        return False
    if not (allowed.lstrip("-").isdigit()):
        return False
    if is_private and not allow_private:
        return False
    return allowed == chat_id.strip()


def should_process_outgoing_text(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    assistant_prefixes = (
        "LegasVex AI CRM на связи",
        "LegasVex AI CRM помощник",
        "Демо LegasVex",
        "Я могу ответить",
        "Ключевые риски:",
        "Сроки и нагрузка:",
        "Документ принят",
        "Contract risk scan completed",
        "Demo loaded",
    )
    return not normalized.startswith(assistant_prefixes)


def should_process_new_message_event(is_outgoing: bool) -> bool:
    return not is_outgoing


def build_client() -> TelegramClient:
    load_dotenv(ROOT_ENV)
    config = _load_config()
    api_id_raw = os.getenv("TELEGRAM_API_ID") or config.get("api_id", "")
    api_hash = os.getenv("TELEGRAM_API_HASH") or config.get("api_hash", "")
    phone = os.getenv("TELEGRAM_PHONE") or config.get("phone", "")
    if not api_id_raw or not api_hash or not phone:
        raise RuntimeError("Telegram credentials are missing in .env and config.yaml")
    api_id = int(str(api_id_raw))
    session_dir = Path(os.getenv("LEGASVEX_TELEGRAM_SESSION_DIR") or (PROJECT_ROOT / "demo-data"))
    session_dir.mkdir(parents=True, exist_ok=True)
    session_name = os.getenv("LEGASVEX_TELEGRAM_SESSION_NAME") or config.get("session_name", "lawyer_telegram_assistant")
    session_path = session_dir / session_name
    client = TelegramClient(str(session_path), api_id, api_hash)
    client.phone = phone  # type: ignore[attr-defined]
    return client


def _load_config() -> dict:
    if not ROOT_CONFIG.exists():
        return {}
    payload = yaml.safe_load(ROOT_CONFIG.read_text(encoding="utf-8")) or {}
    return payload.get("telegram", {})


async def main() -> None:
    load_dotenv(ROOT_ENV)
    crm_base = os.getenv("LEGASVEX_CRM_API_BASE", "http://127.0.0.1:8010")
    intake_base = os.getenv("LEGASVEX_INTAKE_API_BASE", "http://127.0.0.1:8011")
    legal_qa_base = os.getenv("LEGASVEX_LEGAL_QA_API_BASE", "http://127.0.0.1:8015")
    tenant_scope = os.getenv("LEGASVEX_TENANT_SCOPE", "demo-collegium")
    allowed_chat = os.getenv("LEGASVEX_TELEGRAM_ALLOWED_CHAT", "").strip()
    allow_private = os.getenv("LEGASVEX_TELEGRAM_ALLOW_PRIVATE", "0").strip() == "1"
    allow_all_chats = (
        os.getenv("LEGASVEX_TELEGRAM_ALLOW_ALL_CHATS", "0").strip() == "1"
        and os.getenv("LEGASVEX_TELEGRAM_UNSAFE_CONFIRM_ALLOW_ALL", "").strip() == "I_ACCEPT_ACCOUNT_WIDE_REPLIES"
    )
    max_upload_mb = int(os.getenv("LEGASVEX_TELEGRAM_MAX_UPLOAD_MB", "20"))
    max_extract_chars = int(os.getenv("LEGASVEX_DOCUMENT_EXTRACT_MAX_CHARS", "12000"))

    bridge = LocalAPIBridge(
        crm_base=crm_base,
        intake_base=intake_base,
        legal_qa_base=legal_qa_base,
        tenant_scope=tenant_scope,
    )
    assistant = LawyerTelegramAssistant(bridge)
    client = build_client()
    ignored_outgoing_message_ids: set[int] = set()

    def log_message_record(
        *,
        chat_id: str,
        message_id: int | str,
        direction: str,
        actor_id: str = "",
        text: str = "",
        reply_to_message_id: int | str | None = None,
    ) -> None:
        append_message_log(
            PROJECT_ROOT,
            {
                "tenant_scope": tenant_scope,
                "chat_id": str(chat_id),
                "message_id": str(message_id),
                "direction": direction,
                "actor_id": actor_id,
                "reply_to_message_id": str(reply_to_message_id or ""),
                "text_preview": text_preview(text),
            },
        )

    async def reply_to_event(event) -> None:
        message = getattr(event, "message", event)
        raw_text = getattr(event, "raw_text", "") or getattr(message, "raw_text", "") or ""
        chat_id = str(getattr(event, "chat_id", getattr(message, "chat_id", "")))
        message_id = getattr(message, "id", "")
        event_out = bool(getattr(event, "out", getattr(message, "out", False)))
        get_sender = getattr(event, "get_sender", None) or getattr(message, "get_sender", None)
        sender = await get_sender() if get_sender else None
        actor_id = str(getattr(sender, "id", "telegram-user"))
        log_message_record(
            chat_id=chat_id,
            message_id=message_id,
            direction="incoming_event_outgoing" if event_out else "incoming_event",
            actor_id=actor_id,
            text=raw_text,
        )
        if message and message.media:
            file_info = getattr(message, "file", None)
            size_bytes = int(getattr(file_info, "size", 0) or 0)
            if size_bytes > max_upload_mb * 1024 * 1024:
                sent = await event.reply(f"Файл слишком большой. Лимит: {max_upload_mb} MB.")
                ignored_outgoing_message_ids.add(sent.id)
                log_message_record(
                    chat_id=chat_id,
                    message_id=sent.id,
                    direction="assistant_reply",
                    actor_id="assistant",
                    text=f"Файл слишком большой. Лимит: {max_upload_mb} MB.",
                    reply_to_message_id=message_id,
                )
                return
            original_name = getattr(file_info, "name", None) or f"telegram_{message_id}"
            received_at = datetime.now(timezone.utc)
            archive_path = build_archive_path(
                PROJECT_ROOT,
                original_name=original_name,
                chat_id=chat_id,
                message_id=str(message_id),
                ts=received_at,
            )
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            downloaded = await event.download_media(file=str(archive_path))
            stored_path = Path(downloaded or archive_path)
            digest = sha256_file(stored_path)
            caption = raw_text
            mime_type = getattr(file_info, "mime_type", "") or ""
            extracted = extract_document_text(stored_path, mime_type=mime_type, max_chars=max_extract_chars)
            metadata = {
                "source": "telegram",
                "actor_id": actor_id,
                "chat_id": chat_id,
                "message_id": str(message_id),
                "original_filename": original_name,
                "stored_path": str(stored_path),
                "sha256": digest,
                "mime_type": mime_type,
                "size_bytes": stored_path.stat().st_size,
                "received_at": received_at.isoformat(),
                "tenant_scope": tenant_scope,
                "suggested_matter_id": assistant._extract_matter_id(caption),
                "caption": caption,
                "extraction_status": extracted.status,
                "extraction_engine": extracted.extractor,
                "extraction_error": extracted.error,
                "extracted_text_chars": extracted.char_count,
                "extracted_text": extracted.text,
            }
            write_metadata(stored_path, metadata)
            reply = assistant.handle_document(actor_id=actor_id, metadata=metadata, caption=caption)
            sent = await event.reply(reply)
            ignored_outgoing_message_ids.add(sent.id)
            log_message_record(
                chat_id=chat_id,
                message_id=sent.id,
                direction="assistant_reply",
                actor_id="assistant",
                text=reply,
                reply_to_message_id=message_id,
            )
            return
        if raw_text.strip().lower() == "/id":
            reply = build_message_id_reply(
                chat_id=chat_id,
                message_id=message_id,
                sender_id=actor_id,
                direction="outgoing" if event_out else "incoming",
            )
            sent = await event.reply(reply)
            ignored_outgoing_message_ids.add(sent.id)
            log_message_record(
                chat_id=chat_id,
                message_id=sent.id,
                direction="assistant_reply",
                actor_id="assistant",
                text=reply,
                reply_to_message_id=message_id,
            )
            return
        reply = assistant.handle_text(actor_id=actor_id, text=raw_text)
        sent = await event.reply(reply)
        ignored_outgoing_message_ids.add(sent.id)
        log_message_record(
            chat_id=chat_id,
            message_id=sent.id,
            direction="assistant_reply",
            actor_id="assistant",
            text=reply,
            reply_to_message_id=message_id,
        )

    async def poll_allowed_chat() -> None:
        if not allowed_chat or not allowed_chat.lstrip("-").isdigit():
            return
        target_chat_id = int(allowed_chat)
        entity = await client.get_entity(target_chat_id)
        last_seen_id = 0
        async for message in client.iter_messages(entity, limit=1):
            last_seen_id = message.id
        print(
            f"Telegram polling enabled for chat_id={target_chat_id}; starting after message_id={last_seen_id}",
            flush=True,
        )
        while True:
            try:
                new_messages = []
                async for message in client.iter_messages(entity, min_id=last_seen_id, reverse=True):
                    new_messages.append(message)
                for message in new_messages:
                    last_seen_id = max(last_seen_id, message.id)
                    if message.id in ignored_outgoing_message_ids:
                        continue
                    if not message.out:
                        continue
                    if not message.media and not should_process_outgoing_text(message.raw_text or ""):
                        print(f"Telegram polling skipped assistant/self text message_id={message.id}", flush=True)
                        continue
                    if not should_handle_chat(
                        chat_title=str(getattr(entity, "username", "") or getattr(entity, "title", "") or ""),
                        chat_id=str(target_chat_id),
                        allowed_chat=allowed_chat,
                        is_private=bool(getattr(entity, "bot", False) or entity.__class__.__name__ == "User"),
                        allow_private=allow_private,
                        allow_all_chats=allow_all_chats,
                    ):
                        continue
                    if message.media:
                        print(f"Telegram polling processing media message_id={message.id}", flush=True)
                        await reply_to_event(message)
                        continue
                    print(f"Telegram polling processing text message_id={message.id}", flush=True)
                    log_message_record(
                        chat_id=str(target_chat_id),
                        message_id=message.id,
                        direction="polling_outgoing",
                        actor_id="telegram-self",
                        text=message.raw_text or "",
                    )
                    if (message.raw_text or "").strip().lower() == "/id":
                        reply = build_message_id_reply(
                            chat_id=str(target_chat_id),
                            message_id=message.id,
                            sender_id="telegram-self",
                            direction="outgoing",
                        )
                    else:
                        reply = assistant.handle_text(actor_id="telegram-self", text=message.raw_text or "")
                    sent = await client.send_message(entity, reply, reply_to=message.id)
                    ignored_outgoing_message_ids.add(sent.id)
                    log_message_record(
                        chat_id=str(target_chat_id),
                        message_id=sent.id,
                        direction="assistant_reply",
                        actor_id="assistant",
                        text=reply,
                        reply_to_message_id=message.id,
                    )
                    print(f"Telegram polling sent reply message_id={sent.id}", flush=True)
            except Exception as exc:
                print(f"Telegram polling error: {exc}", flush=True)
            await asyncio.sleep(2)

    @client.on(events.NewMessage())
    async def handler(event):  # type: ignore[no-redef]
        if not should_process_new_message_event(bool(event.out)):
            return
        chat = await event.get_chat()
        chat_title = getattr(chat, "title", "") or getattr(chat, "username", "") or ""
        if not should_handle_chat(
            chat_title=chat_title,
            chat_id=str(event.chat_id),
            allowed_chat=allowed_chat,
            is_private=bool(getattr(event, "is_private", False)),
            allow_private=allow_private,
            allow_all_chats=allow_all_chats,
        ):
            return
        await reply_to_event(event)

    retry_seconds = int(os.getenv("LEGASVEX_TELEGRAM_CONNECT_RETRY_SECONDS", "5"))
    while True:
        print("LegasVex Telegram assistant connecting.", flush=True)
        try:
            await client.connect()
            break
        except Exception as exc:
            print(f"LegasVex Telegram assistant connect failed: {exc}; retrying.", flush=True)
            await asyncio.sleep(retry_seconds)
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session is not authorized. Run: python -m telegram_assistant.authorize_telegram")
    print("LegasVex Telegram assistant connected.", flush=True)
    asyncio.create_task(poll_allowed_chat())
    print("LegasVex Telegram assistant started.", flush=True)
    await client.run_until_disconnected()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
