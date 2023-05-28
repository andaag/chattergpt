import json
import logging
import os
from typing import Dict

import requests

from shared import ChatContext, Tool, ToolResult


def search(query):
    def _search(query):
        url = "https://google.serper.dev/search"

        payload = json.dumps({"q": query})
        headers = {
            "X-API-KEY": os.environ["SERPER_API_KEY"],
            "Content-Type": "application/json",
        }

        response = requests.request("POST", url, headers=headers, data=payload)
        return response.json()

    results = _search(query)
    snippets = [v for v in results["organic"] if "youtube" not in v["link"]]
    # if "answerBox" in results:
    #    snippets = [
    #        {
    #            "snippet": results["answerBox"]["title"]
    #            + "="
    #            + results["answerBox"]["answer"]
    #        }
    #    ] + snippets
    return snippets[0:3]


class SearchTool(Tool):
    def tool_regex_match(self) -> str:
        return r"<search>(.*?)<\/search>"

    async def process_commands(
        self, context: ChatContext, search_query: str
    ) -> ToolResult | None:
        await context.telegram_action_typing()

        logging.info(f"Search : Searching for {search_query}")

        results_list = search(search_query)
        results = "No results found"

        if results_list:

            def entry_to_str(item: Dict[str, str]):
                yield "\n<result>\n"
                yield item["snippet"].strip()
                if "link" in item:
                    yield "\n" + item["link"].strip()
                yield "\n<result>\n"

            results = "".join(["".join(entry_to_str(item)) for item in results_list])
        return ToolResult(results)
