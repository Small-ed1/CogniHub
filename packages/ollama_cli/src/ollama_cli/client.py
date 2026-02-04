"""Ollama API client.

This module provides a clean, focused client for interacting with the Ollama API
including model listing, pulling, generation, and chat functionality.
"""

import json
from typing import Any, Dict, Iterator, Optional, List

import requests  # type: ignore

from .errors import OllamaAPIError, OllamaNetworkError, OllamaTimeoutError


class OllamaClient:
    """Client for Ollama API interactions."""
    
    def __init__(self, base_url: str, timeout: int = 60, api_key: Optional[str] = None):
        """Initialize Ollama client.
        
        Args:
            base_url: Base URL for Ollama API
            timeout: Request timeout in seconds
            api_key: Optional API key for authorization
        """
        # Ollama API lives under /api
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        
        # Set up headers with optional API key
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
    
    def _url(self, path: str) -> str:
        """Build full URL for API endpoint.
        
        Args:
            path: API endpoint path (without /api prefix)
            
        Returns:
            Full URL for the endpoint
        """
        path = path.lstrip("/")
        return f"{self.base_url}/api/{path}"
    
    def _post_stream(
        self, path: str, payload: Dict[str, Any]
    ) -> Iterator[Dict[str, Any]]:
        """Stream JSON responses from POST request.
        
        Args:
            path: API endpoint path
            payload: Request payload
            
        Yields:
            JSON response objects
            
        Raises:
            OllamaAPIError: If request fails
        """
        try:
            r = requests.post(
                self._url(path),
                headers=self.headers,
                json=payload,
                stream=True,
                timeout=self.timeout,
            )
            r.raise_for_status()
        except requests.Timeout as e:
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e
        except requests.RequestException as e:
            raise OllamaNetworkError(f"Ollama request failed: {e}") from e
        
        for line in r.iter_lines(decode_unicode=True):
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise OllamaAPIError(f"Invalid JSON response: {e}") from e
    
    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make POST request and return JSON response.
        
        Args:
            path: API endpoint path
            payload: Request payload
            
        Returns:
            JSON response data
            
        Raises:
            OllamaAPIError: If request fails
        """
        try:
            r = requests.post(
                self._url(path),
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except requests.Timeout as e:
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e
        except requests.RequestException as e:
            raise OllamaNetworkError(f"Ollama request failed: {e}") from e
    
    def tags(self) -> Dict[str, Any]:
        """List available local models.
        
        Returns:
            Dictionary with model information under 'models' key
        """
        try:
            r = requests.get(self._url("tags"), headers=self.headers, timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except requests.Timeout as e:
            raise OllamaTimeoutError(f"Ollama request timed out: {e}") from e
        except requests.RequestException as e:
            raise OllamaNetworkError(f"Ollama request failed: {e}") from e
    
    def pull(self, model: str, insecure: bool = False) -> Iterator[Dict[str, Any]]:
        """Pull a model from Ollama registry.
        
        Args:
            model: Model name to pull
            insecure: Skip TLS verification if True
            
        Yields:
            Pull status updates
        """
        payload = {"name": model, "insecure": insecure}
        return self._post_stream("pull", payload)
    
    def generate(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        context: Optional[List[int]] = None,
        options: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
        template: Optional[str] = None,
        stream: bool = False,
    ) -> Iterator[Dict[str, Any]]:
        """Generate text from a model.
        
        Args:
            model: Model name
            prompt: Input prompt
            system: System prompt (optional)
            context: Conversation context (optional)
            options: Model options (optional)
            format: Output format (optional)
            template: Prompt template (optional)
            stream: Whether to stream response
            
        Yields:
            Generation response chunks
        """
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
        }
        
        if system:
            payload["system"] = system
        if context:
            payload["context"] = context
        if options:
            payload["options"] = options
        if format:
            payload["format"] = format
        if template:
            payload["template"] = template
        
        return self._post_stream("generate", payload) if stream else iter([self._post_json("generate", payload)])
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        options: Optional[Dict[str, Any]] = None,
        format: Optional[str] = None,
        template: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Have a conversation with a model.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            model: Model name
            tools: Tool definitions for function calling (optional)
            stream: Whether to stream response
            options: Model options (optional)
            format: Output format (optional)
            template: Prompt template (optional)
            
        Yields:
            Chat response chunks
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        
        if tools:
            payload["tools"] = tools
        if options:
            payload["options"] = options
        if format:
            payload["format"] = format
        if template:
            payload["template"] = template
        
        return self._post_stream("chat", payload) if stream else iter([self._post_json("chat", payload)])
