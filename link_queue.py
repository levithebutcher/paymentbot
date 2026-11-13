"""
Asynchronous Link Resolver Queue
=================================
Manages concurrent and bulk-forwarded link resolution tasks.
Ensures zero race conditions, handles Telegram rate-limiting,
and gives instant queue position feedback to users.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import NamedTuple, Optional
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from resolve_link import extract_final_link_async

logger = logging.getLogger("link_queue")


class ResolveTask(NamedTuple):
    message: Message
    url: str
    status_msg: Message
    task_id: int


class LinkResolverQueue:
    def __init__(self, concurrency: int = 2):
        self._queue: asyncio.Queue[ResolveTask] = asyncio.Queue()
        self._concurrency = concurrency
        self._workers: list[asyncio.Task] = []
        self._task_counter = 0
        self._started = False

    def start(self) -> None:
        """Starts background worker consumers."""
        if not self._started:
            self._started = True
            for i in range(self._concurrency):
                worker = asyncio.create_task(self._worker_loop(i + 1))
                self._workers.append(worker)
            logger.info("LinkResolverQueue started with %d workers.", self._concurrency)

    async def enqueue(self, message: Message, url: str) -> None:
        """
        Enqueues a link resolution task.
        Sends immediate user feedback with queue position if busy.
        """
        if not self._started:
            self.start()

        self._task_counter += 1
        current_queue_depth = self._queue.qsize()

        if current_queue_depth > 0:
            status_text = (
                f"⏳ <i>In queue (Position #{current_queue_depth + 1})... "
                "Resolving shortly!</i>"
            )
        else:
            status_text = "⏳ <i>Resolving destination link...</i>"

        try:
            status_msg = await message.answer(status_text, parse_mode="HTML")
        except Exception:
            # Fallback if answer fails
            status_msg = await message.reply(status_text, parse_mode="HTML")

        task = ResolveTask(
            message=message,
            url=url,
            status_msg=status_msg,
            task_id=self._task_counter,
        )
        await self._queue.put(task)

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker loop continuously pulling tasks from queue."""
        logger.debug("Worker %d listening for tasks...", worker_id)
        while True:
            try:
                task = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                await self._process_task(task)
            except asyncio.CancelledError:
                self._queue.task_done()
                break
            except Exception as exc:
                logger.error("Worker %d unexpected error: %s", worker_id, exc, exc_info=True)
            finally:
                self._queue.task_done()

    async def _process_task(self, task: ResolveTask) -> None:
        """Processes a single link resolution task."""
        message, url, status_msg = task.message, task.url, task.status_msg

        try:
            # If status message indicated queue waiting, update to active resolving
            try:
                await status_msg.edit_text("⏳ <i>Resolving destination link...</i>", parse_mode="HTML")
            except Exception:
                pass

            final_link = await extract_final_link_async(url)

            kb = None
            if final_link.startswith(("http://", "https://", "tg://")):
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👉 Open Destination Link", url=final_link)]
                ])

            reply_text = (
                "<blockquote>\n"
                "<b>🎯 LINK RESOLVED</b>\n"
                f"<b>Destination:</b> <code>{html.escape(final_link)}</code>\n"
                "</blockquote>"
            )
            await status_msg.edit_text(reply_text, reply_markup=kb, parse_mode="HTML")

            # Delete the user's forwarded / raw message to keep chat spotless
            try:
                await message.delete()
            except Exception:
                pass

        except Exception as exc:
            err_msg = html.escape(str(exc))
            try:
                await status_msg.edit_text(
                    f"❌ <b>Failed to resolve link:</b>\n<i>{err_msg}</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Brief rate-limiting pause between tasks
        await asyncio.sleep(0.4)


# Global singleton instance
resolver_queue = LinkResolverQueue(concurrency=2)
