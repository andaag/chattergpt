import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from typing import List

import guidance
from telegram import Message, Update, constants
from telegram.error import RetryAfter, TimedOut
from telegram.ext import ContextTypes


def retry(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        retries = 5
        backoff = 2
        last_exception = None

        for _ in range(5):
            retries += 1
            try:
                return await func(*args, **kwargs)
            except RetryAfter as e:
                last_exception = e
                await asyncio.sleep(e.retry_after)
                backoff = 1
                continue
            except TimedOut as e:
                last_exception = e
                await asyncio.sleep(backoff)
                backoff += 2
                continue
            except Exception as e:
                last_exception = e
                await asyncio.sleep(backoff)
                backoff += 2
                continue
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

        @retry
        async def create_inital_message():
            return await self.reply_text("...")

        @retry
        async def edit_message(telegram_message: Message, text: str):
            await telegram_message.edit_text(response)

        telegram_message = await create_inital_message()
        print("Telegram message created", telegram_message)

        response = ""
        for running_reply in reply:
            response = running_reply.get("answer", "").strip()
            if response:
                await edit_message(telegram_message, response)
        return response


@dataclass
class ToolResult:
    reply: str
    # hidden:bool = False


class Tool(ABC):
    @abstractmethod
    async def process_commands(
        self, context: ChatContext, commands: List[str]
    ) -> ToolResult | None:
        pass

    @abstractmethod
    def tool_regex_match(self) -> str:
        pass
