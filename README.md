# OpenAI API Compitable MCP Client

## Introduction
The openai agent sdk has been acessed to the mcp-servers recently, However, the openai api is more flexible and general. This project aims to provide a simple and easy to use mcp-client to access the openai-api-compitable servers(local and cloud) and mcp-servers.


## Features
- Support General Local (vLLM, LMDeploy, Llama.cpp, SGLang, etc.)  or Cloud (OpenAI, Google Gemini, DashScope, etc.) OpenAI API Compitable LLM Server 
- Support existing MCP-server or user defined MCP-server by simple py script.

## Usage
```bash
uv run client.py config.json 
```   
## How to add new MCP-servers
User could modify the config to add your own mcp-server, the format is `command[uvx|npx|python|deno]` + `args` + `mcp-server-name`. Here is an example:
```plaintext
{
  "servers": 
    [
        {
            "type": 
                "script", 
            "path": 
                "/home/alpha/projs/pys/mcp-client/servers/simple_add.py", 
            "name": 
                "simple_add"
        },

        {
            "type": 
                "package", 
            "command": 
                "uvx", 
            "args": 
                [
                    "--default-index", 
                    "https://pypi.tuna.tsinghua.edu.cn/simple", 
                    "mcp-server-fetch"
                ], 
            "name": 
                "mcp-server-fetch"
        },

        {
            "type": 
                "package", 
            "command": 
                "deno", 
            "args": 
                [
                    "run", 
                    "-N", 
                    "-R=node_modules", 
                    "-W=node_modules", 
                    "--node-modules-dir=auto", 
                    "jsr:@pydantic/mcp-run-python", 
                    "stdio"
                ], 
            "name": 
                "code_interpreter"
        }
    ]
}

```
