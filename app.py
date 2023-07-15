#!/usr/bin/env python

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

import guidance.llms
import tiktoken
from dotenv import load_dotenv
from telegram import ForceReply, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from shared import ChatContext
from tool_load import load_webpage
from tool_search import search

load_dotenv()

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
guidance.llm = guidance.llms.OpenAI("gpt-4-0613", caching=False)
encoding = tiktoken.encoding_for_model("gpt-4-0613")

# State:
chat_history: Dict[str, List["ChatHistoryItem"]] = {}


class Role(Enum):
    SYSTEM = "system"
    ASSISTANT = "assistant"
    USER = "user"


class Created(Enum):
    INITIAL = 1
    MANUAL = 2
    AUTO = 3


@dataclass
class ChatHistoryItem:
    role: Role
    content: str
    created: Created = Created.MANUAL

    def __str__(self) -> str:
        s = "\n{{#" + self.role.value + "~}}"
        s += "\n" + self.content.strip()
        s += "\n{{~/" + self.role.value + "}}"
        return s


class ChatHistory:
    def __init__(self, context: ChatContext):
        self.user = context.user
        if self.user not in chat_history:
            chat_history[self.user] = []
        if len(chat_history[self.user]) == 0:
            logging.warning("Resetting chat history")
            self.reset()

    def add_history(self, role: Role, content: str):
        assert content
        chat_history[self.user].append(ChatHistoryItem(role, content))

    def count_tokens(self):
        num_tokens = 0
        for item in chat_history[self.user]:
            num_tokens += len(encoding.encode(item.content))
        return num_tokens

    def reset(self):
        chat_history[self.user] = [
            ChatHistoryItem(
                Role.SYSTEM,
                "You are a helpful assistant.\n{{>tool_def functions=functions}}",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(
                Role.USER,
                """Answer as short and concise, but maintaining relevant information.
You are a my assistant with an IQ of 120.
From now on, whenever your response depends on any factual information, or if the I ask you to confirm something please search for more updated information on the internet.

Ok?""",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(Role.ASSISTANT, "Ok", created=Created.INITIAL),
        ]

    def get_history(self) -> List[ChatHistoryItem]:
        return chat_history[self.user]


class Chattergpt:
    def __init__(self, context: ChatContext):
        self.context = context
        self.functions = [
            {
                "name": "search",
                "description": "Search the internet for up to date information",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search string",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "load_webpage",
                "description": "Load a web page",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "A valid url to load. Always use a search first to find the correct url unless you are told which url to use",
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

        self._chat_history = ChatHistory(context)

    def create_program(self, prompt: str) -> guidance.Program:
        return guidance(prompt)  # type: ignore

    def reset_history(self):
        self._chat_history.reset()

    def count_tokens(self):
        return self._chat_history.count_tokens()

    async def summarize(self):
        await self.context.reply_text("Summarizing our conversation so far...")
        await self.context.telegram_action_typing()
        history = [v for v in self._chat_history.get_history() if not v.created == Created.INITIAL]
        self._chat_history.add_history(
            Role.USER,
            "Please summarize our conversation so far. Answer with summary only.",
        )
        # FIXME : there is an empty assistant content in here.. dont know why.
        prompt_str = "".join(str(v) for v in history)
        prompt_str += """
{{#assistant~}}
{{gen "answer"}}
{{~/assistant}}"""
        program = self.create_program(prompt_str)
        answer = await self.context.stream_chatgpt_reply(program(stream=True, silent=True))  # type: ignore
        self._chat_history.reset()
        assert answer
        self._chat_history.add_history(Role.ASSISTANT, answer)

    async def on_user_message(self, message: str):
        token_count = self.count_tokens()
        if token_count > 2500:
            logging.warning(f"Token count high {token_count} Summarizing...")
            await self.summarize()
        token_count = self.count_tokens()

        self._chat_history.add_history(Role.USER, message)

        history = self._chat_history.get_history()
        prompt_str = "".join(str(v) for v in history)
        prompt_str += """
{{~#each range(10)~}}
    {{#assistant~}}
        {{gen "answer" function_call="auto" }}
    {{~/assistant}}
    {{#if not callable(answer)}}{{break}}{{/if}}
    {{~#function name=answer.__name__~}}
    {{answer()}}
    {{~/function~}}
{{~/each~}}
"""
        # print("Query:\n", prompt_str, "\n")
        logging.info(f"Token count estimate : {token_count}")

        program = self.create_program(prompt_str)
        logger.info("Computing answer...")
        answer = await self.context.stream_chatgpt_reply(
            program(stream=True, silent=True, functions=self.functions, search=search, load_webpage=load_webpage)  # type: ignore
        )
        logger.info("Answer recieved")
        assert answer
        self._chat_history.add_history(Role.ASSISTANT, answer)


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /start is issued."""
    assert update.message and update.effective_user
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message
    chat_context = ChatContext(update, context)
    Chattergpt(chat_context).reset_history()
    await update.message.reply_text("Ok")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.info("message_handler received text")
    assert update.message and update.message.text and update.effective_user
    chattergpt = Chattergpt(ChatContext(update, context))

    allowed_userids = os.environ["ALLOWED_TELEGRAM_USER_IDS"].split(",")
    if not str(update.effective_user.id) in allowed_userids:
        logging.warning(
            f"User {update.effective_user.id} {update.effective_user.username} - not whitelisted ({allowed_userids})"
        )
        await chattergpt.context.reply_text("Sorry, you are not whitelisted.")
        return

    await chattergpt.on_user_message(update.message.text)


def main() -> None:
    application = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )
    logging.info("Run polling...")
    application.run_polling()


if __name__ == "__main__":
    main()
