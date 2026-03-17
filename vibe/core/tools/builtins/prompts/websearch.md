Use `web_search` to find current information from the web.
It uses Tavily first and falls back to DDGS if Tavily is unavailable.
The Tavily key is `TAVILY_API_KEY`, and the provider preference can be changed in `/config`.
The result includes:
- `provider`: which backend served the result
- `answer`: optional provider-generated answer
- `hits`: provider-agnostic search hits with title, URL, snippet, and optional score

Always reference the source URLs you rely on when presenting information to the user.

**Query Best Practices:**
- Avoid relative time terms ("latest", "today", "this week") - resolve to actual dates when possible
- Be specific and use concrete terms rather than vague queries

**When to use:**
- User asks about recent events or explicitly asks to search the web
- Documentation, APIs, or libraries may have been updated since training cutoff
- Verifying facts that could be outdated (versions, deprecations, breaking changes)
- Looking up specific error messages or issues that may have known solutions
- User mentions a library, framework, or version you're not familiar with

**When NOT to use:**
- General programming concepts and patterns (use training knowledge)
- Searching the local codebase (use `grep` or file search instead)
- Static reference information unlikely to change (math, algorithms, language syntax)
- Information you're already confident about and is unlikely to have changed

**Using results:**
- Stay critical - web content may be outdated, wrong, or misleading
- Cross-reference multiple sources when possible
- Prefer official documentation over third-party sources
- Always cite your sources so the user can verify
