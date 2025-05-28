"""
main.py

Main entrypoint for the agent. Handles server setup, configuration loading, and orchestration of the agent lifecycle.
"""

import os
import logging
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import AgentSession
from mcp_client import MCPClientWithAuth, MCPServerSse, MCPServerStdIO
from mcp_client.agent_tools import MCPToolsIntegration
import fnmatch
from agent_core import FunctionAgent
from mcp_config import load_mcp_config, expand_env_vars
from a2a import A2AServerConfig
from tool_integration import filtered_prepare_dynamic_tools
from utils import sanitize_tool_name
import asyncio

async def entrypoint(ctx: JobContext):
    """
    Main entrypoint for the LiveKit agent application.
    Loads configuration, sets up MCP and A2A servers, prepares tools, and starts the agent session.
    """
    # Load MCP server configs
    mcp_configs = load_mcp_config()
    mcp_servers = []
    allowed_tools_map = {}
    
    for conf in mcp_configs:
        server_type = conf.get("type", "mcp")
        headers = {}
        for k, v in conf.get("headers", {}).items():
            headers[k] = expand_env_vars(v)
        server_name = conf.get("name", "")
        server_url = conf.get("url", "")

        if server_type == "mcp":
            server = await create_mcp_server(conf, headers, server_name, server_url)
        elif server_type == "a2a":
            server = await create_a2a_server(conf, headers, server, server_name, server_url)
        else:
            raise ValueError(f"Unknown server type: {server_type}")

        mcp_servers.append(server)
        if "allowed_tools" in conf:
            allowed_tools_map[server_name] = set(conf["allowed_tools"])

    # Patch MCPToolsIntegration to filter tools per server
    MCPToolsIntegration.prepare_dynamic_tools = lambda mcp_servers, convert_schemas_to_strict=True, auto_connect=True: filtered_prepare_dynamic_tools(mcp_servers, allowed_tools_map, convert_schemas_to_strict, auto_connect)

    agent = await MCPToolsIntegration.create_agent_with_tools(
        agent_class=FunctionAgent,
        mcp_servers=mcp_servers
    )

    await ctx.connect()
    session = AgentSession()
    print("👋 Agent is ready! Say 'hello' to begin.")
    # Optionally, greet via voice if possible
    if hasattr(agent, 'speak') and callable(getattr(agent, 'speak', None)):
        await agent.speak("Hello! I am your promotion assistant. How can I help you today?")

    # Robust session loop with reconnection
    max_retries = 10
    retry_delay = 3
    for attempt in range(1, max_retries + 1):
        try:
            await session.start(agent=agent, room=ctx.room)
            break  # Exit if session ends cleanly
        except Exception as exc:
            logging.error(f"Agent session error (attempt {attempt}/{max_retries}): {exc}")
            # Reconnect all MCP servers
            for server in mcp_servers:
                try:
                    await server.connect()
                except Exception as conn_exc:
                    logging.error(f"Failed to reconnect MCP server {getattr(server, 'name', '')}: {conn_exc}")
            if attempt < max_retries:
                logging.info(f"Retrying agent session in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logging.error("Max session retries reached. Exiting.")
                raise


async def create_a2a_server(conf, headers, server, server_name, server_url):
    # Only set Authorization header if auth is enabled in config
    env_var_name = conf.get("auth", {}).get("env_var")
    if env_var_name:
        jwt_token = os.environ.get(env_var_name)
        if jwt_token:
            headers["Authorization"] = f"Bearer {jwt_token}"
            print(f"A2A server '{server_name}' Authorization header: {headers['Authorization']}")
        else:
            print(
                f"Warning: JWT env var '{env_var_name}' is configured for '{server_name}' but not set in environment.")
    else:
        # Ensure no Authorization header is present if auth is not enabled
        headers.pop("Authorization", None)
    server = A2AServerConfig(
        base_url=server_url,
        headers=headers,
        name=server_name
    )
    return server


async def create_mcp_server(conf, headers, server_name, server_url):
    if "command" in conf:
        command = conf["command"]
        logging.info(f"Using {command} MCP")
        server = MCPServerStdIO(
            command,
            args=conf.get("args", []),
            env=conf.get("env", {}),
            name=server_name
        )
    if "url" in conf:
        if "auth" in conf:
            auth_type = conf["auth"].get("type", "")
            env_var_name = conf["auth"].get("env_var", "")
            secret_key = os.environ.get(env_var_name, "")
            if secret_key:
                logging.info(f"Using {env_var_name} for authentication with {server_name}")
                client = MCPClientWithAuth(
                    url=server_url,
                    auth_type=auth_type,
                    secret_key=secret_key,
                    headers=headers,
                    name=server_name
                )
                server = client.server
            else:
                logging.warning(f"{env_var_name} not set, authentication will not be used for {server_name}")
                server = MCPServerSse(
                    params={
                        "url": server_url,
                        "headers": headers
                    },
                    cache_tools_list=True,
                    name=server_name
                )
        else:
            server = MCPServerSse(
                params={"url": server_url, "headers": headers},
                cache_tools_list=True,
                name=server_name
            )
    return server


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint)) 