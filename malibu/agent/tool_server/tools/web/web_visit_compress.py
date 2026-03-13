from typing import Any, List

from malibu.agent.tool_server.tools.base import BaseTool, ToolResult


# Name
NAME = "web_visit_compress"
DISPLAY_NAME = "Web Visit Compress"

# Tool description
DESCRIPTION = "You should call this tool when you need to visit a webpage and extract relevant content. Returns relevant webpage content as text."

# Input schema
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "urls": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "description": "The urls of the webpages to visit.",
        },
        "query": {
            "type": "string",
            "description": "The query to extract relevant content.",
        },
    },
    "required": ["urls", "query"],
}

DEFAULT_TIMEOUT = 300


class WebVisitCompressTool(BaseTool):
    name = NAME
    display_name = DISPLAY_NAME
    description = DESCRIPTION
    input_schema = INPUT_SCHEMA
    read_only = True

    def __init__(self, service: Any):
        self.service = service

    async def execute(
        self,
        tool_input: dict[str, Any],
    ) -> ToolResult:
        urls = tool_input["urls"]
        query = tool_input["query"]
        process_urls = []
        for url in urls:
            if "arxiv.org/abs" in url:
                url = "https://arxiv.org/html/" + url.split("/")[-1]
            process_urls.append(url)

        try:
            response = await self.service.researcher_visit(process_urls, query)
        except Exception as e:
            return ToolResult(
                llm_content=f"Web visit compression failed: {e}",
                is_error=True,
            )

        content = response.content

        return ToolResult(
            llm_content=content,
            user_display_content=content,
        )


    async def execute_mcp_wrapper(self, urls: List[str], query: str):
        return await self._mcp_wrapper(
            tool_input={
                "urls": urls,
                "query": query,
            }
        )

