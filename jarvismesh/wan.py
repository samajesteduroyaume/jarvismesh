"""
Interconnexion WAN, détection Tailscale/VPN et serveur de relais (MeshRelayServer) pour JarvisMesh.

Permet de connecter des nœuds situés sur des réseaux physiques distincts
(au-delà du multicast LAN) via Tailscale, WireGuard ou un serveur de rendez-vous / relais.
"""
from __future__ import annotations
import asyncio
import json
import socket
import time
from typing import Any, Optional

from .node import JarvisNode


def detect_tailscale_ip() -> Optional[str]:
    """Détecte une adresse IPv4 Tailscale (plage 100.64.0.0/10) si présente."""
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip.startswith("100."):
                return ip
    except Exception:
        pass
    return None


class MeshRelayServer:
    """Serveur de relais / rendez-vous léger permettant la découverte distante WAN."""

    def __init__(self, host: str = "0.0.0.0", port: int = 9000):
        self.host = host
        self.port = port
        self._nodes: dict[str, dict[str, Any]] = {}  # name -> {address, port, skills, last_seen}
        self._server: Optional[asyncio.Server] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self.node_ttl = 60.0  # Expire après 60s sans heartbeat

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self._cleanup_task = asyncio.ensure_future(self._cleanup_loop())

    async def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(15.0)
                now = time.time()
                expired = [k for k, v in self._nodes.items() if now - v.get("last_seen", 0) > self.node_ttl]
                for k in expired:
                    self._nodes.pop(k, None)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                return

            line_str = line.decode("utf-8", errors="ignore").strip()
            parts = line_str.split(" ")
            if len(parts) < 2:
                writer.close()
                return

            method, path = parts[0], parts[1].split("?")[0]
            content_len = 0
            while True:
                h = await reader.readline()
                if not h or h == b"\r\n":
                    break
                h_str = h.decode("utf-8", errors="ignore").strip()
                if h_str.lower().startswith("content-length:"):
                    try:
                        content_len = int(h_str.split(":", 1)[1].strip())
                    except ValueError:
                        content_len = 0

            body = await reader.readexactly(content_len) if content_len > 0 else b""

            if method == "POST" and path == "/register":
                data = json.loads(body.decode("utf-8")) if body else {}
                name = data.get("name")
                if name:
                    self._nodes[name] = {
                        "name": name,
                        "address": data.get("address") or writer.get_extra_info("peername")[0],
                        "port": int(data.get("port", 8765)),
                        "skills": data.get("skills", []),
                        "last_seen": time.time(),
                    }
                    await self._send_json(writer, 200, {"ok": True, "registered": name})
                else:
                    await self._send_json(writer, 400, {"ok": False, "error": "Nom de nœud requis"})
                return

            elif method == "GET" and path == "/peers":
                await self._send_json(writer, 200, {"peers": self._nodes})
                return

            await self._send_json(writer, 404, {"error": "Not Found"})
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_json(self, writer: asyncio.StreamWriter, status: int, data: Any):
        payload = json.dumps(data).encode("utf-8")
        msg = (
            f"HTTP/1.1 {status} OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n\r\n"
        )
        writer.write(msg.encode("utf-8") + payload)
        await writer.drain()


class WANPeerManager:
    """Synchronise périodiquement les pairs distants via un serveur de relais WAN."""

    def __init__(self, node: JarvisNode, relay_url: str, sync_interval: float = 10.0):
        self.node = node
        self.relay_url = relay_url.rstrip("/")
        self.sync_interval = sync_interval
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        self._task = asyncio.ensure_future(self._sync_loop())

    async def stop(self):
        if self._task:
            self._task.cancel()

    async def _sync_loop(self):
        while True:
            try:
                await self._heartbeat()
                await self._fetch_peers()
                await asyncio.sleep(self.sync_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5.0)

    async def _heartbeat(self):
        """Enregistre le nœud local auprès du serveur relais."""
        ts_ip = detect_tailscale_ip()
        adv_ip = ts_ip or self.node.advertise_ip
        data = {
            "name": self.node.name,
            "address": adv_ip,
            "port": self.node.port,
            "skills": sorted(self.node.skills.keys()),
        }
        await self._http_post(f"{self.relay_url}/register", data)

    async def _fetch_peers(self):
        """Récupère la liste des pairs distants et les ajoute au nœud local."""
        res = await self._http_get(f"{self.relay_url}/peers")
        if res and "peers" in res:
            for p_name, p_info in res["peers"].items():
                if p_name != self.node.name:
                    self.node.add_static_peer(
                        name=p_name,
                        address=p_info["address"],
                        port=p_info["port"],
                        skills=p_info.get("skills", []),
                    )

    async def _http_post(self, url: str, data: dict) -> Optional[dict]:
        import urllib.request
        def _sync_post():
            req = urllib.request.Request(
                url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))
        try:
            return await asyncio.to_thread(_sync_post)
        except Exception:
            return None

    async def _http_get(self, url: str) -> Optional[dict]:
        import urllib.request
        def _sync_get():
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))
        try:
            return await asyncio.to_thread(_sync_get)
        except Exception:
            return None
