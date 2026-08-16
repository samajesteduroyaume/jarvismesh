"""
Serveur HTTP & Événements temps réel pour le Dashboard JarvisMesh.

Fournit une interface web de supervision du maillage d'agents, de télémétrie VRAM/CPU,
d'un studio d'inférence en streaming et d'un exécuteur de workflows multi-agents.
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Optional, Set

from ..node import JarvisNode
from ..orchestrator import Workflow
from ..protocol import DESCRIBE_SKILL, HEALTH_SKILL

STATIC_DIR = Path(__file__).parent / "static"


class DashboardServer:
    def __init__(self, node: JarvisNode, host: str = "0.0.0.0", port: int = 8080):
        self.node = node
        self.host = host
        self.port = port
        self._server: Optional[asyncio.Server] = None
        self._sse_clients: Set[asyncio.Queue] = set()
        self._ticker_task: Optional[asyncio.Task] = None

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self._ticker_task = asyncio.ensure_future(self._broadcast_loop())

    async def stop(self):
        if self._ticker_task:
            self._ticker_task.cancel()
            self._ticker_task = None
        for q in list(self._sse_clients):
            await q.put(None)
        self._sse_clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def broadcast_event(self, event_type: str, data: dict):
        """Envoie un événement en temps réel à tous les clients connectés."""
        msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for q in list(self._sse_clients):
            try:
                q.put_nowait(msg)
            except Exception:
                pass

    async def _broadcast_loop(self):
        """Diffuse périodiquement l'état du maillage et la santé des nœuds."""
        while True:
            try:
                await asyncio.sleep(2.0)
                if not self._sse_clients:
                    continue
                # Métriques locales
                local_health = self.node._health_handler({})
                payload = {
                    "timestamp": time.time(),
                    "node": {
                        "name": self.node.name,
                        "port": self.node.port,
                        "ip": self.node.advertise_ip,
                        "skills": sorted(self.node.skills.keys()),
                        "health": local_health,
                    },
                    "peers": self.node.peers,
                    "peers_health": self.node._peer_health,
                }
                self.broadcast_event("telemetry", payload)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1.0)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            line_str = request_line.decode("utf-8", errors="ignore").strip()
            parts = line_str.split(" ")
            if len(parts) < 2:
                writer.close()
                return

            method, raw_path = parts[0], parts[1]
            path = raw_path.split("?")[0]

            headers = {}
            content_length = 0
            while True:
                header_line = await reader.readline()
                if not header_line or header_line == b"\r\n":
                    break
                header_text = header_line.decode("utf-8", errors="ignore").strip()
                if ":" in header_text:
                    k, v = header_text.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                    if k.strip().lower() == "content-length":
                        try:
                            content_length = int(v.strip())
                        except ValueError:
                            content_length = 0

            body_bytes = b""
            if content_length > 0:
                body_bytes = await reader.readexactly(content_length)

            await self._route_request(method, path, headers, body_bytes, writer)
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _route_request(self, method: str, path: str, headers: dict, body: bytes, writer: asyncio.StreamWriter):
        # 1. API Status & Topology
        if method == "GET" and path == "/api/status":
            local_health = self.node._health_handler({})
            data = {
                "name": self.node.name,
                "port": self.node.port,
                "ip": self.node.advertise_ip,
                "skills": sorted(self.node.skills.keys()),
                "health": local_health,
                "peers": self.node.peers,
                "peers_health": self.node._peer_health,
            }
            await self._send_json(writer, 200, data)
            return

        # 2. API All Available Skills in Mesh
        if method == "GET" and path == "/api/skills":
            mesh_skills: dict[str, list[str]] = {}
            for s in self.node.skills.keys():
                mesh_skills.setdefault(s, []).append(self.node.name)
            for p_name, p_info in self.node.peers.items():
                for s in p_info.get("skills", []):
                    mesh_skills.setdefault(s, []).append(p_name)
            await self._send_json(writer, 200, {"skills": mesh_skills})
            return

        # 3. API Delegate (Single Task or Streaming)
        if method == "POST" and path == "/api/delegate":
            try:
                req_data = json.loads(body.decode("utf-8")) if body else {}
            except Exception as e:
                await self._send_json(writer, 400, {"ok": False, "error": f"JSON invalide: {e}"})
                return

            skill = req_data.get("skill")
            payload = req_data.get("payload", {})
            peer = req_data.get("peer") or None
            stream = req_data.get("stream", False)
            timeout = float(req_data.get("timeout", 30.0))

            if not skill:
                await self._send_json(writer, 400, {"ok": False, "error": "'skill' est requis"})
                return

            if stream:
                # Réponse en flux HTTP SSE (Server-Sent Events)
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/event-stream\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Connection: keep-alive\r\n"
                    b"Access-Control-Allow-Origin: *\r\n\r\n"
                )
                await writer.drain()

                async def on_stream_chunk(chunk):
                    msg = f"event: chunk\ndata: {json.dumps({'chunk': chunk})}\n\n"
                    writer.write(msg.encode("utf-8"))
                    await writer.drain()

                resp = await self.node.delegate_stream(
                    skill=skill,
                    payload=payload,
                    on_chunk=lambda c: asyncio.ensure_future(on_stream_chunk(c)),
                    peer_name=peer,
                    timeout=timeout,
                )
                final_msg = f"event: done\ndata: {json.dumps({'ok': resp.ok, 'result': resp.result, 'error': resp.error, 'handled_by': resp.handled_by})}\n\n"
                writer.write(final_msg.encode("utf-8"))
                await writer.drain()
                return
            else:
                resp = await self.node.delegate(skill=skill, payload=payload, peer_name=peer, timeout=timeout)
                await self._send_json(writer, 200, {
                    "ok": resp.ok,
                    "result": resp.result,
                    "error": resp.error,
                    "handled_by": resp.handled_by,
                    "request_id": resp.request_id,
                })
                return

        # 4. API Run Workflow
        if method == "POST" and path == "/api/workflow/run":
            try:
                wf_data = json.loads(body.decode("utf-8")) if body else {}
            except Exception as e:
                await self._send_json(writer, 400, {"ok": False, "error": f"JSON invalide: {e}"})
                return

            workflow = Workflow.from_dict(wf_data.get("workflow", {}))
            initial_input = wf_data.get("input", {})
            stream_updates = wf_data.get("stream", False)

            if stream_updates:
                writer.write(
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/event-stream\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Connection: keep-alive\r\n"
                    b"Access-Control-Allow-Origin: *\r\n\r\n"
                )
                await writer.drain()

                def progress_cb(event_type, step_name, data):
                    msg = f"event: {event_type}\ndata: {json.dumps({'step': step_name, 'data': data})}\n\n"
                    writer.write(msg.encode("utf-8"))
                    asyncio.ensure_future(writer.drain())

                result = await workflow.run(self.node, initial_input=initial_input, on_progress=progress_cb)
                final_msg = f"event: workflow_done\ndata: {json.dumps(result.to_dict())}\n\n"
                writer.write(final_msg.encode("utf-8"))
                await writer.drain()
                return
            else:
                result = await workflow.run(self.node, initial_input=initial_input)
                await self._send_json(writer, 200, result.to_dict())
                return

        # 5. Live Events SSE Stream
        if method == "GET" and path == "/api/events":
            q: asyncio.Queue = asyncio.Queue()
            self._sse_clients.add(q)
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/event-stream\r\n"
                b"Cache-Control: no-cache\r\n"
                b"Connection: keep-alive\r\n"
                b"Access-Control-Allow-Origin: *\r\n\r\n"
            )
            await writer.drain()
            try:
                while True:
                    msg = await q.get()
                    if msg is None:
                        break
                    writer.write(msg.encode("utf-8"))
                    await writer.drain()
            except Exception:
                pass
            finally:
                self._sse_clients.discard(q)
            return

        # 6. Static Files (HTML / CSS / JS)
        file_path = STATIC_DIR / ("index.html" if path in ("/", "") else path.lstrip("/"))
        if file_path.is_file() and str(file_path).startswith(str(STATIC_DIR)):
            content_type = "text/plain"
            if file_path.suffix == ".html":
                content_type = "text/html; charset=utf-8"
            elif file_path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif file_path.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            elif file_path.suffix == ".svg":
                content_type = "image/svg+xml"
            elif file_path.suffix == ".json":
                content_type = "application/json"

            content = file_path.read_bytes()
            headers_str = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: {content_type}\r\n"
                f"Content-Length: {len(content)}\r\n"
                f"Access-Control-Allow-Origin: *\r\n\r\n"
            )
            writer.write(headers_str.encode("utf-8") + content)
            await writer.drain()
            return

        # 404 Not Found
        not_found = b"HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\n\r\nNot Found"
        writer.write(not_found)
        await writer.drain()

    async def _send_json(self, writer: asyncio.StreamWriter, status_code: int, data: Any):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers = (
            f"HTTP/1.1 {status_code} OK\r\n"
            f"Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n\r\n"
        )
        writer.write(headers.encode("utf-8") + body)
        await writer.drain()


async def run_dashboard(node: JarvisNode, host: str = "0.0.0.0", port: int = 8080):
    server = DashboardServer(node, host=host, port=port)
    await server.start()
    print(f"[{node.name}] 🌐 Dashboard JarvisMesh accessible sur http://{node.advertise_ip}:{port}")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()
