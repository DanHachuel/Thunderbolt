from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping

MCP_URL = "https://mcp.canva.com/mcp"
PROTOCOL_VERSION = "2025-06-18"


class CanvaMCPError(RuntimeError):
    pass


class CanvaMCPClient:
    """Direct local MCP client for Canva, using the official mcp-remote adapter."""

    def __init__(self, *, endpoint: str = MCP_URL, timeout: int = 120) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._next_id = 0
        self._process: subprocess.Popen[str] | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._reader: threading.Thread | None = None

    def _command(self) -> list[str]:
        executable = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
        return [executable, "--yes", "mcp-remote@latest", self.endpoint]

    def connect(self) -> dict[str, Any]:
        if self._process and self._process.poll() is None:
            return {}
        env = {
            **os.environ,
            "MCP_REMOTE_QUIET": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
        self._process = subprocess.Popen(
            self._command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self._reader = threading.Thread(target=self._read_stdout, name="canva-mcp-reader", daemon=True)
        self._reader.start()
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "Thunderbolt", "version": "0.5.8"},
            },
        )
        self.notify("notifications/initialized", {})
        return result

    def _read_stdout(self) -> None:
        assert self._process and self._process.stdout
        for line in self._process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                self._messages.put(message)

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": dict(params)})

    def _send(self, message: Mapping[str, Any]) -> None:
        if not self._process or self._process.poll() is not None or not self._process.stdin:
            raise CanvaMCPError("A sessão directa Canva MCP não está ligada.")
        self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

    def request(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                message = self._messages.get(timeout=0.5)
            except queue.Empty:
                if self._process and self._process.poll() is not None:
                    raise CanvaMCPError("O processo mcp-remote terminou antes de responder.")
                continue
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                error = message["error"]
                raise CanvaMCPError(str(error.get("message") or error))
            result = message.get("result")
            return result if isinstance(result, dict) else {"result": result}
        raise CanvaMCPError(f"Timeout na operação MCP {method}.")

    def tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        tools = result.get("tools")
        return [dict(tool) for tool in tools if isinstance(tool, Mapping)] if isinstance(tools, list) else []

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": dict(arguments or {})})
        if result.get("isError"):
            raise CanvaMCPError(self._text(result.get("content")) or "A ferramenta Canva devolveu erro.")
        return result

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, list):
            return "\n".join(str(item.get("text") or "") for item in content if isinstance(item, Mapping)).strip()
        return str(content or "").strip()

    def find_tool(self, *names: str) -> str:
        available = {str(tool.get("name")) for tool in self.tools()}
        for name in names:
            if name in available:
                return name
        raise CanvaMCPError(f"A sessão Canva MCP não disponibiliza nenhuma destas operações: {', '.join(names)}.")

    def close(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def __enter__(self) -> "CanvaMCPClient":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


__all__ = ["CanvaMCPClient", "CanvaMCPError", "MCP_URL"]
