import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List

import guidance
from telegram import Message, Update, constants
from telegram.ext import ContextTypes


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
        telegram_message = await self.reply_text("...")
        response = ""
        for running_reply in reply:
            response = running_reply.get("answer", "").strip()
            if response:
                await telegram_message.edit_text(response)
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
