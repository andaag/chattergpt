import logging

from trafilatura import extract, fetch_url
from trafilatura.settings import use_config

from shared import ChatContext, Tool, ToolResult

trafilatura_config = use_config()
trafilatura_config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")


class LoadTool(Tool):
    def tool_regex_match(self) -> str:
        return r"<load>(.*?)<\/load>"

    async def process_commands(
        self, context: ChatContext, url: str
    ) -> ToolResult | None:
        await context.telegram_action_typing()

        logging.info(f"Loading url {url}")

        downloaded = fetch_url(url)
        url_content = extract(downloaded, include_links=True, config=trafilatura_config)

        if not url_content:
            url_content = "Could not load url, maybe you can try another?"
        results = f"<result>\n{url_content}\n</result>"

        return ToolResult(results)
