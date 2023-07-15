import asyncio
import logging
import os
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from typing import List

import guidance
from telegram import Message, Update, constants
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import ContextTypes

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def debug() -> bool:
    return os.environ.get("DEBUG", "false") == "true"


def retry(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        backoff = 1
        last_exception = None

        for _ in range(3):
            try:
                return await func(*args, **kwargs)
            except RetryAfter as e:
                last_exception = e
                await asyncio.sleep(e.retry_after)
                continue
            except TimedOut as e:
                last_exception = e
                await asyncio.sleep(backoff)
                backoff += 1
                continue
            except BadRequest as e:
                logger.warning(f"Ignoring badrequest {e}")
                return
        assert last_exception
        raise last_exception

    return wrapper


@dataclass
class ChatContext:
    update: Update
    telegram_context: ContextTypes.DEFAULT_TYPE

    @property
    def user(self) -> str:
        assert self.update.effective_user and self.update.effective_user.username
        return self.update.effective_user.username

    async def telegram_action_typing(self):
        assert self.update and self.update.message
        await self.update.message.reply_chat_action(action=constants.ChatAction.TYPING)

    async def reply_text(self, message: str) -> Message:
        assert self.update and self.update.message
        return await self.update.message.reply_text(message)

    async def stream_chatgpt_reply(self, reply: guidance.Program):
        await self.telegram_action_typing()
        logger.info("Callback stream_chatgpt_reply")

        @retry
        async def create_inital_message():
            logger.info("Callback create_inital_message...")
            return await self.reply_text("...")

        @retry
        async def edit_message(telegram_message: Message, text: str):
            logger.info("Callback edit_message...")
            await telegram_message.edit_text(text)

        telegram_message = await create_inital_message()
        logger.info(f"Telegram message created {telegram_message}")

        last_response = ""
        response = ""
        for running_reply in reply:
            response = running_reply.get("answer", "").strip()
            if response and response != last_response:
                await edit_message(telegram_message, response)
                last_response = response
                await asyncio.sleep(0.1)  # minimum delay.
        return response


@dataclass
class ToolResult:
    reply: str
    # hidden:bool = False


class Tool(ABC):
    @abstractmethod
    async def process_commands(self, context: ChatContext, commands: List[str]) -> ToolResult | None:
        pass

    @abstractmethod
    def tool_regex_match(self) -> str:
        pass
        pass
