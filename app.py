#!/usr/bin/env python

import logging
import os
import re
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
from tool_load import LoadTool
from tool_search import SearchTool

load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)
guidance.llm = guidance.llms.OpenAI("gpt-4")
encoding = tiktoken.encoding_for_model("gpt-4")


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
                Role.SYSTEM, "You are a helpful assistant.", created=Created.INITIAL
            ),
            ChatHistoryItem(
                Role.USER,
                """Answer as short and concise, but maintaining relevant information.
You are a researcher.
From now on, whenever your response depends on any factual information, or if the user asks you to confirm something, please search the web by using the function <search>query</search> before responding. I will then paste web results in, and you can respond.
If you can't find the results in the search result you can use <load>https://www.valid.url/with/parameters</load> to have me load a webpage for you with more details.""",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(Role.ASSISTANT, "Ok", created=Created.INITIAL),
            ChatHistoryItem(
                Role.USER,
                """Lets practice. What is Microsoft's stock price right now?""",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(
                Role.ASSISTANT,
                "<search>Microsoft stock price</search>",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(
                Role.USER,
                """<result>
Microsoft Corp (MSFT) Stock Price & News - Google Finance Home MSFT • NASDAQ Microsoft Corp Follow Share

https://finance.yahoo.com/quote/MSFT/
</result>
<result>
Microsoft Corporation (MSFT) Stock Price, News, Quote & History - Yahoo Finance U.S. markets closed -4.31 Russell 2000 -7.29(-0.40%) (+0.05%) -2.80 HAPPENING SOON: Yahoo Finance breaks...

https://www.marketwatch.com/investing/stock/msft
</result>""",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(
                Role.ASSISTANT,
                """<load>https://finance.yahoo.com/quote/MSFT/</load>""",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(
                Role.USER,
                """<result>
NASDAQ Microsoft Corp Follow Share $288.37 After Hours: $287.86 (0.18%) -0.51 Closed: Apr 18, 5:57:32 PM GMT-4 ·...
</result>
""",
                created=Created.INITIAL,
            ),
            ChatHistoryItem(
                Role.ASSISTANT,
                """Microsoft's stock price is currently $288.37. Please note that stock prices are constantly changing, so it's best to check an updated source for the most accurate information.""",
                created=Created.INITIAL,
            ),
        ]

    def get_history(self) -> List[ChatHistoryItem]:
        return chat_history[self.user]


class Chattergpt:
    def __init__(self, context: ChatContext):
        self.context = context

        self._chat_history = ChatHistory(context)
        self.tools = [SearchTool(), LoadTool()]

    def reset_history(self):
        self._chat_history.reset()

    def count_tokens(self):
        return self._chat_history.count_tokens()

    async def summarize(self):
        await self.context.reply_text("Summarizing our conversation so far...")
        await self.context.telegram_action_typing()
        history = [
            v
            for v in self._chat_history.get_history()
            if not v.created == Created.INITIAL
        ]
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
        prompt = guidance(prompt_str)  # type: ignore
        answer = await self.context.stream_chatgpt_reply(
            prompt(stream=True, silent=True)
        )
        self._chat_history.reset()
        assert answer
        self._chat_history.add_history(Role.ASSISTANT, answer)

    async def on_user_message(self, message: str, automated_reply_count: int = 0):
        token_count = self.count_tokens()
        if token_count > 2500:
            logging.warning(f"Token count high {token_count} Summarizing...")
            await self.summarize()
        token_count = self.count_tokens()

        logging.info(
            f"on_user_message : Answering (automated reply count {automated_reply_count})"
        )
        self._chat_history.add_history(Role.USER, message)

        history = self._chat_history.get_history()
        prompt_str = "".join(str(v) for v in history)
        prompt_str += """
{{#assistant~}}
{{gen "answer"}}
{{~/assistant}}"""

        logging.info(f"Token count estimate : {token_count}")
        prompt = guidance(prompt_str)  # type: ignore
        answer = await self.context.stream_chatgpt_reply(
            prompt(stream=True, silent=True)
        )
        assert answer
        self._chat_history.add_history(Role.ASSISTANT, answer)
        await self.on_answer(answer, automated_reply_count)

    async def on_answer(self, answer: str, automated_reply_count: int = 0):
        logging.info(f"on_answer {automated_reply_count}")
        if automated_reply_count > 5:
            logging.warning("Too many automated replies, stopping")
            await self.context.reply_text(
                "Too many automated replies, stopping - Please let me know how this happened to improve!"
            )
            return
        for tool in self.tools:
            match = re.search(tool.tool_regex_match(), answer)
            if match:
                logging.info(f"on_answer - found tool {tool.__class__.__name__}")
                await self.context.telegram_action_typing()
                reply = await tool.process_commands(self.context, match.group(1))
                if reply:
                    short_reply = reply.reply
                    if len(short_reply) > 4000:
                        short_reply = short_reply.replace("</result>", "")
                        short_reply = short_reply[:3950] + "...</result>"
                    # todo : could calculate whats left of context length here and limit based on that...
                    await self.context.reply_text(short_reply)
                    await self.on_user_message(short_reply, automated_reply_count + 1)
                    break


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
