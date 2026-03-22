import asyncio
import os
from pathlib import Path
from malibu.config import get_settings
from malibu.agent.graph import build_agent
from langchain_core.messages import HumanMessage

async def main():
    cwd = str(Path.cwd())
    settings = get_settings()
    # Disable components that might crash if run natively
    settings.tui_show_welcome = False
    
    # Build agent
    print("Building agent...")
    agent = build_agent(settings=settings, cwd=cwd)
    
    print("Starting astream...")
    config = {"configurable": {"thread_id": "test_session_1"}}
    input_data = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]}
    
    try:
        async for chunk in agent.astream(
            input_data,
            config=config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            print(f"CHUNK TYPE: {type(chunk)}")
            if isinstance(chunk, tuple):
                print(f"CHUNK LEN: {len(chunk)} -> {chunk}")
            else:
                print(f"CHUNK: {chunk}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
