"""
Passerelle bi-directionnelle Model Context Protocol (MCP) pour JarvisMesh.

1. Client MCP (MCP -> JarvisMesh) : Connecte un serveur d'outils MCP (stdio/JSON-RPC)
   et expose chacun de ses outils comme une compétence JarvisMesh distribuée sur le mesh.
2. Serveur MCP (JarvisMesh -> MCP) : Expose l'ensemble du maillage JarvisMesh comme un
   serveur d'outils MCP stdio standard pour Claude Desktop, Cursor, Antigravity, etc.
"""
from __future__ import annotations
import asyncio
import json
import os
import shlex
import sys
from typing import Any, Callable, Optional

from .node import JarvisNode
from .skills import SkillRegistry


class MCPClientBridge:
    """Client bridge connectant un sous-processus MCP stdio à JarvisMesh."""

    def __init__(self, command: str | list[str], prefix: str = "mcp_"):
        self.command = command if isinstance(command, list) else shlex.split(command)
        self.prefix = prefix
        self._process: Optional[asyncio.subprocess.Process] = None
        self._req_counter = 0
        self._pending_responses: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._tools_meta: list[dict[str, Any]] = []

    async def start(self) -> dict[str, Callable]:
        """Démarre le serveur MCP, négocie l'initialisation et retourne les compétences générées."""
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._reader_task = asyncio.ensure_future(self._stdout_reader())

        # 1. Handshake Initialize
        init_res = await self._send_jsonrpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jarvismesh-bridge", "version": "1.0.0"},
            },
        )

        # 2. Notification Initialized
        await self._send_notification("notifications/initialized", {})

        # 3. Découverte des outils disponibles (tools/list)
        tools_res = await self._send_jsonrpc("tools/list", {})
        self._tools_meta = tools_res.get("tools", [])

        # 4. Génération des compétences JarvisMesh
        skills_dict: dict[str, Callable] = {}
        for tool in self._tools_meta:
            tool_name = tool.get("name")
            skill_name = f"{self.prefix}{tool_name}"
            desc = tool.get("description", f"Outil MCP: {tool_name}")

            fn = self._create_tool_caller(tool_name)
            setattr(fn, "__name__", skill_name)
            setattr(fn, "__doc__", desc)
            setattr(fn, "__is_jarvismesh_skill__", True)
            setattr(fn, "__skill_name__", skill_name)
            setattr(fn, "__skill_desc__", desc)
            skills_dict[skill_name] = fn

        return skills_dict

    def _create_tool_caller(self, mcp_tool_name: str) -> Callable:
        async def call_mcp_tool(payload: dict) -> dict:
            res = await self._send_jsonrpc("tools/call", {
                "name": mcp_tool_name,
                "arguments": payload,
            })
            content = res.get("content", [])
            # Extraction propre du contenu textuel retourné par MCP
            text_outputs = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_outputs.append(item.get("text", ""))
                else:
                    text_outputs.append(str(item))
            combined_text = "\n".join(text_outputs) if text_outputs else str(res)
            return {
                "content": combined_text,
                "raw": res,
                "is_error": res.get("isError", False),
            }

        return call_mcp_tool

    async def _send_jsonrpc(self, method: str, params: dict) -> dict:
        self._req_counter += 1
        req_id = self._req_counter
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending_responses[req_id] = fut

        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        line = json.dumps(msg) + "\n"
        if not self._process or not self._process.stdin:
            raise ConnectionError("Le processus MCP n'est pas démarré.")

        self._process.stdin.write(line.encode("utf-8"))
        await self._process.stdin.drain()

        try:
            return await asyncio.wait_for(fut, timeout=30.0)
        except asyncio.TimeoutError:
            self._pending_responses.pop(req_id, None)
            raise TimeoutError(f"Délai d'attente dépassé pour la méthode MCP '{method}'")

    async def _send_notification(self, method: str, params: dict):
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        line = json.dumps(msg) + "\n"
        if self._process and self._process.stdin:
            self._process.stdin.write(line.encode("utf-8"))
            await self._process.stdin.drain()

    async def _stdout_reader(self):
        try:
            while self._process and self._process.stdout and not self._process.stdout.at_eof():
                line = await self._process.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="ignore").strip()
                if not line_str or not line_str.startswith("{"):
                    continue
                try:
                    data = json.loads(line_str)
                    req_id = data.get("id")
                    if req_id is not None and req_id in self._pending_responses:
                        fut = self._pending_responses.pop(req_id)
                        if not fut.done():
                            if "error" in data:
                                fut.set_exception(RuntimeError(data["error"].get("message", str(data["error"]))))
                            else:
                                fut.set_result(data.get("result", {}))
                except Exception:
                    pass
        except Exception:
            pass

    async def stop(self):
        if self._reader_task:
            self._reader_task.cancel()
        if self._process:
            try:
                self._process.terminate()
                await self._process.wait()
            except Exception:
                pass


class MCPServerBridge:
    """Serveur stdio MCP permettant aux clients externes (Claude Desktop, etc.) de consommer JarvisMesh."""

    def __init__(self, node: JarvisNode):
        self.node = node

    async def run_stdio(self):
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
        w_transport, w_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(w_transport, w_protocol, reader, asyncio.get_event_loop())

        while not reader.at_eof():
            line = await reader.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="ignore").strip()
            if not line_str or not line_str.startswith("{"):
                continue

            try:
                req = json.loads(line_str)
                req_id = req.get("id")
                method = req.get("method")
                params = req.get("params", {})

                if method == "initialize":
                    res = {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": f"jarvismesh-{self.node.name}", "version": "1.0.0"},
                    }
                    await self._send_res(writer, req_id, res)
                elif method == "tools/list":
                    tools = []
                    for s_name in sorted(self.node.skills.keys()):
                        tools.append({
                            "name": s_name,
                            "description": f"Compétence JarvisMesh : {s_name}",
                            "inputSchema": {
                                "type": "object",
                                "properties": {},
                                "additionalProperties": True,
                            },
                        })
                    await self._send_res(writer, req_id, {"tools": tools})
                elif method == "tools/call":
                    tool_name = params.get("name")
                    tool_args = params.get("arguments", {})
                    task_resp = await self.node.delegate(tool_name, tool_args)
                    res_content = json.dumps(task_resp.result if task_resp.ok else {"error": task_resp.error}, ensure_ascii=False)
                    await self._send_res(writer, req_id, {
                        "content": [{"type": "text", "text": res_content}],
                        "isError": not task_resp.ok,
                    })
            except Exception as e:
                pass

    async def _send_res(self, writer: asyncio.StreamWriter, req_id: Any, result: dict):
        if req_id is None:
            return
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }
        writer.write((json.dumps(payload) + "\n").encode("utf-8"))
        await writer.drain()
