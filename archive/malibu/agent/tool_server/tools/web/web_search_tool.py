import json
from typing import Any

from malibu.agent.tool_server.tools.base import BaseTool, ToolResult


# Name
NAME = "web_search"
DISPLAY_NAME = "Web Search"

# Tool description
DESCRIPTION = """Performs a web search using a search engine API and returns the top 5 results with each result's title, URL, and snippet. 

When to Use
- Find information on the internet that goes beyond the model's training cutoff
- Research current events, documentation, tutorials, or updates
- Check the latest news and trends

Combine with the web_visit tool to open a result's URL and extract its full content.
"""

# Input schema
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The search query to find information on the web"},
        "max_results": {
            "type": "integer",
            "description": "Optional number of results to return. Defaults to the tool runtime setting.",
        },
    },
    "required": ["query"],
}

DEFAULT_MAX_RESULTS = 12
    
class WebSearchTool(BaseTool):
    name = NAME
    display_name = DISPLAY_NAME
    description = DESCRIPTION
    input_schema = INPUT_SCHEMA
    read_only = True

    def __init__(self, client: Any, max_results: int = DEFAULT_MAX_RESULTS):
        self.client = client
        self.max_results = max_results

    async def execute(
        self,
        tool_input: dict[str, Any],
    ) -> ToolResult:
        query = tool_input["query"]
        max_results = int(tool_input.get("max_results") or self.max_results)

        try:
            response = await self.client.search(query, max_results=max_results)
        except Exception as e:
            return ToolResult(
                llm_content=f"Web search failed: {e}",
                is_error=True,
            )

        results = response.result[:max_results]
        results_str = json.dumps(results, indent=2)

        if len(results) == 0:
            return ToolResult(
                llm_content=(
                    f"No results found for '{query}'. Try broader keywords or check for typos."
                ),
                user_display_content=results_str,
                is_error=False,
            )
        
        return ToolResult(
            llm_content=results_str,
            is_error=False,
        )

    async def execute_mcp_wrapper(self, query: str):
        return await self._mcp_wrapper(
            tool_input={
                "query": query,
            }
        )

