"""
JarvisNode — un agent JarvisMesh.

Chaque noeud :
  1. Expose ses compétences ("skills") via un petit serveur websocket
     (ws:// ou wss:// si un ssl_context est fourni).
  2. S'annonce sur le réseau local via zeroconf (mDNS), TXT record = liste
     de ses compétences.
  3. Découvre les autres noeuds du réseau et peut leur déléguer une tâche
     si lui-même ne sait pas la faire (ou si un pair est meilleur).
  4. Si un `psk` (clé pré-partagée) est configuré, signe ses requêtes
     sortantes en HMAC-SHA256 et rejette toute requête entrante non signée
     ou mal signée — un intrus sur le réseau local ne peut pas se faire
     passer pour un pair de confiance ni écouter les tâches en clair s'il
     ne connaît pas le psk (et en clair, seul le payload reste visible
     sans TLS ; utiliser ssl_context pour aussi chiffrer le transport).
  5. Expose deux compétences internes réservées, toujours disponibles sans
     déclaration explicite : `_describe_skills` (introspection complète,
     pour contourner la limite de taille du TXT record mDNS) et `_health`
     (charge courante, pour un routage plus fin que le simple tourniquet).

Aucun serveur central, aucune API propriétaire, aucun cloud : le réseau
local suffit. Fallback "peers statiques" fourni pour les environnements
sans multicast (conteneurs, tests).
"""
from __future__ import annotations
import asyncio
import inspect
import os
import socket
import ssl as ssl_module
import time
from typing import Any, Callable, Optional, Type

import websockets
from zeroconf import IPVersion
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceInfo, AsyncServiceBrowser

from .protocol import (
    TaskRequest, TaskChunk, TaskResponse, parse_message, SERVICE_TYPE,
    DESCRIBE_SKILL, HEALTH_SKILL, RESERVED_SKILLS, verify_request,
)
from ..security.crypto import verify_ed25519_signature

try:
    from pydantic import BaseModel, ValidationError
    _HAS_PYDANTIC = True
except ImportError:  # la validation de payload reste optionnelle
    BaseModel = None  # type: ignore
    ValidationError = Exception  # type: ignore
    _HAS_PYDANTIC = False


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class JarvisNode:
    def __init__(self, name: str, port: int, skills: Optional[dict[str, Callable]] = None,
                 host: str = "0.0.0.0", advertise_ip: Optional[str] = None,
                 psk: Optional[str] = None, ssl_context: Optional["ssl_module.SSLContext"] = None,
                 schemas: Optional[dict[str, Type["BaseModel"]]] = None,
                 health_extra: Optional[Callable[[], dict]] = None,
                 identity: Optional[Any] = None,
                 trust_store: Optional[Any] = None):
        """
        psk : clé pré-partagée pour signer/vérifier les TaskRequest en
            HMAC-SHA256. None = mode ouvert, rétro-compatible (aucune
            vérification). Tous les noeuds du mesh doivent partager le
            même psk pour communiquer entre eux.
        identity : instance de NodeIdentity (Ed25519) pour signer les requêtes
            sortantes de manière asymétrique.
        trust_store : instance de TrustStore contenant les clés publiques autorisées
            pour rejeter les requêtes provenant de pairs non approuvés ou révoqués.
        ssl_context : si fourni, le serveur écoute en wss:// avec ce
            contexte (charger un certificat via ssl.SSLContext côté
            serveur) et les connexions sortantes vers les pairs l'utilisent
            aussi (pour un mesh local avec certificats auto-signés,
            construire le contexte avec check_hostname=False et
            verify_mode=ssl.CERT_NONE — le psk reste la couche d'authentification,
            TLS n'apporte ici que la confidentialité du transport).
        schemas : dict optionnel {nom_compétence: modèle Pydantic} pour
            valider les payloads entrants avant d'appeler la fonction.
            Nécessite `pydantic` installé.
        health_extra : callback optionnel sans argument retournant un dict
            de métriques additionnelles à fusionner dans la réponse de la
            compétence interne `_health` (ex: VRAM libre côté MLX).
        """
        self.name = name
        self.port = port
        self.skills = skills or {}
        self.host = host
        self.advertise_ip = advertise_ip or _local_ip()
        self.psk = psk
        self.identity = identity
        self.trust_store = trust_store
        self.ssl_context = ssl_context
        self.health_extra = health_extra

        self.schemas: dict[str, Any] = schemas or {}
        if self.schemas and not _HAS_PYDANTIC:
            raise ImportError(
                "des schémas de validation ont été fournis mais 'pydantic' "
                "n'est pas installé — `pip install pydantic --break-system-packages`"
            )

        self.peers: dict[str, dict] = {}  # name -> {"address", "port", "skills"}
        self._zc: Optional[AsyncZeroconf] = None
        self._service_info: Optional[AsyncServiceInfo] = None
        self._browser: Optional[AsyncServiceBrowser] = None
        self._ws_server = None

        # Pool de connexions websocket persistantes vers les pairs (une par
        # pair, réutilisée entre appels pour éviter le handshake à chaque
        # délégation).
        #
        # Multiplexage : une seule boucle de lecture par connexion
        # (_reader_loop) distribue chaque réponse à la bonne requête via
        # request_id -> Future. Plusieurs requêtes concurrentes peuvent donc
        # partager la même connexion sans s'attendre les unes les autres —
        # seul l'envoi (ws.send) est protégé par un verrou léger, jamais
        # l'attente de la réponse.
        self._pool: dict[str, "websockets.WebSocketClientProtocol"] = {}
        self._send_locks: dict[str, asyncio.Lock] = {}
        self._reader_tasks: dict[str, asyncio.Task] = {}
        self._pending: dict[str, dict[str, asyncio.Future]] = {}
        self._stream_cbs: dict[str, dict[str, Callable[[Any], None]]] = {}

        # Curseur round-robin par compétence, pour répartir la charge entre
        # plusieurs pairs qui fournissent la même compétence (utilisé en
        # secours quand aucune métrique de santé fraîche n'est disponible,
        # et pour départager des pairs à charge égale).
        self._rr_cursor: dict[str, int] = {}

        # Charge locale (nb de tâches d'un pair en cours de traitement pour
        # ce noeud), exposée via la compétence interne `_health`.
        self._active_tasks = 0

        # Cache de santé des pairs, alimenté par un sondage périodique en
        # tâche de fond (voir _health_probe_loop). {peer_name: {..., "ts": float}}
        self._peer_health: dict[str, dict] = {}
        self._health_ttl = 15.0          # au-delà, une mesure est jugée périmée
        self._health_probe_interval = 5.0
        self._health_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    async def start(self, enable_zeroconf: bool = True):
        self._ws_server = await websockets.serve(
            self._handle_ws, self.host, self.port, ssl=self.ssl_context
        )

        if enable_zeroconf:
            self._zc = AsyncZeroconf(ip_version=IPVersion.V4Only)
            skills_txt = ",".join(self.skills.keys())
            self._service_info = AsyncServiceInfo(
                SERVICE_TYPE,
                f"{self.name}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(self.advertise_ip)],
                port=self.port,
                properties={"skills": skills_txt},
            )
            await self._zc.async_register_service(self._service_info)
            self._browser = AsyncServiceBrowser(
                self._zc.zeroconf, SERVICE_TYPE, handlers=[self._on_service_change]
            )

        self._health_task = asyncio.ensure_future(self._health_probe_loop())

    async def stop(self):
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None
        for task in list(self._reader_tasks.values()):
            task.cancel()
        for pending in self._pending.values():
            for fut in pending.values():
                if not fut.done():
                    fut.cancel()
        for ws in list(self._pool.values()):
            try:
                await ws.close()
            except Exception:
                pass
        self._pool.clear()
        self._reader_tasks.clear()
        self._pending.clear()
        self._stream_cbs.clear()
        if self._browser:
            await self._browser.async_cancel()
        if self._zc and self._service_info:
            await self._zc.async_unregister_service(self._service_info)
            await self._zc.async_close()
        if self._ws_server:
            self._ws_server.close()
            await self._ws_server.wait_closed()

    # ------------------------------------------------------------------ #
    # Découverte
    # ------------------------------------------------------------------ #
    def _on_service_change(self, zeroconf, service_type, name, state_change):
        peer_name = name.replace(f".{SERVICE_TYPE}", "")
        if peer_name == self.name:
            return
        if state_change.name in ("Added", "Updated"):
            asyncio.ensure_future(self._refresh_peer(zeroconf, service_type, name, peer_name))
        elif state_change.name == "Removed":
            self.peers.pop(peer_name, None)

    async def _refresh_peer(self, zeroconf, service_type, name, peer_name):
        info = AsyncServiceInfo(service_type, name)
        ok = await info.async_request(zeroconf, 3000)
        if not ok or not info.addresses:
            return
        address = socket.inet_ntoa(info.addresses[0])
        skills_raw = info.properties.get(b"skills", b"").decode()
        self.peers[peer_name] = {
            "address": address,
            "port": info.port,
            "skills": [s for s in skills_raw.split(",") if s],
        }
        # Le TXT record mDNS est limité en taille (~1-2 Ko) : dès qu'un
        # noeud a beaucoup de compétences, la liste peut y être tronquée.
        # On complète donc systématiquement via une introspection directe
        # (compétence interne réservée `_describe_skills`, pas de limite de
        # taille car transportée sur le websocket) — best effort : si le
        # pair ne répond pas encore (juste découvert) ou est une ancienne
        # version sans cette compétence, on garde la liste issue du TXT.
        try:
            resp = await self._send_request(peer_name, DESCRIBE_SKILL, {}, timeout=3.0, on_chunk=None)
            if resp.ok and isinstance(resp.result, dict) and "skills" in resp.result:
                self.peers[peer_name]["skills"] = resp.result["skills"]
        except Exception:
            pass

    def add_static_peer(self, name: str, address: str, port: int, skills: list[str]):
        """Fallback manuel pour les réseaux sans multicast (Docker, tests, CI)."""
        self.peers[name] = {"address": address, "port": port, "skills": skills}

    def list_peers(self) -> dict:
        return dict(self.peers)

    def find_peers_for_skill(self, skill: str) -> list[str]:
        return [p for p, info in self.peers.items() if skill in info.get("skills", [])]

    # ------------------------------------------------------------------ #
    # Compétences internes réservées (introspection + santé)
    # ------------------------------------------------------------------ #
    def _describe_skills_handler(self, payload: dict) -> dict:
        """Catalogue complet des compétences de ce noeud — contourne la
        limite de taille du TXT record mDNS, qui ne sert plus que
        d'annonce initiale rapide."""
        return {"name": self.name, "skills": sorted(self.skills.keys())}

    def _health_handler(self, payload: dict) -> dict:
        """Métriques de charge courantes, utilisées par les pairs pour
        router vers le noeud le plus disponible plutôt qu'un simple
        tourniquet aveugle à la charge réelle."""
        try:
            load1, _, _ = os.getloadavg()
        except (OSError, AttributeError):
            load1 = None  # non disponible (ex: Windows)
        metrics = {
            "active_tasks": self._active_tasks,
            "load": load1,
            "cpu_count": os.cpu_count(),
        }
        if self.health_extra is not None:
            try:
                metrics.update(self.health_extra())
            except Exception:
                pass
        return metrics

    def _resolve_skill_fn(self, skill: str) -> Optional[Callable]:
        if skill == DESCRIBE_SKILL:
            return self._describe_skills_handler
        if skill == HEALTH_SKILL:
            return self._health_handler
        return self.skills.get(skill)

    async def _health_probe_loop(self):
        """Sonde périodiquement `_health` sur tous les pairs connus pour
        alimenter le cache utilisé par le routage (_ordered_candidates).
        Best effort : un pair injoignable ne fait qu'expirer du cache
        (voir _health_ttl), il ne casse jamais la boucle."""
        while True:
            try:
                await asyncio.sleep(self._health_probe_interval)
                peer_names = list(self.peers.keys())
                if not peer_names:
                    continue
                results = await asyncio.gather(
                    *(self._send_request(p, HEALTH_SKILL, {}, timeout=2.0, on_chunk=None)
                      for p in peer_names),
                    return_exceptions=True,
                )
                now = time.time()
                for peer_name, resp in zip(peer_names, results):
                    if isinstance(resp, TaskResponse) and resp.ok and isinstance(resp.result, dict):
                        self._peer_health[peer_name] = {**resp.result, "ts": now}
            except asyncio.CancelledError:
                break
            except Exception:
                continue  # ne jamais laisser mourir la boucle de sondage

    # ------------------------------------------------------------------ #
    # Validation de payload
    # ------------------------------------------------------------------ #
    def _validate_payload(self, skill: str, payload: dict):
        """Valide `payload` contre le schéma Pydantic déclaré pour `skill`,
        s'il y en a un. Retourne (payload_validé, erreur). `erreur` est
        None si tout est valide."""
        model = self.schemas.get(skill)
        if model is None:
            return payload, None
        try:
            instance = model(**payload)
            return instance.model_dump(), None
        except ValidationError as e:
            details = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or '<payload>'}: {err['msg']}"
                for err in e.errors()
            )
            return None, f"payload invalide pour '{skill}': {details}"

    # ------------------------------------------------------------------ #
    # Traitement des tâches entrantes
    # ------------------------------------------------------------------ #
    async def _handle_ws(self, websocket):
        # Verrou d'envoi partagé entre toutes les tâches de cette connexion :
        # plusieurs requêtes traitées en parallèle ne doivent pas écrire sur
        # le même websocket en même temps.
        send_lock = asyncio.Lock()
        async for raw in websocket:
            msg = parse_message(raw)
            if msg.get("type") != "task_request":
                continue
            # Une tâche par requête : la boucle de lecture continue
            # immédiatement, donc une requête lente ne bloque plus les
            # suivantes derrière elle sur la même connexion.
            asyncio.ensure_future(self._process_task(websocket, send_lock, msg))

    async def _process_task(self, websocket, send_lock: asyncio.Lock, msg: dict):
        skill = msg.get("skill")
        req_id = msg.get("request_id")
        ts = float(msg.get("ts", 0.0))
        origin = msg.get("origin", "")
        sig = msg.get("sig")
        pubkey = msg.get("pubkey")

        # 1. Authentification Asymétrique (Ed25519 via TrustStore)
        if self.trust_store is not None:
            # Protection contre le rejeu : tolérance de 120s sur l'horodatage
            now = time.time()
            if abs(now - ts) > 120.0:
                resp = TaskResponse(request_id=req_id, ok=False,
                                     error="authentification échouée (horodatage expiré / replay protection)",
                                     handled_by=self.name)
                async with send_lock:
                    await websocket.send(resp.to_json())
                return

            if not self.trust_store.is_authorized(pubkey):
                resp = TaskResponse(request_id=req_id, ok=False,
                                     error="authentification échouée (clé publique non autorisée ou révoquée)",
                                     handled_by=self.name)
                async with send_lock:
                    await websocket.send(resp.to_json())
                return

            valid_sig = verify_ed25519_signature(pubkey, req_id, origin, skill, ts, msg.get("payload", {}), sig)
            if not valid_sig:
                resp = TaskResponse(request_id=req_id, ok=False,
                                     error="authentification échouée (signature Ed25519 invalide)",
                                     handled_by=self.name)
                async with send_lock:
                    await websocket.send(resp.to_json())
                return

        # 2. Authentification Symétrique (PSK/HMAC) si configuré
        elif self.psk is not None:
            authentic = verify_request(
                self.psk, req_id, origin, skill, ts, msg.get("payload", {}), sig,
            )
            if not authentic:
                resp = TaskResponse(request_id=req_id, ok=False,
                                     error="authentification échouée (psk manquant ou invalide)",
                                     handled_by=self.name)
                async with send_lock:
                    await websocket.send(resp.to_json())
                return

        fn = self._resolve_skill_fn(skill)
        if fn is None:
            resp = TaskResponse(request_id=req_id, ok=False,
                                 error=f"compétence '{skill}' inconnue sur {self.name}",
                                 handled_by=self.name)
            async with send_lock:
                await websocket.send(resp.to_json())
            return

        payload = msg.get("payload", {})

        # 2. Validation du payload contre le schéma déclaré, s'il y en a un.
        payload, validation_error = self._validate_payload(skill, payload)
        if validation_error:
            resp = TaskResponse(request_id=req_id, ok=False, error=validation_error, handled_by=self.name)
            async with send_lock:
                await websocket.send(resp.to_json())
            return

        self._active_tasks += 1
        try:
            if inspect.isasyncgenfunction(fn):
                resp = await self._stream_async_gen(websocket, send_lock, req_id, fn(payload))
            elif inspect.isgeneratorfunction(fn):
                resp = await self._stream_sync_gen(websocket, send_lock, req_id, fn(payload))
            else:
                result = fn(payload)
                if inspect.isawaitable(result):
                    result = await result
                resp = TaskResponse(request_id=req_id, ok=True, result=result, handled_by=self.name)
        except Exception as e:
            resp = TaskResponse(request_id=req_id, ok=False, error=str(e), handled_by=self.name)
        finally:
            self._active_tasks -= 1
        async with send_lock:
            await websocket.send(resp.to_json())

    async def _stream_sync_gen(self, websocket, send_lock: asyncio.Lock, req_id, gen) -> TaskResponse:
        chunks = []
        for i, item in enumerate(gen):
            chunks.append(item)
            async with send_lock:
                await websocket.send(TaskChunk(request_id=req_id, index=i, chunk=item).to_json())
        return TaskResponse(request_id=req_id, ok=True, result=chunks, handled_by=self.name, streamed=True)

    async def _stream_async_gen(self, websocket, send_lock: asyncio.Lock, req_id, agen) -> TaskResponse:
        chunks = []
        i = 0
        async for item in agen:
            chunks.append(item)
            async with send_lock:
                await websocket.send(TaskChunk(request_id=req_id, index=i, chunk=item).to_json())
            i += 1
        return TaskResponse(request_id=req_id, ok=True, result=chunks, handled_by=self.name, streamed=True)

    # ------------------------------------------------------------------ #
    # Délégation sortante
    # ------------------------------------------------------------------ #
    def _ordered_candidates(self, skill: str) -> list[str]:
        """Pairs fournissant `skill`, ordonnés pour tenter le plus
        prometteur en premier. Si des métriques de santé fraîches
        (< _health_ttl) sont disponibles pour TOUS les candidats, on
        trie par charge croissante (tâches actives, puis load average) ;
        sinon on retombe sur le tourniquet round-robin classique. Dans les
        deux cas, un curseur tourne à chaque appel pour départager les
        pairs à charge égale et permettre le failover vers les suivants si
        le premier échoue."""
        candidates = self.find_peers_for_skill(skill)
        if not candidates:
            return []

        start = self._rr_cursor.get(skill, 0) % len(candidates)
        self._rr_cursor[skill] = start + 1
        rotated = candidates[start:] + candidates[:start]

        now = time.time()

        def fresh_health(name: str) -> Optional[tuple]:
            h = self._peer_health.get(name)
            if h and now - h.get("ts", 0) < self._health_ttl:
                load = h.get("load")
                return (h.get("active_tasks", 0), load if load is not None else 0.0)
            return None

        healths = {c: fresh_health(c) for c in rotated}
        if all(v is not None for v in healths.values()):
            return sorted(rotated, key=lambda c: healths[c])
        return rotated

    async def delegate(self, skill: str, payload: dict, peer_name: Optional[str] = None,
                        timeout: float = 10.0) -> TaskResponse:
        # 1. Compétence locale disponible et aucun pair explicitement demandé
        if peer_name is None and (skill in self.skills or skill in RESERVED_SKILLS):
            fn = self._resolve_skill_fn(skill)
            payload, validation_error = self._validate_payload(skill, payload)
            if validation_error:
                return TaskResponse(request_id="local", ok=False, error=validation_error, handled_by=self.name)
            result = fn(payload)
            if inspect.isawaitable(result):
                result = await result
            return TaskResponse(request_id="local", ok=True, result=result, handled_by=self.name)

        # 2. Pair explicitement ciblé : une seule tentative, pas de failover
        #    (le choix de l'appelant est respecté tel quel).
        if peer_name is not None:
            return await self._send_request(peer_name, skill, payload, timeout, on_chunk=None)

        # 3. Sinon : routage par santé (ou round-robin en secours) + failover.
        candidates = self._ordered_candidates(skill)
        if not candidates:
            return TaskResponse(request_id="none", ok=False,
                                 error=f"aucun pair ne fournit '{skill}'", handled_by="")
        last_resp = None
        for candidate in candidates:
            last_resp = await self._send_request(candidate, skill, payload, timeout, on_chunk=None)
            if last_resp.ok:
                return last_resp
        last_resp.error = f"tous les pairs ont échoué pour '{skill}' — dernière erreur: {last_resp.error}"
        return last_resp

    async def delegate_stream(self, skill: str, payload: dict, on_chunk: Callable[[Any], None],
                               peer_name: Optional[str] = None, timeout: float = 30.0) -> TaskResponse:
        """Comme delegate(), mais appelle on_chunk(item) à chaque morceau reçu
        au fil de l'eau (utile pour un LLM qui streame token par token)."""
        if peer_name is not None:
            return await self._send_request(peer_name, skill, payload, timeout, on_chunk=on_chunk)

        candidates = self._ordered_candidates(skill)
        if not candidates:
            return TaskResponse(request_id="none", ok=False,
                                 error=f"aucun pair ne fournit '{skill}'", handled_by="")
        last_resp = None
        for candidate in candidates:
            last_resp = await self._send_request(candidate, skill, payload, timeout, on_chunk=on_chunk)
            if last_resp.ok:
                return last_resp
        last_resp.error = f"tous les pairs ont échoué pour '{skill}' — dernière erreur: {last_resp.error}"
        return last_resp

    # ------------------------------------------------------------------ #
    # Connexion + dispatcher multiplexé
    # ------------------------------------------------------------------ #
    async def _get_connection(self, peer_name: str):
        """Retourne une connexion websocket persistante vers ce pair,
        en la (re)créant si elle est absente ou fermée, et démarre sa
        boucle de lecture en tâche de fond si ce n'est pas déjà fait."""
        ws = self._pool.get(peer_name)
        if ws is not None and ws.state is websockets.protocol.State.OPEN:
            return ws
        peer = self.peers.get(peer_name)
        if peer is None:
            raise ConnectionError(f"pair '{peer_name}' inconnu")
        scheme = "wss" if self.ssl_context else "ws"
        uri = f"{scheme}://{peer['address']}:{peer['port']}"
        ws = await websockets.connect(uri, open_timeout=10, ssl=self.ssl_context)
        self._pool[peer_name] = ws
        self._pending.setdefault(peer_name, {})
        self._stream_cbs.setdefault(peer_name, {})
        old_task = self._reader_tasks.get(peer_name)
        if old_task:
            old_task.cancel()
        self._reader_tasks[peer_name] = asyncio.ensure_future(self._reader_loop(peer_name, ws))
        return ws

    async def _reader_loop(self, peer_name: str, ws):
        """Une seule boucle de lecture par connexion, qui distribue chaque
        message entrant à la requête concernée via request_id. C'est ce qui
        permet à plusieurs délégations concurrentes de partager la même
        connexion sans se bloquer mutuellement."""
        try:
            async for raw in ws:
                data = parse_message(raw)
                req_id = data.get("request_id")
                if data.get("type") == "task_chunk":
                    cb = self._stream_cbs.get(peer_name, {}).get(req_id)
                    if cb is not None:
                        cb(data.get("chunk"))
                    continue
                if data.get("type") == "task_response":
                    fut = self._pending.get(peer_name, {}).pop(req_id, None)
                    self._stream_cbs.get(peer_name, {}).pop(req_id, None)
                    if fut is not None and not fut.done():
                        fut.set_result(TaskResponse(**{
                            k: v for k, v in data.items() if k != "type"
                        }))
        except Exception as e:
            # Connexion coupée : on échoue toutes les requêtes en attente
            # sur ce pair plutôt que de les laisser pendre indéfiniment.
            for fut in self._pending.pop(peer_name, {}).values():
                if not fut.done():
                    fut.set_exception(e)
            self._stream_cbs.pop(peer_name, None)
        finally:
            self._pool.pop(peer_name, None)
            self._reader_tasks.pop(peer_name, None)

    async def _send_request(self, peer_name: str, skill: str, payload: dict,
                             timeout: float, on_chunk: Optional[Callable[[Any], None]]) -> TaskResponse:
        if peer_name not in self.peers:
            return TaskResponse(request_id="none", ok=False,
                                 error=f"pair '{peer_name}' inconnu", handled_by="")

        req = TaskRequest(skill=skill, payload=payload, origin=self.name)
        if self.identity is not None:
            req.sign_ed25519(self.identity)
        elif self.psk is not None:
            req.sign(self.psk)
        try:
            ws = await self._get_connection(peer_name)
        except Exception as e:
            return TaskResponse(request_id=req.request_id, ok=False, error=str(e), handled_by=peer_name)

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending.setdefault(peer_name, {})[req.request_id] = fut
        if on_chunk is not None:
            self._stream_cbs.setdefault(peer_name, {})[req.request_id] = on_chunk

        # Seul l'envoi est verrouillé (rapide) — l'attente de la réponse ne
        # bloque personne d'autre : c'est le multiplexage.
        send_lock = self._send_locks.setdefault(peer_name, asyncio.Lock())
        try:
            async with send_lock:
                await ws.send(req.to_json())
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.get(peer_name, {}).pop(req.request_id, None)
            self._stream_cbs.get(peer_name, {}).pop(req.request_id, None)
            return TaskResponse(request_id=req.request_id, ok=False, error="timeout", handled_by=peer_name)
        except Exception as e:
            self._pending.get(peer_name, {}).pop(req.request_id, None)
            self._stream_cbs.get(peer_name, {}).pop(req.request_id, None)
            return TaskResponse(request_id=req.request_id, ok=False, error=str(e), handled_by=peer_name)
