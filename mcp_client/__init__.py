from mcp_client.server import MCPServerSse, MCPServer
from mcp_client.auth import HMACAuth, create_auth_middleware
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
import logging

logger = logging.getLogger("mcp-agent-tools")

# Define MCPClientStdIO class with command and args
class MCPServerStdIO(MCPServer):
    def __init__(self, command, args=None, env=None, name=None):
        """
        Create an MCP client for a standard I/O server.

        Args:
            command: The command to run the MCP server
            args: Optional list of arguments for the command
            env: Optional environment variables for the command
            name: Optional name for the client
        """
        self.connected = False
        self.session = None
        self.server_params = StdioServerParameters(
            command=command,  # Executable
            args=args or [],  # Optional command line arguments
            env=env or {},  # Optional environment variables
        )
        self._name = name
        self._tools = None  # Cache for tools

    def name(self):
        """ Return the name of the MCP server.
        """
        return self._name

    async  def connect(self, name=None):
        """ Connect to the MCP server using standard I/O.
        """
        logger.info(f"Connecting to MCP server with command: {self.name} with server_params: {self.server_params}")
        self._stdio_context = stdio_client(self.server_params)
        read, write = await self._stdio_context.__aenter__()
        self._session_context = ClientSession(read, write)
        self.session = await self._session_context.__aenter__()
        await self.session.initialize()
        self.connected = True
        logger.info(f"Connected to MCP server: {self.name()}")

    async def disconnect(self):
        """ Disconnect from the MCP server.
        """
        if self.connected:
            if hasattr(self, '_session_context'):
                await self._session_context.__aexit__(None, None, None)
            if hasattr(self, '_stdio_context'):
                await self._stdio_context.__aexit__(None, None, None)
            self.connected = False
            self.session = None


    async def list_tools(self):
        """ List available tools from the MCP server.
        Returns:
            List of tool names available on the server.
        """
        if self._tools is not None:
            # Return cached tools if available
            logger.info(f"Returning cached tools for {self.name}")
            return self._tools

        logger.info(f"list_tools: {self._name}")
        res = await self.session.list_tools()
        self._tools = res.tools  # Cache the tools for later use
        return self._tools


    async def list_prompts(self):
        """ List available prompts from the MCP server.
        Returns:
            List of prompt names available on the server.
        """
        logger.info(f"list_tools: {self.name}")
        return await self.session.list_prompts()


    async def call_tool(self, tool_name, arguments=None):
        """ Call a tool on the MCP server.
        Args:
            tool_name: The name of the tool to call.
            arguments: Optional arguments to pass to the tool
        Returns:
            The result of the tool call.
        """
        logger.info(f"call_tool: {self.name}")
        return self.session.call_tool(tool_name, arguments=arguments or {})

# Define MCPClientWithAuth class here since client.py doesn't exist
class MCPClientWithAuth:
    def __init__(self, url, auth_type, secret_key, headers=None, name=None):
        """
        Create an authenticated MCP client.
        
        Args:
            url: The URL of the MCP server
            secret_key: The secret key for authentication
            headers: Additional headers to include in requests
            name: Optional name for the client
        """
        from mcp_client.auth import create_auth_middleware
        
        self.url = url
        self.name = name
        self.headers = headers or {}

        middleware = []

        # Create authentication middleware
        if auth_type == "secret_key":
            auth_middleware = create_auth_middleware(secret_key)
            middleware.append(auth_middleware)

        if auth_type == "jwt":
            auth_middleware = create_auth_middleware(secret_key)
            middleware.append(auth_middleware)

        # Create server with authentication middleware
        self.server = MCPServerSse(
            params={
                "url": url,
                "headers": self.headers
            },
            cache_tools_list=True,
            name=name,
            middleware=middleware
        )

__all__ = ["MCPServerStdIO", "MCPClientWithAuth", "MCPServerSse", "MCPServer", "HMACAuth", "create_auth_middleware"]