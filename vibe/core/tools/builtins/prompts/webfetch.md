Fetches content from a specified URL and converts HTML to markdown for readability.
Use this tool when you need to retrieve and analyze web content.

- Prefer a more specialized tool over `web_fetch` when one is available.
- Uses Tavily extract first when configured, then falls back to raw HTTP fetch.
- The Tavily key is `TAVILY_API_KEY`, and the provider preference can be changed in `/config`.
- You can pass `prompt` for focused extraction.
- The result includes `provider` so you can tell whether Tavily or raw HTTP served the content.
- URLs must be valid.
- Read-only: does not modify any files.
