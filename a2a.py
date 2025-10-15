"""
a2a.py

Provides the A2AServerConfig class for A2A server integration and the send_a2a_task function for sending tasks to A2A agents.
Refactored for Google ADK compatibility and improved error handling.
"""

import asyncio
import json
import uuid
import httpx
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class TaskState(Enum):
    """A2A task states as defined in the protocol."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class A2AMessage:
    """Represents an A2A message part."""
    type: str
    text: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

@dataclass
class A2ATask:
    """Represents an A2A task."""
    id: str
    session_id: str
    message: Dict[str, Any]
    accepted_output_modes: List[str] = None
    
    def __post_init__(self):
        if self.accepted_output_modes is None:
            self.accepted_output_modes = ["text"]

class A2AError(Exception):
    """Base exception for A2A protocol errors."""
    pass

class A2AConnectionError(A2AError):
    """Raised when connection to A2A agent fails."""
    pass

class A2ATaskError(A2AError):
    """Raised when task execution fails."""
    pass

class A2AServerConfig:
    """
    Represents an A2A server configuration for tool integration.
    Provides methods to list available tools and connect (no-op).
    Refactored for Google ADK compatibility with improved error handling.
    """
    def __init__(self, base_url: str, headers: Optional[Dict[str, str]], name: str):
        self.type = "a2a"
        self.base_url = base_url.rstrip('/')
        self.headers = headers or {}
        self.name = name
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create an async HTTP client with improved timeout configuration."""
        if self._client is None:
            # Use more granular timeout configuration
            timeout = httpx.Timeout(
                connect=10.0,  # Connection timeout
                read=60.0,     # Read timeout (increased for long-running tasks)
                write=10.0,    # Write timeout
                pool=5.0       # Pool timeout
            )
            self._client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                follow_redirects=True
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        Fetch the list of available skills/tools from the A2A agent.
        Returns a list of skills with improved error handling.
        """
        agent_card_url = f"{self.base_url}/.well-known/agent.json"
        
        try:
            client = await self._get_client()
            response = await client.get(agent_card_url, headers=self.headers)
            
            if response.status_code != 200:
                raise A2AConnectionError(
                    f"Failed to get agent card: {response.status_code} - {response.text}"
                )
            
            agent_card = response.json()
            skills = agent_card.get("skills", [])
            
            logger.info(f"Retrieved {len(skills)} skills from A2A agent {self.name}")
            return skills
            
        except httpx.RequestError as e:
            raise A2AConnectionError(f"Network error connecting to A2A agent: {e}")
        except json.JSONDecodeError as e:
            raise A2AConnectionError(f"Invalid JSON response from agent card: {e}")

    async def connect(self):
        """
        No-op for A2A servers, required for interface compatibility.
        """
        return

    async def send_task_async(self, user_text: str, session_id: Optional[str] = None, max_retries: int = 2) -> str:
        """
        Send a task to an A2A agent asynchronously and return the agent's reply as text.
        Updated to use the correct A2A protocol based on Google ADK documentation.
        Includes retry logic for handling temporary network issues.
        """
        if not session_id:
            session_id = str(uuid.uuid4())
        
        task_id = str(uuid.uuid4())
        
        # Create message following A2A protocol
        # Based on testing, A2A uses message/send with parts using "kind" field
        message_payload = {
            "message": {
                "role": "user",
                "parts": [
                    {"kind": "text", "text": user_text}
                ]
            }
        }
        
        jsonrpc_payload = {
            "jsonrpc": "2.0",
            "id": task_id,
            "method": "message/send",
            "params": message_payload
        }
        
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                client = await self._get_client()
                # Try the main A2A endpoint first
                a2a_url = f"{self.base_url}/"
                
                logger.info(f"Sending A2A message to {a2a_url} (attempt {attempt + 1}/{max_retries + 1})")
                response = await client.post(
                    a2a_url, 
                    json=jsonrpc_payload, 
                    headers=self.headers
                )
                
                logger.info(f"A2A response status: {response.status_code}")
                
                if response.status_code != 200:
                    raise A2ATaskError(
                        f"Task request failed: {response.status_code} - {response.text}"
                    )
                
                task_response = response.json()
                
                # Check for JSON-RPC errors
                if "error" in task_response:
                    error = task_response["error"]
                    raise A2ATaskError(f"JSON-RPC error: {error.get('message', 'Unknown error')}")
                
                # Process the response - A2A protocol returns task result with artifacts
                result = task_response.get("result", {})
                
                # Check if task completed successfully
                status = result.get("status", {})
                if status.get("state") == "completed":
                    # Extract response from artifacts
                    artifacts = result.get("artifacts", [])
                    if artifacts:
                        artifact = artifacts[0]  # Get first artifact
                        parts = artifact.get("parts", [])
                        if parts:
                            agent_reply_text = ""
                            for part in parts:
                                if part.get("kind") == "text" and "text" in part:
                                    agent_reply_text += part["text"]
                            logger.info(f"A2A response extracted from artifacts: {len(agent_reply_text)} chars")
                            return agent_reply_text if agent_reply_text else "No text content in response"
                    
                    # Fallback: check history for agent messages
                    history = result.get("history", [])
                    for msg in reversed(history):  # Look for most recent agent message
                        if msg.get("role") == "agent":
                            parts = msg.get("parts", [])
                            if parts:
                                agent_reply_text = ""
                                for part in parts:
                                    if part.get("kind") == "text" and "text" in part:
                                        agent_reply_text += part["text"]
                                logger.info(f"A2A response extracted from history: {len(agent_reply_text)} chars")
                                return agent_reply_text if agent_reply_text else "No text content in response"
                    
                    return "Task completed but no response found"
                elif status.get("state") == "failed":
                    error_msg = status.get("message", {})
                    if isinstance(error_msg, dict) and "parts" in error_msg:
                        parts = error_msg["parts"]
                        if parts:
                            error_text = ""
                            for part in parts:
                                if part.get("kind") == "text" and "text" in part:
                                    error_text += part["text"]
                            raise A2ATaskError(f"Task failed: {error_text}")
                    raise A2ATaskError(f"Task failed: {status}")
                else:
                    return f"Task did not complete. Status: {status}"
                    
            except httpx.TimeoutException as e:
                last_exception = e
                logger.warning(f"A2A request timed out (attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    logger.error(f"A2A request timed out after {max_retries + 1} attempts")
                    raise A2AConnectionError(f"Request timed out after {max_retries + 1} attempts. The A2A agent may be overloaded or experiencing issues.")
            except httpx.ConnectError as e:
                last_exception = e
                logger.warning(f"A2A connection error (attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    logger.error(f"A2A connection failed after {max_retries + 1} attempts")
                    raise A2AConnectionError(f"Failed to connect to A2A agent after {max_retries + 1} attempts: {e}")
            except httpx.RequestError as e:
                last_exception = e
                logger.warning(f"A2A request error (attempt {attempt + 1}): {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    logger.error(f"A2A request failed after {max_retries + 1} attempts")
                    raise A2AConnectionError(f"Network error sending task to A2A agent after {max_retries + 1} attempts: {e}")
            except json.JSONDecodeError as e:
                logger.error(f"A2A JSON decode error: {e}")
                raise A2AConnectionError(f"Invalid JSON response from task endpoint: {e}")
            except A2ATaskError:
                # Don't retry task errors, they're not network issues
                raise
        
        # This should never be reached, but just in case
        raise A2AConnectionError(f"Unexpected error after {max_retries + 1} attempts: {last_exception}")

    def _extract_agent_response(self, result_obj: Dict[str, Any]) -> str:
        """Extract text response from agent result object."""
        messages = result_obj.get("messages", [])
        
        # Handle case where message is in status
        if not messages and "status" in result_obj and "message" in result_obj["status"]:
            agent_message = result_obj["status"]["message"]
            messages = [agent_message]
        
        if messages:
            agent_message = messages[-1]
            agent_reply_text = ""
            
            for part in agent_message.get("parts", []):
                if "text" in part:
                    agent_reply_text += part["text"]
            
            return agent_reply_text if agent_reply_text else "No text content in response"
        else:
            return "No messages in response!"

# Legacy function for backward compatibility
def send_a2a_task(agent_base_url: str, user_text: str, headers: Optional[Dict[str, str]] = None) -> str:
    """
    Send a task to an A2A agent and return the agent's reply as text.
    Legacy synchronous function for backward compatibility.
    Raises RuntimeError on failure or incomplete response.
    """
    import requests
    
    try:
        # Check if we're already in an event loop
        try:
            asyncio.get_running_loop()
            # We're in an async context, we need to use a different approach
            # Use requests directly for synchronous operation
            return _send_a2a_task_sync(agent_base_url, user_text, headers)
        except RuntimeError:
            # No event loop running, safe to use async
            config = A2AServerConfig(agent_base_url, headers, "legacy")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(config.send_task_async(user_text))
                return result
            finally:
                loop.close()
            
    except A2AError as e:
        raise RuntimeError(f"A2A task failed: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error: {e}")


def _send_a2a_task_sync(agent_base_url: str, user_text: str, headers: Optional[Dict[str, str]] = None) -> str:
    """
    Synchronous implementation using requests for when we're already in an async context.
    Updated to use the correct A2A protocol based on Google ADK documentation.
    """
    import requests
    
    # Create message following A2A protocol
    # Based on testing, A2A uses message/send with parts using "kind" field
    task_id = str(uuid.uuid4())
    
    message_payload = {
        "message": {
            "role": "user",
            "parts": [
                {"kind": "text", "text": user_text}
            ]
        }
    }
    
    jsonrpc_payload = {
        "jsonrpc": "2.0",
        "id": task_id,
        "method": "message/send",
        "params": message_payload
    }
    
    # Send the conversation message to the main A2A endpoint
    a2a_url = f"{agent_base_url}/"
    try:
        result = requests.post(a2a_url, json=jsonrpc_payload, headers=headers, timeout=60)
        if result.status_code != 200:
            raise RuntimeError(f"Task request failed: {result.status_code}, {result.text}")
    except requests.exceptions.Timeout:
        raise RuntimeError("Request timed out after 60 seconds. The A2A agent may be overloaded or experiencing issues.")
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Failed to connect to A2A agent: {e}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Network error sending task to A2A agent: {e}")
    
    task_response = result.json()
    
    # Check for JSON-RPC errors
    if "error" in task_response:
        error = task_response["error"]
        raise RuntimeError(f"JSON-RPC error: {error.get('message', 'Unknown error')}")
    
    # Process the response - A2A protocol returns task result with artifacts
    result_obj = task_response.get("result", {})
    
    # Check if task completed successfully
    status = result_obj.get("status", {})
    if status.get("state") == "completed":
        # Extract response from artifacts
        artifacts = result_obj.get("artifacts", [])
        if artifacts:
            artifact = artifacts[0]  # Get first artifact
            parts = artifact.get("parts", [])
            if parts:
                agent_reply_text = ""
                for part in parts:
                    if part.get("kind") == "text" and "text" in part:
                        agent_reply_text += part["text"]
                return agent_reply_text if agent_reply_text else "No text content in response"
        
        # Fallback: check history for agent messages
        history = result_obj.get("history", [])
        for msg in reversed(history):  # Look for most recent agent message
            if msg.get("role") == "agent":
                parts = msg.get("parts", [])
                if parts:
                    agent_reply_text = ""
                    for part in parts:
                        if part.get("kind") == "text" and "text" in part:
                            agent_reply_text += part["text"]
                    return agent_reply_text if agent_reply_text else "No text content in response"
        
        return "Task completed but no response found"
    elif status.get("state") == "failed":
        error_msg = status.get("message", {})
        if isinstance(error_msg, dict) and "parts" in error_msg:
            parts = error_msg["parts"]
            if parts:
                error_text = ""
                for part in parts:
                    if part.get("kind") == "text" and "text" in part:
                        error_text += part["text"]
                raise RuntimeError(f"Task failed: {error_text}")
        raise RuntimeError(f"Task failed: {status}")
    else:
        return f"Task did not complete. Status: {status}"


# Google ADK Integration Helper Functions
async def create_a2a_client(base_url: str, headers: Optional[Dict[str, str]] = None, name: str = "a2a-client") -> A2AServerConfig:
    """
    Create an A2A client for Google ADK integration.
    Returns a configured A2AServerConfig instance.
    """
    return A2AServerConfig(base_url, headers, name)


async def send_a2a_message(client: A2AServerConfig, message: str, session_id: Optional[str] = None) -> str:
    """
    Send a message to an A2A agent using the provided client.
    Google ADK compatible async function.
    """
    return await client.send_task_async(message, session_id)


def create_a2a_message_parts(text: str, message_type: str = "text") -> List[Dict[str, Any]]:
    """
    Create A2A message parts for Google ADK integration.
    """
    return [{"type": message_type, "text": text}]


def create_a2a_task_payload(task_id: str, session_id: str, message_parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create A2A task payload following Google ADK standards.
    """
    return {
        "id": task_id,
        "sessionId": session_id,
        "acceptedOutputModes": ["text"],
        "message": {
            "role": "user",
            "parts": message_parts
        }
    } 