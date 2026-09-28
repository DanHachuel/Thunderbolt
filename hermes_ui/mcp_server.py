from __future__ import annotations

import atexit
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import storage
from .domain import create_batch, create_tasks_for_batch, pipeline_summary

LOGGER = logging.getLogger(__name__)
MCP_ENDPOINT_PATH = "/mcp"
MCP_HEALTH_PATH = "/health"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3031
DEFAULT_PROTOCOL_VERSION = "2025-06-18"


def _version() -> str:
    try:
        package = json.loads((Path(__file__).resolve().parents[1] / "package.json").read_text(encoding="utf-8"))
        return str(package.get("version") or "")
    except (OSError, json.JSONDecodeError):
        return ""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _channel_public(channel: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id", "name", "url", "handle", "description", "thumbnail_url", "subscriber_count",
        "video_count", "view_count", "metrics_source", "last_youtube_sync", "language",
        "blueprint_id", "default_blueprint_id", "style_wide", "voice", "default_voice",
        "automation_on", "automation_time", "active", "daily_limit", "backlog_total",
        "created_at", "updated_at",
    )
    return {key: channel.get(key) for key in allowed if key in channel}


def _task_public(task: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id", "batch_id", "creation_mode", "channel_id", "channel_name", "topic", "language",
        "format", "style_wide", "style_ia", "music_mode", "music_source", "background_mode",
        "blueprint_id", "voice", "automation_on", "automation_time", "stage", "state",
        "progress", "error", "created_at", "updated_at",
    )
    return {key: task.get(key) for key in allowed if key in task}


def _list_blueprints() -> list[dict[str, Any]]:
    files = storage.list_blueprint_files()
    return [
        {
            "id": path.stem,
            "name": path.stem,
            "filename": path.name,
            "category": path.parent.name,
        }
        for path in files
    ]


def _tool_definitions(write_enabled: bool) -> list[dict[str, Any]]:
    tools = [
        {
            "name": "thunderbolt_get_status",
            "title": "Thunderbolt — estado da pipeline",
            "description": "Obtém o resumo actual de canais e tarefas do Thunderbolt.",
            "inputSchema": {"type": "object", "additionalProperties": False},
        },
        {
            "name": "thunderbolt_list_channels",
            "title": "Thunderbolt — listar canais",
            "description": "Lista os canais registados sem devolver cookies, tokens ou outros segredos.",
            "inputSchema": {"type": "object", "additionalProperties": False},
        },
        {
            "name": "thunderbolt_list_videos",
            "title": "Thunderbolt — listar vídeos",
            "description": "Lista tarefas de vídeo com filtros opcionais por canal e estado.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "ID do canal opcional."},
                    "state": {"type": "string", "description": "Estado opcional: to_do, doing, blocked, done, failed ou cancelled."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "thunderbolt_list_blueprints",
            "title": "Thunderbolt — listar Blueprints",
            "description": "Lista os Blueprints JSON disponíveis na biblioteca local, sem expor caminhos absolutos.",
            "inputSchema": {"type": "object", "additionalProperties": False},
        },
    ]
    if write_enabled:
        tools.append(
            {
                "name": "thunderbolt_create_video_batch",
                "title": "Thunderbolt — criar lote de vídeos",
                "description": "Cria um lote e as respectivas tarefas. Só aparece quando o utilizador activa ferramentas de escrita na UI.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["single", "batch", "general"]},
                        "channel_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                        "topic": {"type": "string", "minLength": 1},
                        "quantity": {"type": "integer", "minimum": 1, "maximum": 50},
                        "language": {"type": "string"},
                        "format": {"type": "string"},
                        "style_wide": {"type": "string"},
                        "style_ia": {"type": "string"},
                        "music_mode": {"type": "boolean"},
                        "background_mode": {"type": "string"},
                    },
                    "required": ["mode", "channel_ids", "topic", "quantity"],
                    "additionalProperties": False,
                },
            }
        )
    return tools


def _tool_call(name: str, arguments: dict[str, Any], write_enabled: bool) -> Any:
    if name == "thunderbolt_get_status":
        return pipeline_summary()
    if name == "thunderbolt_list_channels":
        channels = storage.read_json("channels.json", [])
        return [_channel_public(channel) for channel in channels if isinstance(channel, dict)]
    if name == "thunderbolt_list_videos":
        channel_id = str(arguments.get("channel_id", "") or "").strip()
        state = str(arguments.get("state", "") or "").strip()
        limit = int(arguments.get("limit", 50) or 50)
        if limit < 1 or limit > 100:
            raise ValueError("limit deve estar entre 1 e 100.")
        valid_states = {"to_do", "doing", "blocked", "done", "failed", "cancelled"}
        if state and state not in valid_states:
            raise ValueError(f"state inválido: {state}.")
        tasks = storage.read_json("tasks.json", [])
        filtered = [
            task for task in tasks
            if isinstance(task, dict)
            and (not channel_id or task.get("channel_id") == channel_id)
            and (not state or task.get("state") == state)
        ]
        return [_task_public(task) for task in filtered[:limit]]
    if name == "thunderbolt_list_blueprints":
        return _list_blueprints()
    if name == "thunderbolt_create_video_batch":
        if not write_enabled:
            raise PermissionError("Ferramentas de escrita estão desactivadas no Servidor MCP.")
        mode = str(arguments.get("mode", "")).strip()
        if mode not in {"single", "batch", "general"}:
            raise ValueError("mode deve ser single, batch ou general.")
        channel_ids = arguments.get("channel_ids")
        if not isinstance(channel_ids, list) or not channel_ids or not all(isinstance(item, str) and item.strip() for item in channel_ids):
            raise ValueError("channel_ids deve conter pelo menos um ID de canal válido.")
        topic = str(arguments.get("topic", "") or "").strip()
        if not topic:
            raise ValueError("topic é obrigatório.")
        quantity = int(arguments.get("quantity", 1) or 1)
        if quantity < 1 or quantity > 50:
            raise ValueError("quantity deve estar entre 1 e 50.")
        options = {
            "language": str(arguments.get("language", "") or ""),
            "format": str(arguments.get("format", "wide") or "wide"),
            "style_wide": str(arguments.get("style_wide", "pexels") or "pexels"),
            "style_ia": str(arguments.get("style_ia", "") or ""),
            "music_mode": bool(arguments.get("music_mode", False)),
            "background_mode": str(arguments.get("background_mode", "stock") or "stock"),
        }
        batch = create_batch(mode, [item.strip() for item in channel_ids], topic, quantity, options)
        tasks = create_tasks_for_batch(batch)
        return {"batch_id": batch["id"], "task_ids": [task["id"] for task in tasks], "created": len(tasks)}
    raise KeyError(f"Ferramenta desconhecida: {name}")


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": _json_text(value)}],
        "isError": is_error,
    }
    if not is_error:
        result["structuredContent"] = value
    return result


class _MCPDispatcher:
    def __init__(self, auth_token: str = "", write_enabled: bool = False):
        self.auth_token = auth_token.strip()
        self.write_enabled = bool(write_enabled)

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0":
            return _rpc_error(request_id, -32600, "Pedido JSON-RPC inválido.")
        method = request.get("method")
        params = request.get("params") or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            return _rpc_error(request_id, -32600, "method e params inválidos.")
        if method in {"notifications/initialized", "notifications/cancelled", "notifications/progress"} or "id" not in request:
            return None
        if method == "initialize":
            requested = params.get("protocolVersion")
            protocol_version = requested if isinstance(requested, str) and requested else DEFAULT_PROTOCOL_VERSION
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": protocol_version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "Thunderbolt MCP Server", "version": _version()},
                    "instructions": "Use tools/list para descobrir as ferramentas disponíveis. Ferramentas de escrita só aparecem quando autorizadas pelo utilizador na UI.",
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_definitions(self.write_enabled)}}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return _rpc_error(request_id, -32602, "name e arguments são obrigatórios em tools/call.")
            try:
                value = _tool_call(name, arguments, self.write_enabled)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(value)}
            except KeyError as exc:
                return _rpc_error(request_id, -32602, str(exc))
            except (ValueError, PermissionError) as exc:
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result(str(exc), is_error=True)}
            except Exception:
                LOGGER.exception("Falha ao executar ferramenta MCP %s", name)
                return {"jsonrpc": "2.0", "id": request_id, "result": _tool_result("Erro interno ao executar a ferramenta.", is_error=True)}
        return _rpc_error(request_id, -32601, f"Método não suportado: {method}")


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _RequestHandler(BaseHTTPRequestHandler):
    server: _HTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("MCP HTTP %s", format % args)

    def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = self.server.dispatcher.auth_token
        if not token:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {token}" or self.headers.get("X-Thunderbolt-MCP-Token", "") == token

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == MCP_HEALTH_PATH:
            self._send_json({"ok": True, "server": "Thunderbolt MCP Server", "endpoint": MCP_ENDPOINT_PATH, "version": _version()})
            return
        if path == MCP_ENDPOINT_PATH:
            self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
            self.send_header("Allow", "POST")
            self.end_headers()
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != MCP_ENDPOINT_PATH:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._send_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1_000_000:
                raise ValueError("Corpo JSON inválido ou demasiado grande.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(_rpc_error(None, -32700, f"JSON inválido: {exc}"), HTTPStatus.BAD_REQUEST)
            return
        if isinstance(payload, list):
            responses = [self.server.dispatcher.handle(item) for item in payload if isinstance(item, dict)]
            responses = [item for item in responses if item is not None]
            if responses:
                self._send_json(responses)
            else:
                self.send_response(HTTPStatus.ACCEPTED)
                self.end_headers()
            return
        if not isinstance(payload, dict):
            self._send_json(_rpc_error(None, -32600, "O pedido MCP deve ser um objecto JSON-RPC."), HTTPStatus.BAD_REQUEST)
            return
        response = self.server.dispatcher.handle(payload)
        if response is None:
            self.send_response(HTTPStatus.ACCEPTED)
            self.end_headers()
            return
        self._send_json(response)


class _Runtime:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.http_server: _HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.host = ""
        self.port = 0
        self.write_enabled = False

    def start(self, host: str, port: int, auth_token: str = "", write_enabled: bool = False) -> dict[str, Any]:
        host = (host or DEFAULT_HOST).strip()
        port = int(port)
        if not 1 <= port <= 65535:
            raise ValueError("A porta MCP deve estar entre 1 e 65535.")
        if host not in {"127.0.0.1", "localhost", "::1"} and not auth_token.strip():
            raise ValueError("Defina um token MCP antes de expor o servidor fora do computador local.")
        with self.lock:
            if self.http_server and self.thread and self.thread.is_alive() and (self.host, self.port) == (host, port):
                self.write_enabled = bool(write_enabled)
                self.http_server.dispatcher.write_enabled = bool(write_enabled)
                self.http_server.dispatcher.auth_token = auth_token.strip()
                return self.status()
            self.stop()
            server = _HTTPServer((host, port), _RequestHandler)
            server.dispatcher = _MCPDispatcher(auth_token, write_enabled)
            thread = threading.Thread(target=server.serve_forever, name="thunderbolt-mcp", daemon=True)
            thread.start()
            self.http_server = server
            self.thread = thread
            self.host = host
            self.port = port
            self.write_enabled = bool(write_enabled)
            return self.status()

    def stop(self) -> None:
        with self.lock:
            if self.http_server:
                self.http_server.shutdown()
                self.http_server.server_close()
            self.http_server = None
            self.thread = None
            self.host = ""
            self.port = 0
            self.write_enabled = False

    def status(self) -> dict[str, Any]:
        running = bool(self.http_server and self.thread and self.thread.is_alive())
        return {
            "running": running,
            "host": self.host if running else "",
            "port": self.port if running else 0,
            "endpoint": f"http://{self.host}:{self.port}{MCP_ENDPOINT_PATH}" if running else "",
            "health_endpoint": f"http://{self.host}:{self.port}{MCP_HEALTH_PATH}" if running else "",
            "write_enabled": self.write_enabled if running else False,
        }


_RUNTIME = _Runtime()
atexit.register(_RUNTIME.stop)


def start_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, auth_token: str = "", write_enabled: bool = False) -> dict[str, Any]:
    return _RUNTIME.start(host, port, auth_token, write_enabled)


def stop_server() -> None:
    _RUNTIME.stop()


def server_status() -> dict[str, Any]:
    return _RUNTIME.status()


def tool_definitions(write_enabled: bool = False) -> list[dict[str, Any]]:
    return _tool_definitions(write_enabled)
