import json

from typing import Any, List

from malibu.agent.tool_server.tools.base import BaseTool, ToolResult


# Name
NAME = "web_batch_search"
DISPLAY_NAME = "Web Batch Search"

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
        "queries": {"type": "array", "items": {"type": "string"}, "description": "The search queries to find information on the web"},
        "max_results": {
            "type": "integer",
            "description": "Optional number of results to return per query.",
        },
    },
    "required": ["queries"],
}

DEFAULT_MAX_RESULTS = 12
    
class WebBatchSearchTool(BaseTool):
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
        queries = tool_input["queries"]
        max_results = int(tool_input.get("max_results") or self.max_results)

        try:
            search_results = await self.client.batch_search(
                queries,
                max_results=max_results,
            )
        except Exception as e:
            return ToolResult(
                llm_content=f"Web batch search failed: {e}",
                is_error=True,
            )

        results = [result.result[:max_results] for result in search_results]
        result_str = ""
        for i, query in enumerate(queries):
            result_str += f"Query: {query}\n"
            for j, result in enumerate(results[i]):
                result_str += f"Output {j+1}:\n"
                result_str += f"Title: {result['title']}\n"
                result_str += f"URL: {result['url']}\n"
                result_str += f"Snippet: {result['content']}\n"
                result_str += "-----------------------------------\n"


        if len(results) == 0:
            return ToolResult(
                llm_content=f"The search engine processed your query '{queries}' successfully but found no matching results. Try rephrasing with different keywords, broader terms, or check for typos.",
                user_display_content="", # NOTE: to compatible with the current frontend implementation
                is_error=False,
            )
        
        user_display_results =[]
        for result in results:
            user_display_results.extend(result)

        return ToolResult(
            llm_content=result_str,
            user_display_content=json.dumps(user_display_results, indent=2),
            is_error=False,
        )

    async def execute_mcp_wrapper(self, queries: List[str]):
        return await self._mcp_wrapper(
            tool_input={
                "queries": queries,
            }
        )

