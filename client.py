import sys
import os
import time
import asyncio
from typing import Optional
from contextlib import AsyncExitStack
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv() 

baseUrl = os.getenv("target_base_url")
apiKey = os.getenv("target_api_key")
modelName = os.getenv("target_model_name")

class MCPClient:
    def __init__(self, config_path=None):
        self.sessions = {}  # 存储多个服务器会话
        self.exit_stack = AsyncExitStack()
        # 添加消息历史记录
        self.message_history = []

        self.client = AsyncOpenAI(
            base_url=baseUrl,
            api_key=apiKey,
        )
        self.model_name = modelName
        
        # 配置文件路径
        self.config_path = config_path
        # 加载服务器配置
        self.load_config()
        
    def load_config(self):
        """从配置文件加载服务器配置"""
        # 默认服务器配置，当配置文件不存在或加载失败时使用
        # default_servers = [
        #     {"type": "script", "path": "/home/alpha/projs/pys/mcp-client/servers/simple_add.py", "name": "simple_add"},
        #     {"type": "package", "command": "uvx", "args": ["--default-index", "https://pypi.tuna.tsinghua.edu.cn/simple","mcp-server-fetch"], "name": "mcp-server-fetch"},
        #     {"type": "package", "command": "deno", "args": ["run", "-N","-R=node_modules","-W=node_modules","--node-modules-dir=auto","jsr:@pydantic/mcp-run-python", "stdio"], "name": "code_interpreter"}
        # ]
        
        # self.default_servers = default_servers
        
        # 如果指定了配置文件，尝试加载
        if self.config_path and os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if 'servers' in config:
                        self.default_servers = config['servers']
                        print(f"已从配置文件 {self.config_path} 加载 {len(self.default_servers)} 个服务器配置")
                    else:
                        print(f"配置文件 {self.config_path} 中未找到 'servers' 配置，使用默认配置")
            except Exception as e:
                print(f"加载配置文件 {self.config_path} 时出错: {str(e)}，使用默认配置")
        else:
            if self.config_path:
                print(f"配置文件 {self.config_path} 不存在，使用默认配置")
            else:
                print("未指定配置文件，使用默认配置")

    async def connect_to_server(self, server_type: str, server_path_or_command: str, server_args=None, server_name: Optional[str] = None):
        """连接到MCP服务器，支持脚本文件或已安装的包
        
        Args:
            server_type: 服务器类型，"script"或"package"
            server_path_or_command: 脚本路径或命令名称
            server_args: 命令参数列表
            server_name: 服务器名称，如果未提供则自动生成
        """
        if server_args is None:
            server_args = []
            
        # 生成默认服务器名称（如果未提供）
        if server_name is None:
            if server_type == "script":
                server_name = os.path.basename(server_path_or_command).replace('.py', '')
            else:
                if server_args:
                    server_name = server_args[0]
                else:
                    server_name = server_path_or_command
                
        # 检查是否已连接该服务器
        if server_name in self.sessions:
            print(f"Server '{server_name}' already connected")
            return
        
        # 根据服务器类型设置参数
        if server_type == "script":
            server_params = StdioServerParameters(
                command="python",
                args=[server_path_or_command],
                env=None
            )
        else:  # 包或其他命令类型
            server_params = StdioServerParameters(
                command=server_path_or_command,
                args=server_args,
                env=None
            )

        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        stdio, write = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))

        await session.initialize()

        # 列出可用工具
        response = await session.list_tools()
        tools = response.tools
        print(f"\nConnected to server '{server_name}' with tools:", [tool.name for tool in tools])
        
        # 存储会话信息
        self.sessions[server_name] = {
            "session": session,
            "tools": tools
        }
        
    async def connect_default_servers(self):
        """连接默认配置的服务器"""
        for server in self.default_servers:
            try:
                await self.connect_to_server(
                    server["type"], 
                    server["path"] if server["type"] == "script" else server["command"],
                    server.get("args"),
                    server["name"]
                )
            except Exception as e:
                print(f"Failed to connect to default server '{server['name']}': {str(e)}")


    async def process_query(self, query: str) -> str:
        """使用 LLM 和 MCP 服务器提供的工具处理查询"""
        if not self.sessions:
            raise RuntimeError("Not connected to any server")
            
        # 使用历史消息并添加新的用户消息
        messages = self.message_history.copy()
        messages.append({
            "role": "user",
            "content": query
        })
    
        # 收集所有服务器的工具
        available_tools = []
        server_tool_map = {}  # 用于跟踪工具属于哪个服务器
        
        for server_name, server_info in self.sessions.items():
            for tool in server_info["tools"]:
                # 为工具名称添加服务器前缀以避免冲突
                prefixed_tool_name = f"{server_name}:{tool.name}"
                server_tool_map[prefixed_tool_name] = {
                    "server_name": server_name,
                    "original_tool_name": tool.name
                }
                
                available_tools.append({
                    "type": "function",
                    "function": {
                        "name": prefixed_tool_name,
                        "description": f"[{server_name}] {tool.description}",
                        "parameters": tool.inputSchema
                    }
                })
        
        response = await self.client.chat.completions.create(
            model=self.model_name if self.model_name else "o1",
            messages=messages,
            max_tokens=2048,
            tools=available_tools
        )
        
        final_text = []
        message = response.choices[0].message
        
        # 保存助手回复到历史记录
        self.message_history.append({
            "role": "user",
            "content": query
        })
        
        if message.content:
            self.message_history.append({
                "role": "assistant",
                "content": message.content
            })
            final_text.append(message.content)
    
        while message.tool_calls:
            for tool_call in message.tool_calls:
                prefixed_tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                # 查找工具对应的服务器和原始工具名
                if prefixed_tool_name not in server_tool_map:
                    error_msg = f"Tool '{prefixed_tool_name}' not found in any server"
                    final_text.append(f"[Error: {error_msg}]")
                    continue
                    
                server_info = server_tool_map[prefixed_tool_name]
                server_name = server_info["server_name"]
                original_tool_name = server_info["original_tool_name"]
                
                # 获取对应服务器的会话
                session = self.sessions[server_name]["session"]
                
                # 调用工具
                result = await session.call_tool(original_tool_name, tool_args)
                final_text.append(f"[Calling tool '{prefixed_tool_name}' with args '{tool_args}']")
    
                tool_call_message = {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": prefixed_tool_name,
                                "arguments": json.dumps(tool_args)
                            }
                        }
                    ]
                }
                
                tool_result_message = {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": str(result.content)
                }
                
                # 添加工具调用和结果到历史和当前消息
                messages.append(tool_call_message)
                messages.append(tool_result_message)

            response = await self.client.chat.completions.create(
                messages=messages,
                model=self.model_name if self.model_name else "o1",
                max_tokens=2048,
            )

            message = response.choices[0].message
            if message.content:
                final_text.append(message.content)
                # 保存最终助手回复到历史记录
                self.message_history.append({
                    "role": "assistant",
                    "content": message.content
                })
    
        return "\n".join(final_text)
    
    async def simulate_stream(self, content):
        """Simulate streaming output with variable speed and natural pauses"""
        import random
        
        # Split content into chunks (words and punctuation)
        chunks = []
        current_chunk = ""
        
        for char in content:
            current_chunk += char
            # Create natural breaks at spaces and punctuation
            if char in [' ', '.', ',', '!', '?', ':', ';', '\n']:
                chunks.append(current_chunk)
                current_chunk = ""
        
        if current_chunk:  # Add any remaining text
            chunks.append(current_chunk)
        
        for chunk in chunks:
            print(chunk, end="", flush=True)
            
            # Variable delay based on content
            if '\n' in chunk:
                # Longer pause at line breaks
                await asyncio.sleep(0.08)
            elif any(p in chunk for p in ['.', '!', '?']):
                # Medium pause at sentence endings
                await asyncio.sleep(0.07)
            elif any(p in chunk for p in [',', ':', ';']):
                # Short pause at other punctuation
                await asyncio.sleep(0.06)
            else:
                # Brief random delay for regular text to simulate typing speed variations
                await asyncio.sleep(random.uniform(0.01, 0.04))

    async def chat_loop(self):
        print("\nMCP Client Started!")
        print("Type your queries, 'clear' to clear conversation history, or 'q' to exit.")

        while True:
            query = input("\nUser: ").strip()
            if query.lower() == 'q':
                break
            elif query.lower() == 'clear':
                self.message_history = []
                print("对话历史已清除")
                continue
                
            response = await self.process_query(query)
            await self.simulate_stream(response)
            
    async def cleanup(self):
        await self.exit_stack.aclose() 

    
async def main():
    # 处理命令行参数
    config_path = None
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    
    # 检查第一个参数是否是配置文件路径
    if args and args[0].endswith('.json'):
        config_path = args[0]
        args = args[1:]  # 移除配置文件参数
    
    client = MCPClient(config_path)
    try:
        # 首先连接默认服务器
        print("Connecting to default servers...")
        await client.connect_default_servers()
        
        # 处理其他命令行参数（如果有）
        i = 0
        while i + 2 < len(args):
            # 格式: command args name
            command = args[i]
            args_str = args[i+1]
            server_name = args[i+2]
            
            # 处理参数字符串，保留原始格式
            if args_str.startswith('"') and args_str.endswith('"'):
                # 去掉引号
                args_str = args_str[1:-1]
            
            # 将参数字符串拆分为列表
            server_args = args_str.split()
            
            print(f"Connecting to server with command '{command}', args '{server_args}', name '{server_name}'...")
            await client.connect_to_server("package", command, server_args, server_name)
            i += 3
        
        # 检查是否成功连接了任何服务器
        if not client.sessions:
            print("Failed to connect to any servers. Exiting...")
            return
            
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
