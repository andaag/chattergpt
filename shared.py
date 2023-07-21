import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Dict, Generator, List

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
                if "Too Many Requests" in str(e):
                    await asyncio.sleep(backoff)
                    backoff += 1
                    continue
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

    async def stream_chatgpt_reply(self, response: Generator[Dict[Any, str], None, None]):
        await self.telegram_action_typing()
        logger.info("Callback stream_chatgpt_reply")

        @retry
        async def create_inital_message():
            logger.info("Callback create_inital_message...")
            return await self.reply_text("...")

        @retry
        async def edit_message(telegram_message: Message, text: str):
            if text:
                await telegram_message.edit_text(text)

        telegram_message = await create_inital_message()
        logger.info(f"Telegram message created {telegram_message}")

        content = ""
        function_call = ""
        function_arguments = ""
        finish_reason = ""
        last_response = None
        last_edit = time.time()

        def rendered_content():
            s = content
            if not s and function_call:
                s += f"```\n{function_call}({function_arguments})\n```"
            if s == last_response:
                return ""
            return s

        for chunk in response:
            choice = chunk["choices"][0]
            content += choice["delta"].get("content", "") or ""  # type: ignore
            function_call += choice["delta"].get("function_call", {}).get("name", "") or ""  # type: ignore
            function_arguments += choice["delta"].get("function_call", {}).get("arguments") or ""  # type: ignore
            finish_reason += choice["finish_reason"] or ""  # type: ignore

            if not finish_reason and time.time() - last_edit > 0.5:
                await edit_message(telegram_message, rendered_content())
                last_edit = time.time()
            last_response = rendered_content()

        try:
            await telegram_message.edit_text(rendered_content(), parse_mode=constants.ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Failed to edit message {e}")
            await edit_message(telegram_message, rendered_content())

        return finish_reason, content, function_call, function_arguments


@dataclass
class ToolResult:
    reply: str


class Tool(ABC):
    @abstractmethod
    async def process_commands(self, context: ChatContext, commands: List[str]) -> ToolResult | None:
        pass

    @abstractmethod
    def tool_regex_match(self) -> str:
        pass
        pass
