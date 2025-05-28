import logging
from mcp_client import MCPClientWithAuth, MCPServerSse, MCPServerStdIO

logger = logging.getLogger("mcp-agent-tools")

#simple main test
if __name__ == "__main__":
    #test
    name = "Docker_MCP_Server"
    command = "/usr/local/bin/docker"
    args = ["run", "-i", "--rm", "alpine/socat", "STDIO", "TCP:host.docker.internal:8811"]

    # Set up logging
    logging.basicConfig(level=logging.INFO)
    import asyncio

    async def run():
        #docker run -i --rm alpine/socat STDIO TCP:host.docker.internal:8811
        logging.info(f"Starting Docker MCP Server {command}{args}")
        docker_mcp = MCPServerStdIO(name=name, command=command, args=args)
        try:
            await docker_mcp.connect()
            tools = await docker_mcp.list_tools()
            print(f"Found {len(tools)} tools:")
            for tool in tools:
                print(f"Tool: {tool.name}, Description: {tool.description}")
        finally:
            await docker_mcp.disconnect()

    asyncio.run(run())