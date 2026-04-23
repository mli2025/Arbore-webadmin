"""
Portainer client for Arbore Web Admin backend.

本模块将 Arbore webadmin 对 Docker 引擎的所有操作统一收敛到 Portainer CE 的
HTTP API 上。Arbore 不再直接与 /var/run/docker.sock 或 docker CLI 交互，
从而解决自建接口在大镜像 tar 上传、容器创建、启停等场景下的不稳定问题。

This module is the single gateway between the Arbore webadmin FastAPI app and
Portainer CE. All Docker operations (image load, container create/start/stop/
restart/remove/inspect/logs/stats) go through Portainer's proxy to the Docker
Engine API. The goal is to replace fragile in-process docker SDK calls and
direct unix socket access with a battle tested backend.

Required environment variables (configure in backend .env or compose):
    PORTAINER_URL           e.g. http://portainer:9000  (recommended: in-compose hostname)
    PORTAINER_API_KEY       Portainer API key (Settings -> Users -> API keys)
    PORTAINER_ENDPOINT_ID   Numeric environment id of the local Docker env (usually 1 or 2)

Optional:
    PORTAINER_VERIFY_SSL    "true" (default) / "false" when using self signed https
    PORTAINER_TIMEOUT       total timeout in seconds for standard requests (default 60)
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator, Dict, List, Optional

import httpx


class PortainerError(Exception):
    """Generic Portainer API error with HTTP status."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Portainer {status_code}: {message}")


class PortainerNotFound(PortainerError):
    """Resource (container/image/network) not found on Portainer endpoint."""


class PortainerConflict(PortainerError):
    """Resource conflict, e.g. container name already taken."""


class PortainerClient:
    """Thin async HTTP client around Portainer's Docker proxy API.

    Instances are cheap and stateless; httpx AsyncClient is constructed per call
    because uvicorn workers fork and we want to avoid cross-worker connection
    pool surprises. If profiling shows overhead, a shared client with an
    explicit lifespan hook can be introduced without breaking callers.
    """

    def __init__(self) -> None:
        url = (os.environ.get("PORTAINER_URL") or "").strip()
        self.base_url = url.rstrip("/")
        self.api_key = (os.environ.get("PORTAINER_API_KEY") or "").strip()
        try:
            self.endpoint_id = int(os.environ.get("PORTAINER_ENDPOINT_ID", "1"))
        except ValueError:
            self.endpoint_id = 1
        self.verify_ssl = (os.environ.get("PORTAINER_VERIFY_SSL", "true").lower()
                           not in ("0", "false", "no", "off"))
        try:
            self.timeout = float(os.environ.get("PORTAINER_TIMEOUT", "60"))
        except ValueError:
            self.timeout = 60.0

    @property
    def configured(self) -> bool:
        return bool(self.base_url) and bool(self.api_key)

    @property
    def docker_base(self) -> str:
        return f"{self.base_url}/api/endpoints/{self.endpoint_id}/docker"

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {"X-API-Key": self.api_key}
        if extra:
            h.update(extra)
        return h

    def _client(self, *, read_timeout: Optional[float] = None,
                write_timeout: Optional[float] = None) -> httpx.AsyncClient:
        read = read_timeout if read_timeout is not None else self.timeout
        write = write_timeout if write_timeout is not None else self.timeout
        return httpx.AsyncClient(
            timeout=httpx.Timeout(None, connect=10.0, read=read, write=write, pool=10.0),
            verify=self.verify_ssl,
        )

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        text = (resp.text or "").strip()[:500]
        if resp.status_code == 404:
            raise PortainerNotFound(404, text or "not found")
        if resp.status_code == 409:
            raise PortainerConflict(409, text or "conflict")
        raise PortainerError(resp.status_code, text or resp.reason_phrase)

    # ---------------- system ----------------

    async def ping(self) -> bool:
        """Return True when Portainer and its Docker endpoint are reachable."""
        async with self._client(read_timeout=10.0) as cli:
            try:
                r = await cli.get(f"{self.base_url}/api/system/status", headers=self._headers())
                if r.status_code >= 400:
                    return False
                r2 = await cli.get(f"{self.docker_base}/_ping", headers=self._headers())
                return r2.status_code < 400
            except httpx.HTTPError:
                return False

    # ---------------- images ----------------

    async def images_load_stream(self, stream: AsyncIterator[bytes], *, quiet: int = 1) -> str:
        """Forward a tar byte stream to Docker /images/load via Portainer.

        stream must be an async iterator yielding bytes. We pass it directly to
        httpx without buffering the whole file. Read timeout is disabled so
        large images do not trip the default 60s window.
        """
        url = f"{self.docker_base}/images/load?quiet={quiet}"
        async with self._client(read_timeout=None, write_timeout=None) as cli:
            r = await cli.post(
                url,
                content=stream,
                headers=self._headers({"Content-Type": "application/x-tar"}),
            )
            self._raise_for_status(r)
            return r.text or ""

    async def images_list(self) -> List[dict]:
        url = f"{self.docker_base}/images/json?all=0"
        async with self._client() as cli:
            r = await cli.get(url, headers=self._headers())
            self._raise_for_status(r)
            return r.json()

    async def image_remove(self, name: str, *, force: bool = False) -> None:
        url = f"{self.docker_base}/images/{name}"
        async with self._client() as cli:
            r = await cli.delete(
                url,
                params={"force": "1" if force else "0"},
                headers=self._headers(),
            )
            if r.status_code == 404:
                return
            self._raise_for_status(r)

    # ---------------- containers ----------------

    async def containers_list(self, *, all: bool = True,
                              label_filters: Optional[List[str]] = None,
                              name_filters: Optional[List[str]] = None) -> List[dict]:
        """List containers; optionally filter by label (key or key=value) or name substring."""
        filters: Dict[str, List[str]] = {}
        if label_filters:
            filters["label"] = label_filters
        if name_filters:
            filters["name"] = name_filters
        params: Dict[str, str] = {"all": "1" if all else "0"}
        if filters:
            params["filters"] = json.dumps(filters)
        url = f"{self.docker_base}/containers/json"
        async with self._client() as cli:
            r = await cli.get(url, params=params, headers=self._headers())
            self._raise_for_status(r)
            return r.json()

    async def container_inspect(self, name_or_id: str) -> dict:
        url = f"{self.docker_base}/containers/{name_or_id}/json"
        async with self._client() as cli:
            r = await cli.get(url, headers=self._headers())
            self._raise_for_status(r)
            return r.json()

    async def container_create(self, name: str, config: dict) -> dict:
        url = f"{self.docker_base}/containers/create"
        async with self._client() as cli:
            r = await cli.post(
                url,
                params={"name": name},
                json=config,
                headers=self._headers({"Content-Type": "application/json"}),
            )
            self._raise_for_status(r)
            return r.json()

    async def container_start(self, name_or_id: str) -> None:
        url = f"{self.docker_base}/containers/{name_or_id}/start"
        async with self._client() as cli:
            r = await cli.post(url, headers=self._headers())
            if r.status_code == 304:
                return  # already started
            self._raise_for_status(r)

    async def container_stop(self, name_or_id: str, *, timeout: int = 30) -> None:
        url = f"{self.docker_base}/containers/{name_or_id}/stop"
        async with self._client(read_timeout=float(timeout + 15)) as cli:
            r = await cli.post(url, params={"t": str(timeout)}, headers=self._headers())
            if r.status_code in (204, 304):
                return  # already stopped
            self._raise_for_status(r)

    async def container_restart(self, name_or_id: str, *, timeout: int = 30) -> None:
        url = f"{self.docker_base}/containers/{name_or_id}/restart"
        async with self._client(read_timeout=float(timeout + 30)) as cli:
            r = await cli.post(url, params={"t": str(timeout)}, headers=self._headers())
            if r.status_code == 204:
                return
            self._raise_for_status(r)

    async def container_remove(self, name_or_id: str, *, force: bool = True,
                               remove_volumes: bool = False) -> None:
        url = f"{self.docker_base}/containers/{name_or_id}"
        async with self._client() as cli:
            r = await cli.delete(
                url,
                params={"force": "1" if force else "0", "v": "1" if remove_volumes else "0"},
                headers=self._headers(),
            )
            if r.status_code in (204, 404):
                return
            self._raise_for_status(r)

    async def container_logs_bytes(self, name_or_id: str, *, tail: int = 100,
                                   timestamps: bool = True) -> bytes:
        url = f"{self.docker_base}/containers/{name_or_id}/logs"
        params = {
            "stdout": "1",
            "stderr": "1",
            "tail": str(tail),
            "timestamps": "1" if timestamps else "0",
        }
        async with self._client() as cli:
            r = await cli.get(url, params=params, headers=self._headers())
            self._raise_for_status(r)
            return r.content or b""

    async def container_stats(self, name_or_id: str) -> dict:
        url = f"{self.docker_base}/containers/{name_or_id}/stats"
        async with self._client() as cli:
            r = await cli.get(url, params={"stream": "0"}, headers=self._headers())
            self._raise_for_status(r)
            return r.json()

    # ---------------- networks ----------------

    async def network_list(self) -> List[dict]:
        url = f"{self.docker_base}/networks"
        async with self._client() as cli:
            r = await cli.get(url, headers=self._headers())
            self._raise_for_status(r)
            return r.json()

    async def network_exists(self, name: str) -> bool:
        try:
            networks = await self.network_list()
        except PortainerError:
            return False
        return any(n.get("Name") == name for n in networks)


# Singleton used by the FastAPI app. Import as: from portainer_client import portainer
portainer = PortainerClient()


# ---------------- helpers ----------------

def demux_docker_log_stream(data: bytes) -> str:
    """Decode Docker's multiplexed log stream (non-TTY containers).

    Each frame is prefixed with an 8-byte header: {stream_type, 0, 0, 0, size_be32}.
    TTY containers return plain bytes and don't have headers, so we detect by
    stream_type and fall back to raw decode on anomaly. This mirrors Docker's
    own stdcopy.StdCopy behaviour in Python.
    """
    if not data:
        return ""
    parts: List[str] = []
    i, n = 0, len(data)
    while i + 8 <= n:
        stream_type = data[i]
        if stream_type not in (0, 1, 2):
            # TTY container or unexpected payload -> treat the rest as plain text
            parts.append(data[i:].decode("utf-8", errors="replace"))
            return "".join(parts)
        if data[i + 1] != 0 or data[i + 2] != 0 or data[i + 3] != 0:
            parts.append(data[i:].decode("utf-8", errors="replace"))
            return "".join(parts)
        length = int.from_bytes(data[i + 4:i + 8], "big")
        i += 8
        end = i + length
        if end > n:
            parts.append(data[i:].decode("utf-8", errors="replace"))
            return "".join(parts)
        parts.append(data[i:end].decode("utf-8", errors="replace"))
        i = end
    if i < n:
        parts.append(data[i:].decode("utf-8", errors="replace"))
    return "".join(parts)


def memory_mb_to_bytes(mb: Optional[int]) -> int:
    if not mb or mb <= 0:
        return 0
    return int(mb) * 1024 * 1024


def bytes_to_mb(value: Optional[int]) -> Optional[int]:
    if not value or int(value) <= 0:
        return None
    return int(int(value) // (1024 * 1024))
