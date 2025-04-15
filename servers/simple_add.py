from typing import Any
import httpx
from mcp.server.fastmcp import FastMCP
import asyncio
# 初始化 FastMCP 服务器
mcp = FastMCP("simple_add")

# 定义一个简单的加法工具
@mcp.tool()
async def simple_add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    mcp.run(transport="stdio")