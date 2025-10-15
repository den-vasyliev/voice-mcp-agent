"""
tool_integration.py

Handles dynamic tool preparation and MCPToolsIntegration patching for both MCP and A2A servers.
"""

import fnmatch
import logging
from mcp_client.agent_tools import MCPToolsIntegration
from a2a import A2AServerConfig, send_a2a_task
import re

# Patch MCPToolsIntegration to filter tools per server
async def filtered_prepare_dynamic_tools(mcp_servers, allowed_tools_map, convert_schemas_to_strict=True, auto_connect=True):
    """
    Prepare and filter dynamic tools for MCP and A2A servers, applying allowed tool patterns per server.
    Returns a list of decorated tool objects ready for use by the agent.
    """
    prepared_tools = []
    for server in mcp_servers:
        name = getattr(server, "name", None)
        allowed = allowed_tools_map.get(name)
        # Branch for A2AServerConfig
        if isinstance(server, A2AServerConfig):
            skills = await server.list_tools()
            from mcp_client.util import FunctionTool
            import json
            for skill in skills:
                # Minimal JSON schema: one string parameter 'prompt'
                params_json_schema = {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Prompt for the A2A skill"}
                    },
                    "required": ["prompt"]
                }
                async def on_invoke_tool(context, input_json, _server=server, _skill=skill):
                    args = json.loads(input_json) if input_json else {}
                    prompt = args.get("prompt", "")
                    # Use the async method directly instead of the legacy sync function
                    return await _server.send_task_async(prompt)
                ft = FunctionTool(
                    name=re.sub(r'[^a-zA-Z0-9_-]', '_', skill.get("name", skill.get("id", "unknown_skill"))),
                    description=skill.get("description", ""),
                    params_json_schema=params_json_schema,
                    on_invoke_tool=on_invoke_tool,
                    strict_json_schema=False,
                )
                decorated_tool = MCPToolsIntegration._create_decorated_tool(ft)
                prepared_tools.append(decorated_tool)
            continue
        # MCP logic (unchanged)
        tools = await server.list_tools()
        if allowed is not None:
            allowed_patterns = list(allowed)
            tools = [t for t in tools if any(fnmatch.fnmatch(t.name, pat) for pat in allowed_patterns)]
        from mcp_client.util import MCPUtil
        mcp_tools = [MCPUtil.to_function_tool(t, server, convert_schemas_to_strict) for t in tools]
        for tool_instance in mcp_tools:
            try:
                decorated_tool = MCPToolsIntegration._create_decorated_tool(tool_instance)
                prepared_tools.append(decorated_tool)
            except Exception as e:
                logging.getLogger("mcp-agent-tools").error(f"Failed to prepare tool '{tool_instance.name}': {e}")
    return prepared_tools 