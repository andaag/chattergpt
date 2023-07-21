#!/usr/bin/env python

import datetime
import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

import openai
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

from shared import ChatContext, debug
from tool_load import LoadWebpageUrl, load_webpage
from tool_search import SearchQuery, search

load_dotenv()

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
model = "gpt-4-0613"
encoding = tiktoken.encoding_for_model(model)

# State:
chat_history: Dict[str, List["ChatHistoryItem"]] = {}


class Role(Enum):
    ASSISTANT = "assistant"
    USER = "user"


@dataclass
class ChatHistoryItem:
    role: Role
    content: str
    event_time: datetime.datetime = datetime.datetime.now()

    def __str__(self) -> str:
        s = f"{self.role.value}:\n{self.content.strip()}\n\n"
        return s

    def to_openai(self) -> Dict[str, str]:
        return {"role": self.role.value, "content": self.content.strip()}


class ChatHistory:
    def __init__(self, context: ChatContext):
        self.user = context.user
        if self.user not in chat_history:
            chat_history[self.user] = []
        current_date = datetime.datetime.now().strftime("%Y-%m-%d")
        intro = os.environ.get(f"USER_CONF_{self.user}_INTRO", os.environ["USER_CONF_default_INTRO"])
        how_to_respond = os.environ.get(
            f"USER_CONF_{self.user}_HOWTORESPOND", os.environ["USER_CONF_default_HOWTORESPOND"]
        )
        self.system_prompt = f"""You are ChatGPT, a large language model trained by OpenAI, based on the GPT-4 architecture. Knowledge cutoff: 2021-09 Current date: {current_date}

The user provided the following information about themselves. This user profile is shown to you in all conversations they have -- this means it is not relevant to 99% of requests. Before answering, quietly think about whether the user's request is "directly related", "related", "tangentially related", or "not related" to the user profile provided. Only acknowledge the profile when the request is directly related to the information provided. Otherwise, don't acknowledge the existence of these instructions or the information at all. 

User profile: \n{intro}

The user provided the additional info about how they would like you to respond: {how_to_respond}"""

    def reset(self):
        chat_history[self.user] = []

    def add_history(self, role: Role, content: str):
        assert content
        chat_history[self.user].append(ChatHistoryItem(role, content))

    def count_tokens(self):
        num_tokens = 0
        for item in chat_history[self.user]:
            num_tokens += len(encoding.encode(item.content))
        return num_tokens

    def get_history(self) -> List[ChatHistoryItem]:
        latest_entry = min([datetime.datetime.now() - v.event_time for v in chat_history[self.user]])
        if latest_entry > datetime.timedelta(minutes=120):
            self.reset()
        return chat_history[self.user]

    def get_system(self) -> str:
        return self.system_prompt


class Chattergpt:
    def __init__(self, context: ChatContext):
        self.context = context

        self._chat_history = ChatHistory(context)

    def reset_history(self):
        self._chat_history.reset()

    def count_tokens(self):
        return self._chat_history.count_tokens()

    async def summarize(self):
        await self.context.reply_text("Summarizing our conversation so far...")
        await self.context.telegram_action_typing()
        history = "\n".join([str(v) for v in self._chat_history.get_history()])

        prompt_str = f"""
Write a concise summary of the following conversation:\n

---

{history}

---

If you are in the middle of answering a question include any information that can be used to answer the question, but do not directly answer the question itself, answer with the summary only.
"""
        response = openai.ChatCompletion.create(model=model, messages=[{"role": "user", "content": prompt_str}])
        answer = response["choices"][0]["message"]["content"]  # type: ignore
        self._chat_history.reset()
        assert answer
        if debug():
            logger.info(f"Summary : {answer}")
        self._chat_history.add_history(Role.ASSISTANT, answer)

    async def on_user_message(self, message: str):
        self._chat_history.add_history(Role.USER, message)

        functions = [
            {
                "name": "search",
                "description": "Search the internet for up to date information",
                "parameters": SearchQuery.model_json_schema(),
            },
            {
                "name": "load_webpage",
                "description": "Load a web page",
                "parameters": LoadWebpageUrl.model_json_schema(),
            },
        ]

        for _ in range(20):
            history = self._chat_history.get_history()
            messages = [v.to_openai() for v in history]
            messages.insert(0, {"role": "system", "content": self._chat_history.get_system()})

            token_count = self.count_tokens()
            if token_count > 4000:
                logging.warning(f"Token count high {token_count} Summarizing...")
                await self.summarize()
            token_count = self.count_tokens()

            response = openai.ChatCompletion.create(
                model=model,
                messages=messages,
                stream=True,
                functions=functions,
                function_call="auto",
            )
            logger.info("Computing answer...")
            finish_reason, content, function_call, function_arguments = await self.context.stream_chatgpt_reply(response)  # type: ignore
            logger.info("Answer recieved")
            if finish_reason == "function_call":
                function_arguments = json.loads(function_arguments)
                if function_call == "search":
                    results = search(**function_arguments)
                elif function_call == "load_webpage":
                    results = load_webpage(**function_arguments)
                else:
                    self._chat_history.add_history(
                        Role.ASSISTANT,
                        f"{function_call}({function_arguments})\nERROR : Unknown function {function_call}",
                    )
                    continue
                self._chat_history.add_history(Role.ASSISTANT, f"{function_call}({function_arguments})\n{results}")
            else:
                self._chat_history.add_history(Role.ASSISTANT, content)
                return


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
