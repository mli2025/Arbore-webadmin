"""
Arbore Web 管理界面 - 后端 API (Portainer-backed)
Arbore Web Admin Backend API

重构要点（中文）:
1. 所有 Docker 引擎操作通过 Portainer CE 的 HTTP API 进行，
   Arbore 后端不再直接访问 /var/run/docker.sock 或调用 docker CLI；
2. 自定义服务的镜像 tar 上传采用流式转发给 Portainer 的 /images/load，
   彻底解决原先 “一次性 f.read() 加载大镜像” 导致的内存峰值与超时；
3. 自定义服务的生命周期（创建、启动、停止、重启、删除、日志、统计）
   统一通过 Portainer 原生 Docker Engine API 代理，不再编辑
   docker-compose.yml 与 nginx 配置文件；
4. 自定义服务的元数据 (描述、图标、端口、挂载、环境变量等) 使用单一
   JSON Spec 文件 config/custom-services/<name>.json 保存，作为
   重建容器时的权威来源，容器对外通过 arbore.* Label 进行分类与检索；
5. 标准服务继续由 docker-compose.yml 启动，本服务仅通过 Portainer
   读取状态 / 启停 / 重启它们，不再修改 compose 文件。

Refactor summary (English):
- Every container operation is proxied to Portainer over HTTP; no unix
  socket, no docker SDK. This eliminates a whole family of instability
  bugs (blocking event loop, whole tarball in RAM, nginx proxy timeouts).
- Custom service uploads stream the tar file directly into Portainer's
  /images/load endpoint, then create a container with arbore.* labels.
- Custom service config lives in config/custom-services/<name>.json and
  per-service .env files; docker-compose.yml / nginx conf are no longer
  touched by this backend for custom services.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Tuple

import psutil
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from packaging import version as pkg_version
from pydantic import BaseModel

from license_utils import (
    compute_validation_code,
    get_host_hardware_fingerprint,
    get_license_secret,
    save_license,
    validate_license,
)
from portainer_client import (
    PortainerConflict,
    PortainerError,
    PortainerNotFound,
    bytes_to_mb,
    demux_docker_log_stream,
    memory_mb_to_bytes,
    portainer,
)

# ---------------- 版本 / 应用 ----------------

API_VERSION = "1.2.0"
BUILD_TIME = "2026-04-23T12:00:00Z"

app = FastAPI(title="Arbore Web Admin API", version=API_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)
_api_log_file = os.path.join(_log_dir, "api.log")
_handler = logging.FileHandler(_api_log_file, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.root.addHandler(_handler)
logging.root.setLevel(logging.INFO)
logging.info("Web Admin API starting, log file: %s", _api_log_file)


# ---------------- 路径工具 ----------------

def get_project_root() -> str:
    env_root = os.environ.get("ARBORE_PROJECT_ROOT")
    if env_root:
        return env_root
    current_file = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(current_file)))


def _custom_services_dir() -> str:
    d = os.path.join(get_project_root(), "config", "custom-services")
    os.makedirs(d, exist_ok=True)
    return d


def _custom_service_config_dir(name: str) -> str:
    """Per-service directory: holds spec.json, .env, doc.pdf."""
    d = os.path.join(get_project_root(), "config", "custom-services", name)
    os.makedirs(d, exist_ok=True)
    return d


def _custom_service_spec_path(name: str) -> str:
    return os.path.join(_custom_service_config_dir(name), "spec.json")


def _custom_service_env_path(name: str) -> str:
    return os.path.join(_custom_service_config_dir(name), ".env")


def _custom_service_doc_path(name: str) -> str:
    return os.path.join(_custom_service_config_dir(name), "doc.pdf")


# ---------------- Portainer startup probe ----------------

@app.on_event("startup")
async def _probe_portainer_on_startup() -> None:
    if not portainer.configured:
        logging.warning(
            "Portainer not configured: PORTAINER_URL/PORTAINER_API_KEY missing."
            " All Docker operations will fail with 503 until configured.")
        return
    ok = await portainer.ping()
    if ok:
        logging.info("Portainer reachable at %s (endpoint_id=%s)",
                     portainer.base_url, portainer.endpoint_id)
    else:
        logging.warning("Portainer health check failed: %s (endpoint_id=%s)",
                        portainer.base_url, portainer.endpoint_id)


def _require_portainer() -> None:
    if not portainer.configured:
        raise HTTPException(
            status_code=503,
            detail="Portainer backend is not configured (PORTAINER_URL / PORTAINER_API_KEY).",
        )


def _portainer_error_to_http(err: PortainerError) -> HTTPException:
    if isinstance(err, PortainerNotFound):
        return HTTPException(status_code=404, detail=err.message)
    if isinstance(err, PortainerConflict):
        return HTTPException(status_code=409, detail=err.message)
    return HTTPException(status_code=502, detail=f"Portainer error: {err.message}")


# ---------------- 根 / 版本 ----------------

@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "arbore-web-admin-api",
        "version": API_VERSION,
        "build_time": BUILD_TIME,
    }


@app.get("/api/v1/version")
async def get_version():
    portainer_ok = False
    if portainer.configured:
        try:
            portainer_ok = await portainer.ping()
        except Exception:
            portainer_ok = False
    return {
        "version": API_VERSION,
        "build_time": BUILD_TIME,
        "portainer_configured": portainer.configured,
        "portainer_reachable": portainer_ok,
        "portainer_endpoint_id": portainer.endpoint_id,
    }


@app.get("/api/v1/diagnostics/portainer")
async def diagnostics_portainer():
    """诊断端点：详细返回 Portainer 配置和连通性，便于排查 502。

    Reports raw URL/endpoint, configured flag, ping result, and the first
    docker engine probe. Helpful when /images/load returns 502 and you need
    to know whether it's DNS, auth, endpoint id or something else.
    """
    info: dict = {
        "base_url": portainer.base_url,
        "configured": portainer.configured,
        "endpoint_id": portainer.endpoint_id,
        "verify_ssl": portainer.verify_ssl,
        "timeout": portainer.timeout,
    }
    if not portainer.configured:
        info["error"] = "PORTAINER_URL or PORTAINER_API_KEY missing"
        return info

    import httpx as _httpx
    try:
        async with portainer._client(read_timeout=10.0) as cli:  # type: ignore
            r = await cli.get(
                f"{portainer.base_url}/api/system/status",
                headers=portainer._headers(),  # type: ignore
            )
            info["system_status_code"] = r.status_code
            info["system_status_body"] = (r.text or "")[:300]
        async with portainer._client(read_timeout=10.0) as cli:  # type: ignore
            r2 = await cli.get(
                f"{portainer.docker_base}/_ping",
                headers=portainer._headers(),  # type: ignore
            )
            info["docker_ping_code"] = r2.status_code
            info["docker_ping_body"] = (r2.text or "")[:300]
    except _httpx.HTTPError as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info


# ============================================================
# 许可证 (License) - 业务核心，保持原逻辑
# ============================================================

LICENSE_CHECK_INTERVAL_SEC = 48 * 3600


def _license_valid_or_403():
    valid, error_code, info = validate_license(API_VERSION)
    if not valid:
        detail = {"code": error_code, "message": _license_error_message(error_code)}
        raise HTTPException(status_code=403, detail=detail)
    return (True, info)


def _license_error_message(code: Optional[str]) -> str:
    msg = {
        "LICENSE_NOT_FOUND": "License not configured",
        "LICENSE_INVALID": "License invalid or validation code mismatch",
        "HARDWARE_MISMATCH": "License does not match this host",
        "VERSION_MISMATCH": "License version does not match",
        "SECRET_NOT_CONFIGURED": "Server license secret not configured",
    }
    return msg.get(code or "", "License check failed")


def _run_license_periodic_check() -> None:
    """Background thread: re-validate license every 48h; stop standard services on failure."""
    import asyncio as _asyncio

    while True:
        time.sleep(LICENSE_CHECK_INTERVAL_SEC)
        try:
            valid, _error_code, _ = validate_license(API_VERSION)
            if valid or not portainer.configured:
                continue
            for name in _standard_service_keys():
                try:
                    _asyncio.run(portainer.container_stop(name, timeout=30))
                    logging.info("License invalid: stopped standard service %s", name)
                except PortainerNotFound:
                    pass
                except Exception as e:  # pragma: no cover - best effort
                    logging.warning("License check stop %s: %s", name, e)
        except Exception as e:
            logging.warning("License periodic check error: %s", e)


@app.on_event("startup")
def start_license_check_thread():
    t = threading.Thread(target=_run_license_periodic_check, daemon=True)
    t.start()
    logging.info("License periodic check thread started (interval: 48h)")


@app.get("/api/v1/license")
async def get_license():
    valid, error_code, info = validate_license(API_VERSION)
    _fingerprint, display_id = get_host_hardware_fingerprint()
    data = {
        "registered": valid,
        "valid": valid,
        "errorCode": error_code,
        "hostFingerprint": display_id,
        "versionInfo": API_VERSION.split(".")[0].zfill(3) if API_VERSION else "001",
    }
    if info:
        data["companyId"] = info.get("companyId", "")
        data["companyName"] = info.get("companyName", "")
        data["versionInfo"] = info.get("versionInfo", data["versionInfo"])
    return data


@app.get("/api/v1/license/hardware-fingerprint")
async def get_hardware_fingerprint():
    fingerprint, display_id = get_host_hardware_fingerprint()
    return {"hostFingerprint": display_id, "rawAvailable": fingerprint is not None}


@app.post("/api/v1/license/register")
async def register_license(
    companyId: str = Form(..., alias="companyId"),
    validationCode: str = Form(..., alias="validationCode"),
    companyName: str = Form(..., alias="companyName"),
):
    secret = get_license_secret()
    if not secret:
        raise HTTPException(status_code=503, detail={"code": "SECRET_NOT_CONFIGURED",
                                                      "message": "Server license secret not configured"})
    fingerprint, display_id = get_host_hardware_fingerprint()
    if not fingerprint:
        raise HTTPException(status_code=400, detail={"code": "HARDWARE_UNAVAILABLE",
                                                      "message": "Host hardware fingerprint unavailable"})
    expected = compute_validation_code(companyId, display_id, API_VERSION, secret)
    if not hmac.compare_digest(expected.upper(), validationCode.strip().upper()):
        raise HTTPException(status_code=400, detail={"code": "LICENSE_INVALID",
                                                      "message": "Validation code invalid or not for this host"})
    version_major = API_VERSION.split(".")[0].zfill(3) if API_VERSION else "001"
    save_license({
        "companyId": companyId,
        "validationCode": validationCode.strip(),
        "companyName": companyName.strip(),
        "version": version_major,
        "versionInfo": version_major,
    })
    return {"success": True, "message": "License registered"}


@app.post("/api/v1/license/validate")
async def post_license_validate():
    valid, error_code, info = validate_license(API_VERSION)
    return {"valid": valid, "errorCode": error_code, "license": info}


# ============================================================
# OTA 更新 (保持原逻辑)
# ============================================================

UPDATE_CHECK_INTERVAL_SEC = 3600
OTA_ENABLED = os.environ.get("ARBORE_OTA_DISABLED", "").lower() not in ("1", "true", "yes")

_update_info_cache: Dict[str, object] = {
    "has_update": False,
    "remote_version": None,
    "build_time": None,
    "changes": [],
    "last_check": None,
    "error": None,
}
_update_lock = threading.Lock()


def _get_update_config():
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.normpath(os.path.join(backend_dir, "..", "config", "update-config.json"))
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    env_url = os.environ.get("ARBORE_UPDATE_URL")
    if env_url:
        return {"update_url": env_url, "enabled": True}
    return {"update_url": "", "enabled": False}


def _save_update_config(config: dict):
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.normpath(os.path.join(backend_dir, "..", "config"))
    os.makedirs(config_dir, exist_ok=True)
    with open(os.path.join(config_dir, "update-config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _compare_versions(local_ver: str, remote_ver: str) -> bool:
    try:
        return pkg_version.parse(remote_ver) > pkg_version.parse(local_ver)
    except Exception:
        return remote_ver != local_ver


def _check_remote_update():
    import urllib.request

    config = _get_update_config()
    if not config.get("update_url"):
        with _update_lock:
            _update_info_cache["has_update"] = False
            _update_info_cache["error"] = None
            _update_info_cache["last_check"] = datetime.now().isoformat()
        return

    base_url = config["update_url"].rstrip("/")
    version_url = f"{base_url}/version.json"
    try:
        req = urllib.request.Request(version_url,
                                     headers={"User-Agent": f"Arbore-WebAdmin/{API_VERSION}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            remote_info = json.loads(resp.read().decode("utf-8"))
        remote_ver = remote_info.get("version", "")
        has_update = _compare_versions(API_VERSION, remote_ver)
        with _update_lock:
            _update_info_cache["has_update"] = has_update
            _update_info_cache["remote_version"] = remote_ver
            _update_info_cache["build_time"] = remote_info.get("build_time", "")
            _update_info_cache["changes"] = remote_info.get("changes", [])
            _update_info_cache["last_check"] = datetime.now().isoformat()
            _update_info_cache["error"] = None
        if has_update:
            logging.info("OTA: new version available: %s (current: %s)", remote_ver, API_VERSION)
    except Exception as e:
        logging.warning("OTA: check failed: %s", e)
        with _update_lock:
            _update_info_cache["error"] = str(e)
            _update_info_cache["last_check"] = datetime.now().isoformat()


def _run_update_check_loop():
    time.sleep(10)
    cfg = _get_update_config()
    if cfg.get("enabled") and cfg.get("update_url"):
        _check_remote_update()
    while True:
        time.sleep(UPDATE_CHECK_INTERVAL_SEC)
        cfg = _get_update_config()
        if cfg.get("enabled") and cfg.get("update_url"):
            _check_remote_update()


@app.on_event("startup")
def start_update_check_thread():
    if not OTA_ENABLED:
        logging.info("OTA update check disabled via ARBORE_OTA_DISABLED env var")
        return
    t = threading.Thread(target=_run_update_check_loop, daemon=True)
    t.start()
    logging.info("OTA update check thread started (interval: %ss)", UPDATE_CHECK_INTERVAL_SEC)


@app.get("/api/v1/update/config")
async def get_update_config_api():
    config = _get_update_config()
    return {"update_url": config.get("update_url", ""), "enabled": config.get("enabled", False)}


@app.post("/api/v1/update/config")
async def set_update_config(update_url: str = Form(""), enabled: bool = Form(True)):
    config = {"update_url": update_url.strip(), "enabled": enabled}
    _save_update_config(config)
    if enabled and update_url.strip():
        threading.Thread(target=_check_remote_update, daemon=True).start()
    return {"success": True, "message": "Update config saved"}


@app.get("/api/v1/update/check")
async def check_update(force: bool = False):
    if not OTA_ENABLED:
        return {"current_version": API_VERSION, "has_update": False, "ota_disabled": True}
    if force:
        _check_remote_update()
    with _update_lock:
        return {"current_version": API_VERSION, **_update_info_cache}


@app.post("/api/v1/update/apply")
async def apply_update():
    if not OTA_ENABLED:
        raise HTTPException(status_code=403,
                            detail="OTA update is disabled via ARBORE_OTA_DISABLED environment variable")
    import urllib.request

    config = _get_update_config()
    if not config.get("update_url"):
        raise HTTPException(status_code=400, detail="Update URL not configured")

    with _update_lock:
        if not _update_info_cache.get("has_update"):
            raise HTTPException(status_code=400, detail="Already on latest version")

    base_url = config["update_url"].rstrip("/")
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    web_admin_dir = os.path.normpath(os.path.join(backend_dir, ".."))
    frontend_dist_dir = os.path.join(web_admin_dir, "frontend", "dist")
    warnings: List[str] = []

    def _download(url: str, suffix: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            req = urllib.request.Request(url, headers={"User-Agent": f"Arbore-WebAdmin/{API_VERSION}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                shutil.copyfileobj(resp, tmp)
            return tmp.name

    # Frontend dist
    tmp_fe = ""
    try:
        tmp_fe = _download(f"{base_url}/frontend-dist.tar.gz", ".tar.gz")
        dist_backup = frontend_dist_dir + ".bak"
        if os.path.exists(frontend_dist_dir):
            if os.path.exists(dist_backup):
                shutil.rmtree(dist_backup)
            shutil.copytree(frontend_dist_dir, dist_backup)
        with tarfile.open(tmp_fe, "r:gz") as tar:
            tar.extractall(path=os.path.dirname(frontend_dist_dir))
    except Exception as e:
        warnings.append(f"Frontend update failed: {e}")
    finally:
        if tmp_fe and os.path.exists(tmp_fe):
            os.remove(tmp_fe)

    # Backend sources
    tmp_be = ""
    try:
        tmp_be = _download(f"{base_url}/backend.tar.gz", ".tar.gz")
        tmp_extract = tempfile.mkdtemp(prefix="arbore-backend-")
        with tarfile.open(tmp_be, "r:gz") as tar:
            tar.extractall(path=tmp_extract)
        preserve = {"venv", "config", "logs", "__pycache__", ".env"}
        extracted_backend = tmp_extract
        sub_items = os.listdir(tmp_extract)
        if len(sub_items) == 1 and os.path.isdir(os.path.join(tmp_extract, sub_items[0])):
            extracted_backend = os.path.join(tmp_extract, sub_items[0])
        for item in os.listdir(extracted_backend):
            if item in preserve:
                continue
            src = os.path.join(extracted_backend, item)
            dst = os.path.join(backend_dir, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        shutil.rmtree(tmp_extract)

        venv_pip = os.path.join(backend_dir, "venv", "bin", "pip")
        req_file = os.path.join(backend_dir, "requirements.txt")
        if os.path.exists(venv_pip) and os.path.exists(req_file):
            result = subprocess.run([venv_pip, "install", "-r", req_file],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                warnings.append(f"pip install warning: {result.stderr[:200]}")
    except Exception as e:
        warnings.append(f"Backend update failed: {e}")
    finally:
        if tmp_be and os.path.exists(tmp_be):
            os.remove(tmp_be)

    def _delayed_restart():
        time.sleep(2)
        try:
            subprocess.run(["sudo", "systemctl", "restart", "arbore-web-admin-api"],
                           timeout=30, capture_output=True, text=True)
        except Exception:
            os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_delayed_restart, daemon=True).start()
    return {
        "success": True,
        "message": "Update applied. Service is restarting, please wait a few seconds and refresh the page.",
        "warnings": warnings,
    }


# ============================================================
# 系统资源 / IP / 配置 / 日志 (保持原逻辑, 不依赖 Docker)
# ============================================================

def _get_gpu_info():
    gpus: List[dict] = []
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return gpus
        for line in result.stdout.strip().split("\n"):
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                idx = int(parts[0])
                name = parts[1]
                util = int(parts[2].replace("%", "") or 0)
                mem_used_mib = int(parts[3].replace("MiB", "").strip() or 0)
                mem_total_mib = int(parts[4].replace("MiB", "").strip() or 0)
                gpus.append({
                    "index": idx,
                    "name": name,
                    "utilization_percent": min(100, max(0, util)),
                    "memory_used": mem_used_mib * 1024 * 1024,
                    "memory_total": mem_total_mib * 1024 * 1024,
                    "memory_percent": round(100.0 * mem_used_mib / mem_total_mib, 1) if mem_total_mib else 0,
                })
            except (ValueError, IndexError):
                continue
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return gpus


@app.get("/api/v1/system/resources")
async def get_system_resources():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu": {"percent": cpu_percent, "count": psutil.cpu_count()},
            "memory": {"total": memory.total, "used": memory.used,
                       "available": memory.available, "percent": memory.percent},
            "disk": {"total": disk.total, "used": disk.used,
                     "free": disk.free, "percent": disk.percent},
            "gpu": _get_gpu_info(),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/system/ip")
async def get_system_ip():
    try:
        import socket

        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith("127."):
                return {"current_ip": ip, "method": "hostname", "hostname": hostname}
        except Exception:
            pass

        try:
            result = subprocess.run(["ip", "route", "get", "8.8.8.8"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                match = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
                if match:
                    return {"current_ip": match.group(1), "method": "ip_route"}
        except Exception:
            pass

        try:
            result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                for ip in result.stdout.strip().split():
                    if not ip.startswith("127.") and not ip.startswith("169.254."):
                        return {"current_ip": ip, "method": "hostname_I"}
        except Exception:
            pass

        raise HTTPException(status_code=500, detail="Cannot detect server IP address")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"IP detection failed: {e}")


@app.get("/api/v1/system/config")
async def get_system_config():
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env_file = os.path.join(project_root, ".env")
        config: Dict[str, str] = {}
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        config[key.strip()] = value.strip()
        current_ip_info = await get_system_ip()
        current_ip = current_ip_info.get("current_ip", "")
        configured_ip = config.get("SERVER_IP", "")
        return {
            "current_ip": current_ip,
            "configured_ip": configured_ip,
            "needs_update": current_ip != configured_ip and configured_ip != "",
            "config": config,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Read config failed: {e}")


@app.get("/api/v1/system/admin-logs")
async def get_admin_logs(tail: int = 200):
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "api.log")
    if not os.path.exists(log_file):
        return {"logs": ["Log file not yet created; check backend/logs/api.log."]}
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.rstrip("\n") for line in f.readlines()]
        return {"logs": lines[-tail:] if len(lines) > tail else lines}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Read log failed: {e}")


@app.post("/api/v1/system/config/update-ip")
async def update_system_ip():
    try:
        current_ip_info = await get_system_ip()
        new_ip = current_ip_info.get("current_ip", "")
        if not new_ip:
            raise HTTPException(status_code=400, detail="Cannot detect current IP")
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        script_path = os.path.join(project_root, "scripts", "update-server-ip.sh")
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail="IP update script not found")
        result = subprocess.run(["bash", script_path, new_ip],
                                cwd=project_root, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Update script failed: {result.stderr}")

        restart_services = ["arbore-flow", "arbore-nginx"]
        restart_results: List[dict] = []
        if portainer.configured:
            for service_name in restart_services:
                try:
                    await portainer.container_restart(service_name, timeout=60)
                    restart_results.append({"service": service_name, "status": "restarted"})
                except PortainerNotFound:
                    restart_results.append({"service": service_name, "status": "not_found"})
                except PortainerError as e:
                    restart_results.append({"service": service_name, "status": "error",
                                            "error": e.message})
        else:
            restart_results.append({"service": "all", "status": "error",
                                    "error": "Portainer not configured"})
        return {
            "success": True,
            "new_ip": new_ip,
            "script_output": result.stdout,
            "restart_results": restart_results,
            "message": f"IP updated to {new_ip}, related services restarted",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update IP failed: {e}")


# ============================================================
# 标准服务 (Standard services) - 通过 Portainer 操作, 不再修改 compose
# ============================================================

# 标准服务种子配置：仅当 config/standard-services.json 不存在时用作首次写入
# 之后所有读写都走配置文件，前端可通过齿轮按钮维护
_STANDARD_SERVICES_DEFAULT: List[dict] = [
    {"key": "arbore-flow", "display": "工作流服务",
     "description": "n8n 工作流自动化引擎", "icon": "Connection", "port": 5678},
    {"key": "arbore-func", "display": "应用服务",
     "description": "NocoBase 业务应用平台", "icon": "Grid", "port": 13000},
    {"key": "arbore-postgres-nocobase", "display": "PostgreSQL (应用数据库)",
     "description": "NocoBase 业务数据存储", "icon": "Coin", "port": 0},
    {"key": "arbore-postgres-vector", "display": "PostgreSQL (向量数据库)",
     "description": "pgvector 向量检索数据库", "icon": "DataLine", "port": 0},
    {"key": "arbore-ollama", "display": "AI模型服务",
     "description": "Ollama 本地大模型推理引擎", "icon": "Cpu", "port": 11434},
    {"key": "arbore-ollama-webui", "display": "AI模型界面",
     "description": "Ollama Web UI 对话界面", "icon": "ChatDotRound", "port": 3000},
    {"key": "kanban-frontend", "display": "看板前端服务",
     "description": "看板系统前端界面", "icon": "Monitor", "port": 13050},
    {"key": "kanban-backend", "display": "看板后端服务",
     "description": "看板系统后端 API", "icon": "Service", "port": 13051},
]


def _standard_services_config_path() -> str:
    d = os.path.join(get_project_root(), "config")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "standard-services.json")


def _load_standard_services_config() -> List[dict]:
    """读取标准服务配置；不存在则用默认值初始化并落盘。"""
    path = _standard_services_config_path()
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(_STANDARD_SERVICES_DEFAULT, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning("Failed to seed %s: %s", path, e)
        return list(_STANDARD_SERVICES_DEFAULT)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("config root must be a JSON array")
        return data
    except Exception as e:
        logging.warning("Read %s failed (%s), fallback to defaults", path, e)
        return list(_STANDARD_SERVICES_DEFAULT)


def _save_standard_services_config(items: List[dict]) -> None:
    path = _standard_services_config_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _standard_service_keys() -> List[str]:
    return [str(it.get("key", "")).strip() for it in _load_standard_services_config()
            if str(it.get("key", "")).strip()]


# 兼容旧引用：保留为函数式属性，但所有内部判断改走 _standard_service_keys()
STANDARD_DOCKER_SERVICES: List[str] = [it["key"] for it in _STANDARD_SERVICES_DEFAULT]

SYSTEMD_SERVICES: List[str] = [
    "service-router",
    "service-pdf-to-png",
    "service-paddle-ocr",
    "service-tesseract-ocr",
]


def _is_standard_service(service_name: str) -> bool:
    return service_name in _standard_service_keys()


def get_systemd_service_status(service_name: str) -> dict:
    try:
        r1 = subprocess.run(["systemctl", "is-active", service_name],
                            capture_output=True, text=True, timeout=5)
        is_active = r1.stdout.strip() == "active"
        r2 = subprocess.run(["systemctl", "is-enabled", service_name],
                            capture_output=True, text=True, timeout=5)
        is_enabled = r2.stdout.strip() == "enabled"
        port_map = {
            "service-router": ["2026"],
            "service-pdf-to-png": ["2027"],
            "service-paddle-ocr": ["2028"],
            "service-tesseract-ocr": ["2029"],
        }
        return {
            "name": service_name,
            "status": "running" if is_active else "stopped",
            "health": "healthy" if is_active else "unhealthy",
            "ports": port_map.get(service_name, []),
            "enabled": is_enabled,
            "type": "systemd",
        }
    except Exception as e:
        logging.warning("systemd status %s failed: %s", service_name, e)
        return {"name": service_name, "status": "unknown", "health": "unknown",
                "ports": [], "enabled": False, "type": "systemd"}


def _inspect_to_status(name: str, inspect: Optional[dict]) -> dict:
    if inspect is None:
        return {"name": name, "status": "not_found", "health": "unknown", "ports": []}
    state = inspect.get("State", {}) or {}
    health = (state.get("Health") or {}).get("Status", "unknown")
    status = state.get("Status", "unknown")
    ports: List[str] = []
    port_bindings = ((inspect.get("NetworkSettings") or {}).get("Ports") or {})
    for container_port, host_ports in port_bindings.items():
        if host_ports:
            for hp in host_ports:
                ports.append(f"{hp['HostPort']}:{container_port.split('/')[0]}")
    return {"name": name, "status": status, "health": health, "ports": ports}


@app.get("/api/v1/services")
async def get_services():
    services: List[dict] = []
    license_valid, license_error_code, _ = validate_license(API_VERSION)

    standard_keys = _standard_service_keys()
    if portainer.configured:
        for name in standard_keys:
            try:
                inspect = await portainer.container_inspect(name)
                services.append(_inspect_to_status(name, inspect))
            except PortainerNotFound:
                services.append(_inspect_to_status(name, None))
            except PortainerError as e:
                logging.warning("Inspect %s failed: %s", name, e)
                services.append({"name": name, "status": "unknown",
                                 "health": "unknown", "ports": []})
    else:
        for name in standard_keys:
            services.append({"name": name, "status": "unknown",
                             "health": "unknown", "ports": []})

    for sname in SYSTEMD_SERVICES:
        services.append(get_systemd_service_status(sname))

    return {
        "services": services,
        "licenseValid": license_valid,
        "licenseErrorCode": license_error_code,
    }


# ---------------- 标准服务展示配置（齿轮按钮维护） ----------------
# 这里只读写 config/standard-services.json，不动任何容器
# 同时暴露给前端：当用户增删改时影响 ServicesView 的卡片渲染、显示名、端口
# Backend will also pick the same list as STANDARD service keys for start/stop
# 权限校验和许可证联动均跟随该配置。
_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")


def _normalize_standard_service_item(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Each item must be an object")
    key = str(raw.get("key", "")).strip()
    if not key or not _KEY_RE.match(key):
        raise HTTPException(status_code=400,
                            detail=f"Invalid service key: {key!r}")
    display = str(raw.get("display", key)).strip() or key
    description = str(raw.get("description", "")).strip()
    icon = str(raw.get("icon", "")).strip()
    port_raw = raw.get("port", 0)
    try:
        port = int(port_raw) if port_raw not in (None, "") else 0
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail=f"Invalid port for {key!r}: {port_raw!r}")
    if port < 0 or port > 65535:
        raise HTTPException(status_code=400,
                            detail=f"Port out of range for {key!r}: {port}")
    return {
        "key": key,
        "display": display,
        "description": description,
        "icon": icon,
        "port": port,
    }


@app.get("/api/v1/standard-services/config")
async def get_standard_services_config():
    items = _load_standard_services_config()
    normalized: List[dict] = []
    for it in items:
        try:
            normalized.append(_normalize_standard_service_item(it))
        except HTTPException:
            continue
    return {"items": normalized}


@app.put("/api/v1/standard-services/config")
async def put_standard_services_config(payload: dict):
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise HTTPException(status_code=400,
                            detail="Body must be {items: [...]}")
    normalized: List[dict] = [_normalize_standard_service_item(it) for it in items]
    seen = set()
    for it in normalized:
        if it["key"] in seen:
            raise HTTPException(status_code=400,
                                detail=f"Duplicate key: {it['key']}")
        seen.add(it["key"])
    _save_standard_services_config(normalized)
    return {"items": normalized}


@app.get("/api/v1/services/{service_name}")
async def get_service_detail(service_name: str):
    _require_portainer()
    try:
        inspect = await portainer.container_inspect(service_name)
        stats = {}
        try:
            stats = await portainer.container_stats(service_name)
        except PortainerError:
            pass
        image = (inspect.get("Config") or {}).get("Image", "unknown")
        return {
            "name": service_name,
            "status": (inspect.get("State") or {}).get("Status", "unknown"),
            "image": image,
            "created": inspect.get("Created"),
            "cpu_usage": ((stats.get("cpu_stats") or {}).get("cpu_usage") or {}).get("total_usage", 0),
            "memory_usage": (stats.get("memory_stats") or {}).get("usage", 0),
            "memory_limit": (stats.get("memory_stats") or {}).get("limit", 0),
        }
    except PortainerError as e:
        raise _portainer_error_to_http(e)


@app.post("/api/v1/services/{service_name}/start")
async def start_service(service_name: str):
    if _is_standard_service(service_name) or service_name in SYSTEMD_SERVICES:
        _license_valid_or_403()

    if service_name in SYSTEMD_SERVICES:
        try:
            result = subprocess.run(["sudo", "systemctl", "start", service_name],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return {"success": True, "message": f"Service {service_name} started"}
            raise HTTPException(status_code=500, detail=result.stderr)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    _require_portainer()
    try:
        await portainer.container_start(service_name)
        return {"success": True, "message": f"Service {service_name} started"}
    except PortainerError as e:
        raise _portainer_error_to_http(e)


@app.post("/api/v1/services/{service_name}/stop")
async def stop_service(service_name: str):
    if service_name in SYSTEMD_SERVICES:
        try:
            result = subprocess.run(["sudo", "systemctl", "stop", service_name],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return {"success": True, "message": f"Service {service_name} stopped"}
            raise HTTPException(status_code=500, detail=result.stderr)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    _require_portainer()
    try:
        await portainer.container_stop(service_name, timeout=30)
        return {"success": True, "message": f"Service {service_name} stopped"}
    except PortainerError as e:
        raise _portainer_error_to_http(e)


@app.post("/api/v1/services/{service_name}/restart")
async def restart_service(service_name: str):
    if _is_standard_service(service_name) or service_name in SYSTEMD_SERVICES:
        _license_valid_or_403()

    if service_name in SYSTEMD_SERVICES:
        try:
            result = subprocess.run(["sudo", "systemctl", "restart", service_name],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return {"success": True, "message": f"Service {service_name} restarted"}
            raise HTTPException(status_code=500, detail=result.stderr)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    _require_portainer()
    try:
        await portainer.container_restart(service_name, timeout=30)
        return {"success": True, "message": f"Service {service_name} restarted"}
    except PortainerError as e:
        raise _portainer_error_to_http(e)


@app.get("/api/v1/services/{service_name}/logs")
async def get_service_logs(service_name: str, tail: int = 100):
    if service_name in SYSTEMD_SERVICES:
        try:
            result = subprocess.run(
                ["journalctl", "-u", service_name, "-n", str(tail), "--no-pager"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return {"logs": result.stdout.split("\n")}
            raise HTTPException(status_code=500, detail=result.stderr)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    _require_portainer()
    try:
        raw = await portainer.container_logs_bytes(service_name, tail=tail, timestamps=True)
        text = demux_docker_log_stream(raw)
        return {"logs": text.split("\n")}
    except PortainerError as e:
        raise _portainer_error_to_http(e)


# ============================================================
# 自定义服务 (Custom services) - 基于 Portainer + spec.json
# ============================================================

# 容器 Label 命名 (Portainer / Docker 原生支持)
LABEL_CATEGORY = "arbore.category"           # "custom" | "standard"
LABEL_SERVICE = "arbore.service_name"        # 服务逻辑名, 如 "my-api"
LABEL_DESCRIPTION = "arbore.description"
LABEL_ICON = "arbore.icon"
LABEL_HOST_PORT = "arbore.host_port"
LABEL_CONTAINER_PORT = "arbore.container_port"
LABEL_MANAGED_BY = "arbore.managed_by"

CATEGORY_CUSTOM = "custom"
CUSTOM_PORT_MIN = 7000
CUSTOM_PORT_MAX = 7999

CUSTOM_CONTAINER_NAME_PREFIX = "arbore-"
# Optional docker network that Arbore compose uses; containers are attached when it exists
ARBORE_NETWORK_NAME = os.environ.get("ARBORE_NETWORK_NAME", "arbore-network")
DEFAULT_RESTART_POLICY = os.environ.get("ARBORE_RESTART_POLICY", "unless-stopped")


class CustomServiceUpdate(BaseModel):
    description: Optional[str] = None
    icon: Optional[str] = None
    port: Optional[int] = None
    container_port: Optional[int] = None
    env_vars: Optional[str] = None       # JSON string {"K":"V"}
    volumes: Optional[str] = None        # JSON array ["host:cont[:ro]", ...]
    memory_limit_mb: Optional[int] = None
    memory_reservation_mb: Optional[int] = None


# -------------------- spec.json helpers --------------------

def _default_spec(name: str) -> dict:
    return {
        "name": name,
        "description": f"{name} service",
        "icon": "Box",
        "image": f"{name}:latest",
        "host_port": 0,
        "container_port": 0,
        "env_vars": {},
        "volumes": [],
        "memory_limit_mb": None,
        "memory_reservation_mb": None,
        "has_doc": False,
    }


def _read_spec(name: str) -> Optional[dict]:
    path = _custom_service_spec_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        data.setdefault("name", name)
        return data
    except Exception as e:
        logging.warning("Read spec %s failed: %s", path, e)
        return None


def _write_spec(name: str, spec: dict) -> None:
    path = _custom_service_spec_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)


def _delete_spec_dir(name: str) -> None:
    d = os.path.join(get_project_root(), "config", "custom-services", name)
    if os.path.exists(d):
        try:
            shutil.rmtree(d)
        except Exception as e:
            logging.warning("Delete spec dir %s failed: %s", d, e)


def _write_env_file(name: str, env_vars: Dict[str, str]) -> Optional[str]:
    """Persist env vars to config/custom-services/<name>/.env with 0600 perms.

    The file is only used for human inspection / backup; the authoritative copy
    is Docker's container Env field, which we always pass on creation.
    """
    if not env_vars:
        return None
    path = _custom_service_env_path(name)
    with open(path, "w", encoding="utf-8") as f:
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def _parse_env_json(env_vars: Optional[str]) -> Dict[str, str]:
    if not env_vars or not env_vars.strip():
        return {}
    try:
        obj = json.loads(env_vars)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"env_vars JSON error: {e}")
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="env_vars must be a JSON object")
    out: Dict[str, str] = {}
    for k, v in obj.items():
        if not isinstance(k, str):
            raise HTTPException(status_code=400, detail="env_vars keys must be strings")
        out[k] = "" if v is None else str(v)
    return out


def _parse_volumes_json(volumes: Optional[str]) -> List[str]:
    if not volumes or not volumes.strip():
        return []
    try:
        arr = json.loads(volumes)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"volumes JSON error: {e}")
    if not isinstance(arr, list):
        raise HTTPException(status_code=400, detail="volumes must be a JSON array")
    out: List[str] = []
    for v in arr:
        if not isinstance(v, str) or ":" not in v:
            raise HTTPException(status_code=400,
                                detail=f"volume must be 'host:container[:ro]': {v}")
        out.append(v)
    return out


# -------------------- listing & helpers --------------------

async def _list_custom_containers() -> List[dict]:
    """Return Portainer container summaries for arbore-managed custom services."""
    try:
        return await portainer.containers_list(
            all=True,
            label_filters=[f"{LABEL_CATEGORY}={CATEGORY_CUSTOM}"],
        )
    except PortainerError as e:
        raise _portainer_error_to_http(e)


def _spec_from_labels_and_inspect(name: str, inspect: Optional[dict]) -> dict:
    """Best-effort build of a service dict from Docker labels when spec.json is missing."""
    spec = _default_spec(name)
    if not inspect:
        return spec
    cfg = inspect.get("Config") or {}
    labels = cfg.get("Labels") or {}
    spec["description"] = labels.get(LABEL_DESCRIPTION, spec["description"])
    spec["icon"] = labels.get(LABEL_ICON, spec["icon"])
    spec["image"] = cfg.get("Image") or spec["image"]
    try:
        spec["host_port"] = int(labels.get(LABEL_HOST_PORT) or 0)
    except ValueError:
        spec["host_port"] = 0
    try:
        spec["container_port"] = int(labels.get(LABEL_CONTAINER_PORT) or 0)
    except ValueError:
        spec["container_port"] = 0
    host_config = inspect.get("HostConfig") or {}
    spec["memory_limit_mb"] = bytes_to_mb(host_config.get("Memory"))
    spec["memory_reservation_mb"] = bytes_to_mb(host_config.get("MemoryReservation"))
    return spec


def _service_view(spec: dict, inspect: Optional[dict]) -> dict:
    """Build the response object the frontend expects."""
    status = "not_found"
    health = "unknown"
    container_id: Optional[str] = None
    ports_display: List[str] = []
    if inspect:
        state = inspect.get("State") or {}
        status = state.get("Status", "unknown")
        health = (state.get("Health") or {}).get("Status", "unknown")
        container_id = (inspect.get("Id") or "")[:12]
        port_bindings = ((inspect.get("NetworkSettings") or {}).get("Ports") or {})
        for cport, host_ports in port_bindings.items():
            if host_ports:
                for hp in host_ports:
                    ports_display.append(f"{hp['HostPort']}:{cport.split('/')[0]}")

    return {
        "name": spec["name"],
        "port": spec.get("host_port") or 0,
        "container_port": spec.get("container_port") or spec.get("host_port") or 0,
        "endpoint": f"/{spec['name']}",
        "description": spec.get("description") or f"{spec['name']} service",
        "icon": spec.get("icon") or "Box",
        "memory_limit_mb": spec.get("memory_limit_mb"),
        "memory_reservation_mb": spec.get("memory_reservation_mb"),
        "has_doc": bool(spec.get("has_doc")),
        "status": status,
        "health": health,
        "container_id": container_id,
        "ports_display": ports_display,
    }


def _validate_name(name: str) -> None:
    if not re.match(r"^[a-z0-9-]+$", name):
        raise HTTPException(status_code=400, detail="Service name: lowercase, digits, '-' only")


def _validate_port(port: int) -> None:
    if not (CUSTOM_PORT_MIN <= port <= CUSTOM_PORT_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"Custom service port must be in range {CUSTOM_PORT_MIN}-{CUSTOM_PORT_MAX}",
        )


async def _collect_used_ports(exclude_name: Optional[str] = None) -> Tuple[Dict[int, str], Dict[str, int]]:
    """Return ({port: service_name}, {service_name: port}) for all known custom services."""
    port_to_name: Dict[int, str] = {}
    name_to_port: Dict[str, int] = {}

    # From local specs (authoritative for declared config)
    cs_root = _custom_services_dir()
    if os.path.isdir(cs_root):
        for entry in os.listdir(cs_root):
            sub = os.path.join(cs_root, entry)
            if not os.path.isdir(sub):
                continue
            spec = _read_spec(entry)
            if spec and spec.get("host_port") and entry != exclude_name:
                port_to_name[int(spec["host_port"])] = entry
                name_to_port[entry] = int(spec["host_port"])

    # Also scan Portainer (in case specs got out of sync)
    if portainer.configured:
        try:
            containers = await _list_custom_containers()
            for c in containers:
                labels = (c.get("Labels") or {})
                if labels.get(LABEL_CATEGORY) != CATEGORY_CUSTOM:
                    continue
                sname = labels.get(LABEL_SERVICE) or ""
                if sname == exclude_name or not sname:
                    continue
                try:
                    hp = int(labels.get(LABEL_HOST_PORT) or 0)
                except ValueError:
                    hp = 0
                if hp:
                    port_to_name.setdefault(hp, sname)
                    name_to_port.setdefault(sname, hp)
        except HTTPException:
            pass
    return port_to_name, name_to_port


def _container_name_for(service_name: str) -> str:
    return f"{CUSTOM_CONTAINER_NAME_PREFIX}{service_name}"


def _build_create_config(spec: dict) -> dict:
    """Construct Docker /containers/create body from the service spec."""
    host_port = int(spec["host_port"])
    container_port = int(spec.get("container_port") or host_port)

    env_list = [f"{k}={v}" for k, v in (spec.get("env_vars") or {}).items()]
    env_list.append(f"PORT={container_port}")

    labels: Dict[str, str] = {
        LABEL_CATEGORY: CATEGORY_CUSTOM,
        LABEL_SERVICE: spec["name"],
        LABEL_DESCRIPTION: spec.get("description") or "",
        LABEL_ICON: spec.get("icon") or "Box",
        LABEL_HOST_PORT: str(host_port),
        LABEL_CONTAINER_PORT: str(container_port),
        LABEL_MANAGED_BY: "arbore-webadmin",
    }

    binds = list(spec.get("volumes") or [])

    host_config: Dict[str, object] = {
        "PortBindings": {
            f"{container_port}/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(host_port)}],
        },
        "Binds": binds,
        "RestartPolicy": {"Name": DEFAULT_RESTART_POLICY},
    }
    mem_bytes = memory_mb_to_bytes(spec.get("memory_limit_mb") or 0)
    mem_res_bytes = memory_mb_to_bytes(spec.get("memory_reservation_mb") or 0)
    if mem_bytes:
        host_config["Memory"] = mem_bytes
    if mem_res_bytes:
        host_config["MemoryReservation"] = mem_res_bytes

    networking_config: Optional[dict] = None
    # Attach to arbore-network when it exists; Portainer 404 in ping stage is non fatal
    if ARBORE_NETWORK_NAME:
        networking_config = {"EndpointsConfig": {ARBORE_NETWORK_NAME: {}}}

    body: Dict[str, object] = {
        "Image": spec["image"],
        "Env": env_list,
        "Labels": labels,
        "ExposedPorts": {f"{container_port}/tcp": {}},
        "HostConfig": host_config,
    }
    if networking_config:
        body["NetworkingConfig"] = networking_config
    return body


async def _create_and_start(spec: dict) -> dict:
    """Create + start a container from spec; caller must have ensured no conflict."""
    container_name = _container_name_for(spec["name"])

    # If arbore-network is set but missing, drop NetworkingConfig to avoid create failure
    body = _build_create_config(spec)
    if ARBORE_NETWORK_NAME and not await portainer.network_exists(ARBORE_NETWORK_NAME):
        body.pop("NetworkingConfig", None)

    try:
        created = await portainer.container_create(container_name, body)
    except PortainerError as e:
        raise _portainer_error_to_http(e)

    try:
        await portainer.container_start(container_name)
    except PortainerError as e:
        # Roll back dangling container so users can retry cleanly
        try:
            await portainer.container_remove(container_name, force=True)
        except Exception:  # pragma: no cover - best effort
            pass
        raise _portainer_error_to_http(e)
    return created


async def _recreate_container(spec: dict) -> None:
    """Stop + remove existing container (if any), then create+start a new one from spec."""
    container_name = _container_name_for(spec["name"])
    try:
        await portainer.container_stop(container_name, timeout=30)
    except PortainerNotFound:
        pass
    except PortainerError as e:
        logging.warning("Stop before recreate failed for %s: %s", container_name, e)
    try:
        await portainer.container_remove(container_name, force=True)
    except PortainerNotFound:
        pass
    except PortainerError as e:
        logging.warning("Remove before recreate failed for %s: %s", container_name, e)
    await _create_and_start(spec)


# -------------------- streaming upload --------------------

async def _upload_file_to_portainer_load(upload: UploadFile) -> str:
    """Stream a FastAPI UploadFile into Portainer /images/load without buffering."""
    chunk_size = 1024 * 1024  # 1 MiB per chunk
    total = 0

    async def _iter() -> AsyncIterator[bytes]:
        nonlocal total
        while True:
            try:
                data = await upload.read(chunk_size)
            except Exception as ex:  # client disconnect / spool I/O fail
                logging.exception("Read upload chunk failed at %d bytes: %s",
                                  total, ex)
                raise
            if not data:
                break
            total += len(data)
            yield data
        logging.info("Tar upload streamed to Portainer: %d bytes (%.2f MB)",
                     total, total / (1024 * 1024))
    try:
        return await portainer.images_load_stream(_iter())
    except PortainerError as e:
        logging.error("Tar upload -> Portainer failed (status=%s): %s",
                      e.status_code, e.message)
        raise _portainer_error_to_http(e)
    except Exception as e:
        logging.exception("Tar upload unexpected error: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Tar upload internal error: {type(e).__name__}: {e}",
        )


def _extract_loaded_image_tag(body_text: str, fallback: str) -> str:
    """Parse Portainer /images/load streaming response for 'Loaded image:' lines.

    Response body is a stream of JSON objects or Docker-style plain text such
    as 'Loaded image: myimage:latest\\n'. We tolerate both forms.
    """
    tag: Optional[str] = None
    for line in (body_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # Plain text form
        m = re.search(r"Loaded image(?: ID)?:\s*([^\s]+)", line)
        if m:
            tag = m.group(1)
            continue
        # JSON form from Docker
        try:
            obj = json.loads(line)
        except Exception:
            continue
        stream = obj.get("stream") or obj.get("status") or ""
        m = re.search(r"Loaded image(?: ID)?:\s*([^\s]+)", stream)
        if m:
            tag = m.group(1)
    if not tag:
        return fallback
    # Ignore raw image IDs (sha256:...) - they can't be used as Image in create
    if tag.startswith("sha256:"):
        return fallback
    return tag


# -------------------- endpoints --------------------

@app.get("/api/v1/custom-services")
async def list_custom_services():
    """Return the union of known specs and running containers for the UI."""
    out: List[dict] = []
    seen: set = set()

    # 1) Iterate spec files (authoritative)
    cs_root = _custom_services_dir()
    if os.path.isdir(cs_root):
        for entry in sorted(os.listdir(cs_root)):
            sub = os.path.join(cs_root, entry)
            if not os.path.isdir(sub):
                continue
            spec = _read_spec(entry)
            if not spec:
                continue
            inspect: Optional[dict] = None
            if portainer.configured:
                try:
                    inspect = await portainer.container_inspect(_container_name_for(entry))
                except PortainerNotFound:
                    inspect = None
                except PortainerError as e:
                    logging.warning("Inspect %s failed: %s", entry, e)
            spec["has_doc"] = os.path.exists(_custom_service_doc_path(entry))
            out.append(_service_view(spec, inspect))
            seen.add(entry)

    # 2) Also surface label-managed containers with no local spec (e.g. after restore)
    if portainer.configured:
        try:
            containers = await _list_custom_containers()
        except HTTPException:
            containers = []
        for c in containers:
            labels = (c.get("Labels") or {})
            sname = labels.get(LABEL_SERVICE) or ""
            if not sname or sname in seen:
                continue
            try:
                inspect = await portainer.container_inspect(_container_name_for(sname))
            except PortainerError:
                inspect = None
            spec = _spec_from_labels_and_inspect(sname, inspect)
            spec["has_doc"] = os.path.exists(_custom_service_doc_path(sname))
            out.append(_service_view(spec, inspect))

    return {"services": out}


@app.post("/api/v1/custom-services/validate")
async def validate_custom_service(
    name: str = Form(...),
    port: int = Form(...),
    endpoint: str = Form(None),  # deprecated, kept for FE compat
):
    _license_valid_or_403()
    _validate_name(name)
    _validate_port(port)

    # Name uniqueness: spec dir must not exist
    if os.path.exists(_custom_service_spec_path(name)):
        raise HTTPException(status_code=400, detail=f"Service name '{name}' already exists")

    # Port uniqueness: neither spec nor running container may own the port
    port_to_name, _ = await _collect_used_ports()
    owner = port_to_name.get(port)
    if owner:
        raise HTTPException(status_code=400,
                            detail=f"Port {port} already used by service '{owner}'")
    return {"valid": True, "message": "OK"}


@app.post("/api/v1/custom-services/upload")
async def upload_custom_service(
    file: UploadFile = File(...),
    name: str = Form(...),
    port: int = Form(...),
    container_port: int = Form(None),
    endpoint: str = Form(None),  # deprecated
    description: str = Form(...),
    icon: str = Form("Box"),
    env_vars: str = Form(None),
    volumes: str = Form(None),
    memory_limit_mb: int = Form(None),
    memory_reservation_mb: int = Form(None),
    doc_file: UploadFile = File(None),
):
    """Streaming tar upload -> Portainer images/load -> containers/create + start.

    Returns NDJSON streaming response: each line is a JSON event with at least
    a "phase" field, allowing the frontend to render fine-grained progress and
    surface failures the moment they occur.

    Event shapes:
        {"phase": "validating",            "message": "..."}
        {"phase": "uploading_to_portainer","message": "..."}
        {"phase": "image_loaded",          "image": "x:y",  "message": "..."}
        {"phase": "creating_container",    "message": "..."}
        {"phase": "starting_container",    "message": "..."}
        {"phase": "saving_doc",            "message": "..."}
        {"phase": "done",                  "service": {...}, "message": "..."}
        {"phase": "error",                 "stage": "...",   "status": int,
         "message": "..."}
    """
    async def _gen() -> AsyncIterator[bytes]:
        def _ev(**kwargs) -> bytes:
            return (json.dumps(kwargs, ensure_ascii=False) + "\n").encode("utf-8")

        current_stage = "init"

        try:
            current_stage = "validating"
            yield _ev(phase="validating", message="校验服务名与端口")
            _license_valid_or_403()
            _require_portainer()
            _validate_name(name)
            _validate_port(port)

            if os.path.exists(_custom_service_spec_path(name)):
                raise HTTPException(status_code=400,
                                    detail=f"Service name '{name}' already exists")
            port_to_name, _unused = await _collect_used_ports()
            owner = port_to_name.get(port)
            if owner:
                raise HTTPException(status_code=400,
                                    detail=f"Port {port} already used by service '{owner}'")

            env_map = _parse_env_json(env_vars)
            volumes_list = _parse_volumes_json(volumes)

            current_stage = "uploading_to_portainer"
            yield _ev(phase="uploading_to_portainer",
                      message="正在将镜像传输到 Portainer 并加载")
            load_body = await _upload_file_to_portainer_load(file)
            image_tag = _extract_loaded_image_tag(load_body, fallback=f"{name}:latest")
            yield _ev(phase="image_loaded", image=image_tag,
                      message=f"镜像加载成功: {image_tag}")

            current_stage = "writing_spec"
            spec = _default_spec(name)
            spec.update({
                "description": description,
                "icon": icon or "Box",
                "image": image_tag,
                "host_port": port,
                "container_port": int(container_port) if container_port else port,
                "env_vars": env_map,
                "volumes": volumes_list,
                "memory_limit_mb": int(memory_limit_mb) if memory_limit_mb else None,
                "memory_reservation_mb": int(memory_reservation_mb) if memory_reservation_mb else None,
                "has_doc": False,
            })
            _custom_service_config_dir(name)
            _write_env_file(name, env_map)
            _write_spec(name, spec)

            current_stage = "creating_container"
            yield _ev(phase="creating_container", message="创建容器中")
            container_name = _container_name_for(name)
            body = _build_create_config(spec)
            if ARBORE_NETWORK_NAME and not await portainer.network_exists(ARBORE_NETWORK_NAME):
                body.pop("NetworkingConfig", None)
            try:
                await portainer.container_create(container_name, body)
            except PortainerError as e:
                raise _portainer_error_to_http(e)

            current_stage = "starting_container"
            yield _ev(phase="starting_container", message="启动容器中")
            try:
                await portainer.container_start(container_name)
            except PortainerError as e:
                # roll back dangling container
                try:
                    await portainer.container_remove(container_name, force=True)
                except Exception:  # pragma: no cover - best effort
                    pass
                raise _portainer_error_to_http(e)

            if doc_file is not None and doc_file.filename:
                if doc_file.filename.lower().endswith(".pdf"):
                    current_stage = "saving_doc"
                    yield _ev(phase="saving_doc", message="保存说明文档")
                    doc_path = _custom_service_doc_path(name)
                    with open(doc_path, "wb") as df:
                        shutil.copyfileobj(doc_file.file, df)
                    spec["has_doc"] = True
                    _write_spec(name, spec)

            yield _ev(
                phase="done",
                message=f"服务 {name} 部署成功",
                service={
                    "name": name,
                    "port": port,
                    "endpoint": f"/{name}",
                    "description": description,
                    "image_name": image_tag,
                },
            )
        except HTTPException as he:
            logging.error("Upload custom service '%s' failed at %s: %s",
                          name, current_stage, he.detail)
            yield _ev(phase="error", stage=current_stage,
                      status=he.status_code, message=str(he.detail))
        except PortainerError as pe:
            logging.error("Upload custom service '%s' Portainer error at %s: %s",
                          name, current_stage, pe.message)
            yield _ev(phase="error", stage=current_stage,
                      status=pe.status_code, message=pe.message)
        except Exception as e:  # pragma: no cover - safety net
            logging.exception("Upload custom service '%s' unexpected error at %s",
                              name, current_stage)
            yield _ev(phase="error", stage=current_stage,
                      status=500,
                      message=f"{type(e).__name__}: {e}")

    # X-Accel-Buffering: no -> tell nginx not to buffer the streaming response
    # so the frontend can render progress events in real time.
    return StreamingResponse(
        _gen(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


@app.delete("/api/v1/custom-services/{service_name}")
async def delete_custom_service(service_name: str):
    _require_portainer()
    _validate_name(service_name)
    container_name = _container_name_for(service_name)
    try:
        await portainer.container_remove(container_name, force=True)
    except PortainerNotFound:
        pass
    except PortainerError as e:
        logging.warning("Remove container %s failed: %s", container_name, e)
    _delete_spec_dir(service_name)
    return {"success": True, "message": f"Service {service_name} removed"}


@app.put("/api/v1/custom-services/{service_name}")
async def update_custom_service(service_name: str, update: CustomServiceUpdate):
    _require_portainer()
    _validate_name(service_name)
    spec = _read_spec(service_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found")

    needs_recreate = False

    if update.description is not None:
        spec["description"] = update.description
    if update.icon is not None:
        spec["icon"] = update.icon

    if update.port is not None:
        _validate_port(update.port)
        port_to_name, _ = await _collect_used_ports(exclude_name=service_name)
        owner = port_to_name.get(update.port)
        if owner:
            raise HTTPException(status_code=400,
                                detail=f"Port {update.port} already used by service '{owner}'")
        if update.port != spec.get("host_port"):
            spec["host_port"] = update.port
            needs_recreate = True

    if update.container_port is not None and update.container_port != spec.get("container_port"):
        spec["container_port"] = int(update.container_port)
        needs_recreate = True

    if update.env_vars is not None:
        env_map = _parse_env_json(update.env_vars)
        spec["env_vars"] = env_map
        _write_env_file(service_name, env_map)
        needs_recreate = True

    if update.volumes is not None:
        spec["volumes"] = _parse_volumes_json(update.volumes)
        needs_recreate = True

    if update.memory_limit_mb is not None:
        spec["memory_limit_mb"] = int(update.memory_limit_mb) or None
        needs_recreate = True

    if update.memory_reservation_mb is not None:
        spec["memory_reservation_mb"] = int(update.memory_reservation_mb) or None
        needs_recreate = True

    _write_spec(service_name, spec)

    if needs_recreate:
        await _recreate_container(spec)

    return {"success": True, "message": f"Service {service_name} updated"}


@app.post("/api/v1/custom-services/{service_name}/restart")
async def restart_custom_service(service_name: str):
    _require_portainer()
    _validate_name(service_name)
    spec = _read_spec(service_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
    # Re-create for env var changes; if caller only wants a soft restart we still
    # rebuild because env is baked into the container.
    await _recreate_container(spec)
    return {"success": True, "message": f"Service {service_name} restarted"}


@app.post("/api/v1/custom-services/{service_name}/start")
async def start_custom_service(service_name: str):
    _require_portainer()
    _validate_name(service_name)
    try:
        await portainer.container_start(_container_name_for(service_name))
        return {"success": True, "message": f"Service {service_name} started"}
    except PortainerError as e:
        raise _portainer_error_to_http(e)


@app.post("/api/v1/custom-services/{service_name}/stop")
async def stop_custom_service(service_name: str):
    _require_portainer()
    _validate_name(service_name)
    try:
        await portainer.container_stop(_container_name_for(service_name), timeout=30)
        return {"success": True, "message": f"Service {service_name} stopped"}
    except PortainerError as e:
        raise _portainer_error_to_http(e)


@app.get("/api/v1/custom-services/{service_name}/env")
async def get_service_env_vars(service_name: str):
    _validate_name(service_name)
    spec = _read_spec(service_name)
    env_vars = (spec or {}).get("env_vars") or {}
    # Fallback to .env file if spec lacks env_vars
    if not env_vars:
        env_path = _custom_service_env_path(service_name)
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            env_vars[k.strip()] = v.strip()
            except Exception as e:
                logging.warning("Read .env %s failed: %s", service_name, e)
    return {"env_vars": env_vars}


@app.get("/api/v1/custom-services/{service_name}/volumes")
async def get_service_volumes(service_name: str):
    _validate_name(service_name)
    spec = _read_spec(service_name)
    volumes = (spec or {}).get("volumes") or []
    return {"volumes": volumes}


@app.post("/api/v1/custom-services/{service_name}/doc")
async def upload_service_doc(service_name: str, doc_file: UploadFile = File(...)):
    _validate_name(service_name)
    if not doc_file.filename or not doc_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF allowed")
    spec = _read_spec(service_name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
    doc_path = _custom_service_doc_path(service_name)
    with open(doc_path, "wb") as f:
        shutil.copyfileobj(doc_file.file, f)
    spec["has_doc"] = True
    _write_spec(service_name, spec)
    return {"success": True, "message": "Doc uploaded"}


@app.get("/api/v1/custom-services/{service_name}/doc")
async def get_service_doc(service_name: str):
    _validate_name(service_name)
    doc_path = _custom_service_doc_path(service_name)
    if not os.path.exists(doc_path):
        raise HTTPException(status_code=404, detail="Doc not found")
    return FileResponse(doc_path, media_type="application/pdf",
                        filename=f"{service_name}-doc.pdf")


@app.delete("/api/v1/custom-services/{service_name}/doc")
async def delete_service_doc(service_name: str):
    _validate_name(service_name)
    doc_path = _custom_service_doc_path(service_name)
    if os.path.exists(doc_path):
        try:
            os.remove(doc_path)
        except Exception as e:
            logging.warning("Delete doc %s failed: %s", doc_path, e)
    spec = _read_spec(service_name)
    if spec:
        spec["has_doc"] = False
        _write_spec(service_name, spec)
    return {"success": True, "message": "Doc removed"}


@app.get("/api/v1/custom-services/available-port")
async def get_available_port_api():
    port_to_name, _ = await _collect_used_ports()
    for port in range(CUSTOM_PORT_MIN, CUSTOM_PORT_MAX + 1):
        if port not in port_to_name:
            return {"port": port}
    raise HTTPException(status_code=400,
                        detail=f"No free port in {CUSTOM_PORT_MIN}-{CUSTOM_PORT_MAX}")


# ============================================================
# Entrypoint
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8002)
