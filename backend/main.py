"""
Arbore Web管理界面 - 后端 API
Arbore Web Admin Backend API

本模块是 Arbore AI Host 管理控制台在服务端的唯一入口，负责对外暴露一组
统一且安全的 HTTP API，用于驱动前端界面展示容器状态、系统资源信息、
许可证校验结果以及自定义服务编排等功能。

This module serves as the central backend entrypoint for the Arbore AI Host
management console.  It exposes a well‑structured and security‑oriented HTTP
API that powers the frontend dashboard, including container status querying,
system resource inspection, license verification and custom‑service orchestration.

设计要点（中文）:
1. 统一入口：所有前端调用均通过本 FastAPI 应用进行，便于权限控制和审计。
2. 安全访问 Docker：通过本地 /var/run/docker.sock 或 HTTP API 访问 Docker，
   并在初始化时做多种失败兜底，避免异常导致整个控制台不可用。
3. 软著友好：代码中保留了相对完整的业务语义注释，便于阅读和后续维护，
   同时可作为软件著作权登记时的技术说明依据。
4. 可运维性：API 自身的运行日志会写入独立文件，配合前端「日志查看」页面，
   运维人员可以在浏览器中直接查看后台行为。

Key design points (English):
1. Single entrypoint: every frontend interaction goes through this FastAPI
   application, which makes authorization, logging and future extensions easier.
2. Docker access hardening: the code tries multiple strategies to talk to the
   local Docker daemon, and degrades gracefully when the socket or permissions
   are not available, instead of failing the whole API.
3. Readability and IP support: extensive comments keep the intent of each
   subsystem clear (licensing, monitoring, service control), which is useful
   both for future maintainers and for software copyright registration.
4. Operability: the backend writes its own logs into an API specific log file;
   the frontend log viewer page can stream these logs to the browser so that
   operators can debug the platform without logging into the server.

注意：本文件中的注释为设计和运维解释性内容，不会参与任何运行时逻辑，
仅用于帮助理解系统架构、满足文档与代码行数要求。
Note: all the comments in this file are descriptive only, they never change
the runtime behavior of the API and are safe to keep even in production.
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import docker
import psutil
import os
import subprocess
import logging
import re
import shutil
import json
import hmac
from typing import List, Dict, Optional
from datetime import datetime
from pydantic import BaseModel
import threading
import time
import signal
import tarfile
import tempfile
from packaging import version as pkg_version

from license_utils import (
    get_host_hardware_fingerprint,
    load_license,
    save_license,
    validate_license,
    get_license_secret,
    compute_validation_code,
)

# 版本信息
API_VERSION = "1.1.5"
BUILD_TIME = "2026-03-13T12:00:00Z"  # 构建时更新此时间戳

app = FastAPI(title="Arbore Web Admin API", version=API_VERSION)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制为前端域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 控制台服务日志写入文件，便于在「日志查看」界面查看
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_log_dir, exist_ok=True)
_api_log_file = os.path.join(_log_dir, "api.log")
_handler = logging.FileHandler(_api_log_file, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.root.addHandler(_handler)
logging.root.setLevel(logging.INFO)
logging.info("Web Admin API 启动，日志将写入 %s", _api_log_file)

# Docker客户端
# 清除可能干扰的环境变量
import os
for env_var in ['DOCKER_HOST', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH']:
    os.environ.pop(env_var, None)

# 检查Docker socket文件是否存在
docker_socket_path = '/var/run/docker.sock'
if os.path.exists(docker_socket_path):
    print(f"Docker socket found at {docker_socket_path}")
    stat_info = os.stat(docker_socket_path)
    print(f"Socket permissions: {oct(stat_info.st_mode)}")
    print(f"Socket owner UID: {stat_info.st_uid}, GID: {stat_info.st_gid}")
else:
    print(f"Warning: Docker socket not found at {docker_socket_path}")

docker_client = None
docker_api = None

# 尝试多种方式初始化Docker客户端
try:
    # 方法1: 直接使用socket文件路径（不使用unix://前缀）
    docker_api = docker.APIClient(base_url='unix:///var/run/docker.sock')
    docker_api.ping()
    print("Docker APIClient initialized successfully (method 1)")
    docker_client = docker.DockerClient(base_url='unix:///var/run/docker.sock')
    docker_client.ping()
    print("Docker DockerClient initialized successfully")
except Exception as e1:
    print(f"Method 1 failed: {e1}")
    try:
        # 方法2: 使用环境变量方式
        os.environ['DOCKER_HOST'] = 'unix:///var/run/docker.sock'
        docker_api = docker.APIClient()
        docker_api.ping()
        print("Docker APIClient initialized successfully (method 2)")
        docker_client = docker.DockerClient()
        docker_client.ping()
        print("Docker DockerClient initialized successfully (method 2)")
    except Exception as e2:
        print(f"Method 2 failed: {e2}")
        try:
            # 方法3: 使用requests直接调用Docker HTTP API
            import requests_unixsocket
            docker_api = None  # 标记为使用HTTP API
            docker_client = None
            print("Will use HTTP API fallback for Docker operations")
        except Exception as e3:
            print(f"All methods failed: {e3}")
            import traceback
            traceback.print_exc()
            docker_client = None
            docker_api = None


# 标准服务定期许可证校验：每 48 小时执行一次，未通过则自动停止标准服务
LICENSE_CHECK_INTERVAL_SEC = 48 * 3600  # 48 hours


def _run_license_periodic_check():
    """后台线程：每 48 小时校验许可证，未通过则停止标准服务"""
    while True:
        time.sleep(LICENSE_CHECK_INTERVAL_SEC)
        try:
            valid, error_code, _ = validate_license(API_VERSION)
            if valid:
                continue
            # 许可证无效：停止标准 Docker 服务
            if docker_client:
                for name in STANDARD_DOCKER_SERVICES:
                    try:
                        c = docker_client.containers.get(name)
                        if c.status == "running":
                            c.stop()
                            print(f"License invalid: stopped standard service {name}")
                    except Exception as e:
                        if "NotFound" not in str(type(e).__name__):
                            print(f"License check stop {name}: {e}")
            # 停止标准 systemd 服务
            for name in STANDARD_SYSTEMD_SERVICES:
                try:
                    subprocess.run(
                        ["sudo", "systemctl", "stop", name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except Exception as e:
                    print(f"License check stop systemd {name}: {e}")
        except Exception as e:
            print(f"License periodic check error: {e}")


@app.on_event("startup")
def start_license_check_thread():
    """启动后开启 48 小时周期许可证校验线程"""
    t = threading.Thread(target=_run_license_periodic_check, daemon=True)
    t.start()
    print("License periodic check thread started (interval: 48h)")


@app.get("/")
async def root():
    """健康检查"""
    return {
        "status": "ok",
        "service": "arbore-web-admin-api",
        "version": API_VERSION,
        "build_time": BUILD_TIME
    }

@app.get("/api/v1/version")
async def get_version():
    """获取API版本信息"""
    return {
        "version": API_VERSION,
        "build_time": BUILD_TIME,
        "docker_client_available": docker_client is not None,
        "docker_api_available": docker_api is not None
    }


# ==================== OTA 远程更新 ====================

UPDATE_CHECK_INTERVAL_SEC = 3600  # 每小时检查一次
OTA_ENABLED = os.environ.get("ARBORE_OTA_DISABLED", "").lower() not in ("1", "true", "yes")

_update_info_cache = {
    "has_update": False,
    "remote_version": None,
    "build_time": None,
    "changes": [],
    "last_check": None,
    "error": None,
}
_update_lock = threading.Lock()


def _get_update_config():
    """读取更新服务器配置"""
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(backend_dir, "..", "config", "update-config.json")
    config_path = os.path.normpath(config_path)
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    env_url = os.environ.get("ARBORE_UPDATE_URL")
    if env_url:
        return {"update_url": env_url, "enabled": True}
    return {"update_url": "", "enabled": False}


def _save_update_config(config: dict):
    """保存更新服务器配置"""
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(backend_dir, "..", "config")
    config_dir = os.path.normpath(config_dir)
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "update-config.json")
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _compare_versions(local_ver: str, remote_ver: str) -> bool:
    """远程版本是否高于本地版本"""
    try:
        return pkg_version.parse(remote_ver) > pkg_version.parse(local_ver)
    except Exception:
        return remote_ver != local_ver


def _check_remote_update():
    """检查远程服务器的最新版本（只要配置了 update_url 即会拉取；与「启用自动检测」无关，便于仅用手动「立即检查」）。"""
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
        req = urllib.request.Request(version_url, headers={"User-Agent": f"Arbore-WebAdmin/{API_VERSION}"})
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
            print(f"OTA: new version available: {remote_ver} (current: {API_VERSION})")
        else:
            print(f"OTA: already up to date ({API_VERSION})")
    except Exception as e:
        print(f"OTA: check failed: {e}")
        with _update_lock:
            _update_info_cache["error"] = str(e)
            _update_info_cache["last_check"] = datetime.now().isoformat()


def _run_update_check_loop():
    """后台线程：定期检查远程更新（仅当「启用自动检测」为开且 URL 已配置时才会真正请求远程）"""
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
        print("OTA update check disabled via ARBORE_OTA_DISABLED env var")
        return
    t = threading.Thread(target=_run_update_check_loop, daemon=True)
    t.start()
    print(f"OTA update check thread started (interval: {UPDATE_CHECK_INTERVAL_SEC}s)")


@app.get("/api/v1/update/config")
async def get_update_config():
    """获取更新服务器配置"""
    config = _get_update_config()
    return {
        "update_url": config.get("update_url", ""),
        "enabled": config.get("enabled", False)
    }


@app.post("/api/v1/update/config")
async def set_update_config(update_url: str = Form(""), enabled: bool = Form(True)):
    """设置更新服务器地址"""
    config = {"update_url": update_url.strip(), "enabled": enabled}
    _save_update_config(config)
    if enabled and update_url.strip():
        threading.Thread(target=_check_remote_update, daemon=True).start()
    return {"success": True, "message": "Update config saved"}


@app.get("/api/v1/update/check")
async def check_update(force: bool = False):
    """检查是否有可用更新。force=true 时立即查询远程服务器"""
    if not OTA_ENABLED:
        return {"current_version": API_VERSION, "has_update": False, "ota_disabled": True}
    if force:
        _check_remote_update()
    with _update_lock:
        return {
            "current_version": API_VERSION,
            **_update_info_cache
        }


@app.post("/api/v1/update/apply")
async def apply_update():
    """下载并应用更新（前端dist + 后端源码），然后自动重启"""
    if not OTA_ENABLED:
        raise HTTPException(status_code=403, detail="OTA update is disabled via ARBORE_OTA_DISABLED environment variable")
    import urllib.request

    config = _get_update_config()
    if not config.get("update_url"):
        raise HTTPException(status_code=400, detail="未配置更新服务器地址")

    with _update_lock:
        if not _update_info_cache.get("has_update"):
            raise HTTPException(status_code=400, detail="当前已是最新版本")

    base_url = config["update_url"].rstrip("/")
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    web_admin_dir = os.path.normpath(os.path.join(backend_dir, ".."))
    frontend_dist_dir = os.path.join(web_admin_dir, "frontend", "dist")

    warnings = []

    try:
        # 1. 更新前端 dist
        frontend_url = f"{base_url}/frontend-dist.tar.gz"
        print(f"OTA: downloading frontend from {frontend_url}")
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp_path = tmp.name
                req = urllib.request.Request(frontend_url, headers={"User-Agent": f"Arbore-WebAdmin/{API_VERSION}"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    shutil.copyfileobj(resp, tmp)

            # 备份旧 dist
            dist_backup = frontend_dist_dir + ".bak"
            if os.path.exists(frontend_dist_dir):
                if os.path.exists(dist_backup):
                    shutil.rmtree(dist_backup)
                shutil.copytree(frontend_dist_dir, dist_backup)

            # 解压新 dist
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path=os.path.dirname(frontend_dist_dir))

            print("OTA: frontend updated successfully")
        except Exception as e:
            warnings.append(f"Frontend update failed: {e}")
            print(f"OTA: frontend update failed: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # 2. 更新后端源码
        backend_url = f"{base_url}/backend.tar.gz"
        print(f"OTA: downloading backend from {backend_url}")
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                tmp_path = tmp.name
                req = urllib.request.Request(backend_url, headers={"User-Agent": f"Arbore-WebAdmin/{API_VERSION}"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    shutil.copyfileobj(resp, tmp)

            # 解压到临时目录
            tmp_extract = tempfile.mkdtemp(prefix="arbore-backend-")
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(path=tmp_extract)

            # 只复制 .py 和 requirements.txt，不覆盖 config/ venv/ logs/
            preserve = {"venv", "config", "logs", "__pycache__", ".env"}
            extracted_backend = tmp_extract
            # 如果解压后有一层 backend/ 子目录，进入它
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
            print("OTA: backend files updated successfully")

            # 3. 检查 requirements.txt 是否变化，如果变化则自动安装
            venv_pip = os.path.join(backend_dir, "venv", "bin", "pip")
            req_file = os.path.join(backend_dir, "requirements.txt")
            if os.path.exists(venv_pip) and os.path.exists(req_file):
                try:
                    result = subprocess.run(
                        [venv_pip, "install", "-r", req_file],
                        capture_output=True, text=True, timeout=120
                    )
                    if result.returncode != 0:
                        warnings.append(f"pip install warning: {result.stderr[:200]}")
                    else:
                        print("OTA: pip dependencies updated")
                except Exception as e:
                    warnings.append(f"pip install failed: {e}")

        except Exception as e:
            warnings.append(f"Backend update failed: {e}")
            print(f"OTA: backend update failed: {e}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # 4. 延迟重启（让响应先返回客户端）
        def _delayed_restart():
            time.sleep(2)
            print("OTA: restarting service...")
            try:
                subprocess.run(
                    ["sudo", "systemctl", "restart", "arbore-web-admin-api"],
                    timeout=30, capture_output=True, text=True
                )
            except Exception:
                print("OTA: systemctl restart failed, sending SIGTERM to self")
                os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_delayed_restart, daemon=True).start()

        return {
            "success": True,
            "message": "Update applied. Service is restarting, please wait a few seconds and refresh the page.",
            "warnings": warnings
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


# ==================== 许可证 API ====================

def _license_valid_or_403():
    """若许可证无效则抛出 403，否则返回 (True, license_info)。"""
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
    return msg.get(code, "License check failed")


@app.get("/api/v1/license")
async def get_license():
    """获取当前许可证信息及校验状态"""
    valid, error_code, info = validate_license(API_VERSION)
    fingerprint, display_id = get_host_hardware_fingerprint()
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
    """获取宿主机硬件指纹（仅宿主机，非容器），用于注册页展示"""
    fingerprint, display_id = get_host_hardware_fingerprint()
    return {"hostFingerprint": display_id, "rawAvailable": fingerprint is not None}


@app.post("/api/v1/license/register")
async def register_license(
    companyId: str = Form(..., alias="companyId"),
    validationCode: str = Form(..., alias="validationCode"),
    companyName: str = Form(..., alias="companyName"),
):
    """注册许可证：校验码验证通过后写入 license.json"""
    secret = get_license_secret()
    if not secret:
        raise HTTPException(status_code=503, detail={"code": "SECRET_NOT_CONFIGURED", "message": "Server license secret not configured"})
    fingerprint, display_id = get_host_hardware_fingerprint()
    if not fingerprint:
        raise HTTPException(status_code=400, detail={"code": "HARDWARE_UNAVAILABLE", "message": "Host hardware fingerprint unavailable"})
    # 使用 display_id（host-xxx）与 validation-code-generator.js 的 hostId 一致
    expected = compute_validation_code(companyId, display_id, API_VERSION, secret)
    if not hmac.compare_digest(expected.upper(), validationCode.strip().upper()):
        raise HTTPException(status_code=400, detail={"code": "LICENSE_INVALID", "message": "Validation code invalid or not for this host"})
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
    """验证当前许可证是否有效"""
    valid, error_code, info = validate_license(API_VERSION)
    return {"valid": valid, "errorCode": error_code, "license": info}


def get_systemd_service_status(service_name: str) -> Dict:
    """获取 systemd 服务状态"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        is_active = result.stdout.strip() == 'active'
        
        result = subprocess.run(
            ['systemctl', 'is-enabled', service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        is_enabled = result.stdout.strip() == 'enabled'
        
        # 获取端口信息
        ports = []
        port_map = {
            'service-router': ['2026'],
            'service-pdf-to-png': ['2027'],
            'service-paddle-ocr': ['2028'],
            'service-tesseract-ocr': ['2029']
        }
        if service_name in port_map:
            ports = port_map[service_name]
        
        return {
            "name": service_name,
            "status": "running" if is_active else "stopped",
            "health": "healthy" if is_active else "unhealthy",
            "ports": ports,
            "enabled": is_enabled,
            "type": "systemd"
        }
    except Exception as e:
        print(f"Error checking systemd service {service_name}: {e}")
        return {
            "name": service_name,
            "status": "unknown",
            "health": "unknown",
            "ports": [],
            "enabled": False,
            "type": "systemd"
        }


# 标准服务列表（许可证未通过时禁止启动，且定期校验未通过时自动停止）
STANDARD_DOCKER_SERVICES = [
    "arbore-flow",
    "arbore-func",
    "arbore-postgres-nocobase",
    "arbore-postgres-vector",
    "arbore-ollama",
    "arbore-ollama-webui",
    "kanban-frontend",
    "kanban-backend",
]
STANDARD_SYSTEMD_SERVICES = []


@app.get("/api/v1/services")
async def get_services():
    """获取所有服务状态"""
    services = []
    docker_service_names = list(STANDARD_DOCKER_SERVICES)
    systemd_service_names = list(STANDARD_SYSTEMD_SERVICES)

    # 许可证状态（供前端禁用启动/重启）
    license_valid, license_error_code, _ = validate_license(API_VERSION)

    # 获取 Docker 服务状态
    service_names = docker_service_names
    
    # 优先使用docker_client，如果不可用则使用docker_api，最后使用HTTP API fallback
    if docker_client:
        try:
            containers = docker_client.containers.list(all=True)
            container_dict = {c.name: c for c in containers}
            
            for name in service_names:
                container = container_dict.get(name)
                if container:
                    status = container.status
                    health = "unknown"
                    try:
                        health_info = container.attrs.get("State", {}).get("Health", {})
                        health = health_info.get("Status", "unknown")
                    except:
                        pass
                    
                    ports = []
                    try:
                        port_bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {})
                        for container_port, host_ports in port_bindings.items():
                            if host_ports:
                                for hp in host_ports:
                                    ports.append(f"{hp['HostPort']}:{container_port.split('/')[0]}")
                    except:
                        pass
                    
                    services.append({
                        "name": name,
                        "status": status,
                        "health": health,
                        "ports": ports,
                    })
                else:
                    services.append({
                        "name": name,
                        "status": "not_found",
                        "health": "unknown",
                        "ports": []
                    })
        except Exception as e:
            print(f"Error using docker_client: {e}")
            if docker_api:
                try:
                    r = await get_services_api(service_names)
                    services = r.get("services", [])
                except Exception as e2:
                    print(f"Error using docker_api: {e2}")
                    r = await get_services_subprocess(service_names)
                    services = r.get("services", [])
            else:
                r = await get_services_subprocess(service_names)
                services = r.get("services", [])
    elif docker_api:
        try:
            r = await get_services_api(service_names)
            services = r.get("services", [])
        except Exception as e:
            print(f"Error using docker_api: {e}")
            r = await get_services_subprocess(service_names)
            services = r.get("services", [])
    else:
        r = await get_services_subprocess(service_names)
        services = r.get("services", [])

    # 添加 systemd 服务状态
    for systemd_name in systemd_service_names:
        systemd_status = get_systemd_service_status(systemd_name)
        services.append(systemd_status)

    return {
        "services": services,
        "licenseValid": license_valid,
        "licenseErrorCode": license_error_code,
    }


async def get_services_api(service_names):
    """使用docker.APIClient获取服务状态（fallback方法）"""
    services = []
    try:
        containers_data = docker_api.containers(all=True)
        container_dict = {c['Names'][0].lstrip('/'): c for c in containers_data}
        
        for name in service_names:
            container = container_dict.get(name)
            if container:
                status = container.get('State', 'unknown')
                health = "unknown"
                
                # 获取详细信息（包括健康状态）
                try:
                    inspect_data = docker_api.inspect_container(name)
                    state = inspect_data.get('State', {})
                    status = state.get('Status', status)
                    health_info = state.get('Health', {})
                    health = health_info.get('Status', 'unknown')
                    
                    # 获取端口映射
                    ports = []
                    port_bindings = inspect_data.get('NetworkSettings', {}).get('Ports', {})
                    for container_port, host_ports in port_bindings.items():
                        if host_ports:
                            for hp in host_ports:
                                ports.append(f"{hp['HostPort']}:{container_port.split('/')[0]}")
                except Exception as e:
                    print(f"Error inspecting container {name}: {e}")
                    ports = []
                
                services.append({
                    "name": name,
                    "status": status.lower() if status else "unknown",
                    "health": health,
                    "ports": ports,
                })
            else:
                services.append({
                    "name": name,
                    "status": "not_found",
                    "health": "unknown",
                    "ports": []
                })
    except Exception as e:
        print(f"Error in docker_api fallback: {e}")
        import traceback
        traceback.print_exc()
        # 返回默认状态
        for name in service_names:
            services.append({
                "name": name,
                "status": "unknown",
                "health": "unknown",
                "ports": []
            })
    
    return {"services": services}


async def get_services_subprocess(service_names):
    """使用Docker HTTP API获取服务状态（最后fallback方法）"""
    import requests_unixsocket
    import json
    
    services = []
    try:
        # 使用requests-unixsocket直接调用Docker HTTP API
        session = requests_unixsocket.Session()
        url = 'http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/json?all=1'
        
        response = session.get(url)
        if response.status_code == 200:
            containers_data = response.json()
            container_dict = {c['Names'][0].lstrip('/'): c for c in containers_data}
            
            for name in service_names:
                container = container_dict.get(name)
                if container:
                    status = container.get('State', 'unknown')
                    health = "unknown"
                    
                    # 获取详细信息（包括健康状态）
                    try:
                        inspect_url = f'http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/{name}/json'
                        inspect_response = session.get(inspect_url)
                        if inspect_response.status_code == 200:
                            inspect_data = inspect_response.json()
                            state = inspect_data.get('State', {})
                            status = state.get('Status', status)
                            health_info = state.get('Health', {})
                            health = health_info.get('Status', 'unknown')
                            
                            # 获取端口映射
                            ports = []
                            port_bindings = inspect_data.get('NetworkSettings', {}).get('Ports', {})
                            for container_port, host_ports in port_bindings.items():
                                if host_ports:
                                    for hp in host_ports:
                                        ports.append(f"{hp['HostPort']}:{container_port.split('/')[0]}")
                    except Exception as e:
                        print(f"Error inspecting container {name}: {e}")
                        ports = []
                    
                    services.append({
                        "name": name,
                        "status": status.lower() if status else "unknown",
                        "health": health,
                        "ports": ports,
                    })
                else:
                    services.append({
                        "name": name,
                        "status": "not_found",
                        "health": "unknown",
                        "ports": []
                    })
        else:
            raise Exception(f"Docker API returned {response.status_code}")
    except Exception as e:
        print(f"Error in HTTP API fallback: {e}")
        import traceback
        traceback.print_exc()
        # 返回默认状态
        for name in service_names:
            services.append({
                "name": name,
                "status": "unknown",
                "health": "unknown",
                "ports": []
            })
    
    return {"services": services}


@app.get("/api/v1/services/{service_name}")
async def get_service_detail(service_name: str):
    """获取单个服务详细信息"""
    if docker_client:
        try:
            container = docker_client.containers.get(service_name)
            stats = container.stats(stream=False)
            
            return {
                "name": service_name,
                "status": container.status,
                "image": container.image.tags[0] if container.image.tags else "unknown",
                "created": container.attrs.get("Created"),
                "cpu_usage": stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0),
                "memory_usage": stats.get("memory_stats", {}).get("usage", 0),
                "memory_limit": stats.get("memory_stats", {}).get("limit", 0),
            }
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
        except Exception as e:
            print(f"Error using docker_client: {e}")
            # Fallback to docker_api or HTTP API
            if docker_api:
                try:
                    return await get_service_detail_api(service_name)
                except Exception as e2:
                    print(f"Error using docker_api: {e2}")
                    raise HTTPException(status_code=503, detail="Docker client not available")
            else:
                raise HTTPException(status_code=503, detail="Docker client not available")
    elif docker_api:
        try:
            return await get_service_detail_api(service_name)
        except Exception as e:
            print(f"Error using docker_api: {e}")
            raise HTTPException(status_code=503, detail="Docker client not available")
    else:
        raise HTTPException(status_code=503, detail="Docker client not available")


async def get_service_detail_api(service_name: str):
    """使用docker_api获取服务详情"""
    try:
        inspect_data = docker_api.inspect_container(service_name)
        state = inspect_data.get('State', {})
        stats = docker_api.stats(service_name, stream=False)
        
        return {
            "name": service_name,
            "status": state.get('Status', 'unknown'),
            "image": inspect_data.get('Config', {}).get('Image', 'unknown'),
            "created": inspect_data.get('Created'),
            "cpu_usage": stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0),
            "memory_usage": stats.get("memory_stats", {}).get("usage", 0),
            "memory_limit": stats.get("memory_stats", {}).get("limit", 0),
        }
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_gpu_info():
    """通过 nvidia-smi 获取 GPU 使用情况，无 GPU 或不可用时返回空列表"""
    gpus = []
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
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
                util = int(parts[2].strip().replace("%", "") or 0)
                mem_used_mib = int(parts[3].strip().replace("MiB", "").strip() or 0)
                mem_total_mib = int(parts[4].strip().replace("MiB", "").strip() or 0)
                mem_used_bytes = mem_used_mib * 1024 * 1024
                mem_total_bytes = mem_total_mib * 1024 * 1024
                mem_percent = round(100.0 * mem_used_mib / mem_total_mib, 1) if mem_total_mib else 0
                gpus.append({
                    "index": idx,
                    "name": name,
                    "utilization_percent": min(100, max(0, util)),
                    "memory_used": mem_used_bytes,
                    "memory_total": mem_total_bytes,
                    "memory_percent": mem_percent,
                })
            except (ValueError, IndexError):
                continue
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return gpus


@app.get("/api/v1/system/resources")
async def get_system_resources():
    """获取系统资源使用情况（含 CPU、内存、磁盘、GPU）"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        gpus = _get_gpu_info()

        return {
            "cpu": {
                "percent": cpu_percent,
                "count": psutil.cpu_count()
            },
            "memory": {
                "total": memory.total,
                "used": memory.used,
                "available": memory.available,
                "percent": memory.percent
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent
            },
            "gpu": gpus,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/services/{service_name}/start")
async def start_service(service_name: str):
    """启动服务（支持 Docker 和 systemd）。标准服务需许可证有效方可启动。"""
    # 标准服务：许可证未通过则禁止启动
    if service_name in STANDARD_DOCKER_SERVICES or service_name in STANDARD_SYSTEMD_SERVICES:
        try:
            _license_valid_or_403()
        except HTTPException:
            raise

    # 检查是否是 systemd 服务
    systemd_services = ["service-router", "service-pdf-to-png", "service-paddle-ocr", "service-tesseract-ocr"]
    if service_name in systemd_services:
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'start', service_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return {"success": True, "message": f"Service {service_name} started"}
            else:
                raise HTTPException(status_code=500, detail=result.stderr)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # Docker 服务
    if docker_client:
        try:
            container = docker_client.containers.get(service_name)
            container.start()
            return {"success": True, "message": f"Service {service_name} started"}
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=503, detail="Docker client not available")


@app.post("/api/v1/services/{service_name}/stop")
async def stop_service(service_name: str):
    """停止服务（支持 Docker 和 systemd）"""
    # 检查是否是 systemd 服务
    systemd_services = ["service-router", "service-pdf-to-png", "service-paddle-ocr", "service-tesseract-ocr"]
    if service_name in systemd_services:
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'stop', service_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return {"success": True, "message": f"Service {service_name} stopped"}
            else:
                raise HTTPException(status_code=500, detail=result.stderr)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # Docker 服务
    if docker_client:
        try:
            container = docker_client.containers.get(service_name)
            container.stop()
            return {"success": True, "message": f"Service {service_name} stopped"}
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=503, detail="Docker client not available")


@app.post("/api/v1/services/{service_name}/restart")
async def restart_service(service_name: str):
    """重启服务（支持 Docker 和 systemd）。标准服务需许可证有效方可重启。"""
    # 标准服务：许可证未通过则禁止重启
    if service_name in STANDARD_DOCKER_SERVICES or service_name in STANDARD_SYSTEMD_SERVICES:
        try:
            _license_valid_or_403()
        except HTTPException:
            raise

    # 检查是否是 systemd 服务
    systemd_services = ["service-router", "service-pdf-to-png", "service-paddle-ocr", "service-tesseract-ocr"]
    if service_name in systemd_services:
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'restart', service_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return {"success": True, "message": f"Service {service_name} restarted"}
            else:
                raise HTTPException(status_code=500, detail=result.stderr)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # Docker 服务
    if docker_client:
        try:
            container = docker_client.containers.get(service_name)
            container.restart()
            return {"success": True, "message": f"Service {service_name} restarted"}
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        raise HTTPException(status_code=503, detail="Docker client not available")


@app.get("/api/v1/services/{service_name}/logs")
async def get_service_logs(service_name: str, tail: int = 100):
    """获取服务日志（支持 Docker 和 systemd）"""
    # 检查是否是 systemd 服务
    systemd_services = ["service-router", "service-pdf-to-png", "service-paddle-ocr", "service-tesseract-ocr"]
    if service_name in systemd_services:
        try:
            result = subprocess.run(
                ['journalctl', '-u', service_name, '-n', str(tail), '--no-pager'],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                logs = result.stdout.split('\n')
                return {"logs": logs}
            else:
                raise HTTPException(status_code=500, detail=result.stderr)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # Docker 服务
    if docker_client:
        try:
            container = docker_client.containers.get(service_name)
            logs = container.logs(tail=tail, timestamps=True).decode('utf-8')
            return {"logs": logs.split('\n')}
        except docker.errors.NotFound:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
        except Exception as e:
            print(f"Error using docker_client: {e}")
            # Fallback to docker_api or HTTP API
            if docker_api:
                try:
                    return await get_service_logs_api(service_name, tail)
                except Exception as e2:
                    print(f"Error using docker_api: {e2}")
                    return await get_service_logs_http(service_name, tail)
            else:
                return await get_service_logs_http(service_name, tail)
    elif docker_api:
        try:
            return await get_service_logs_api(service_name, tail)
        except Exception as e:
            print(f"Error using docker_api: {e}")
            return await get_service_logs_http(service_name, tail)
    else:
        return await get_service_logs_http(service_name, tail)


async def get_service_logs_api(service_name: str, tail: int = 100):
    """使用docker_api获取服务日志"""
    try:
        logs = docker_api.logs(service_name, tail=tail, timestamps=True).decode('utf-8')
        return {"logs": logs.split('\n')}
    except docker.errors.NotFound:
        raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
    except Exception as e:
        # Fallback to HTTP API
        return await get_service_logs_http(service_name, tail)


async def get_service_logs_http(service_name: str, tail: int = 100):
    """使用HTTP API获取服务日志（最后fallback）"""
    import requests_unixsocket
    try:
        session = requests_unixsocket.Session()
        url = f'http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/{service_name}/logs?tail={tail}&timestamps=1&stdout=1&stderr=1'
        response = session.get(url)
        if response.status_code == 200:
            logs = response.text.split('\n')
            return {"logs": logs}
        elif response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")
        else:
            raise HTTPException(status_code=500, detail=f"Docker API returned {response.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/system/ip")
async def get_system_ip():
    """获取当前服务器IP地址"""
    try:
        import socket
        import subprocess
        
        # 方法1: 通过hostname获取
        try:
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            if ip and not ip.startswith("127."):
                return {
                    "current_ip": ip,
                    "method": "hostname",
                    "hostname": hostname
                }
        except:
            pass
        
        # 方法2: 通过ip命令获取（Linux）
        try:
            result = subprocess.run(
                ['ip', 'route', 'get', '8.8.8.8'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                import re
                match = re.search(r'src\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
                if match:
                    ip = match.group(1)
                    return {
                        "current_ip": ip,
                        "method": "ip_route"
                    }
        except:
            pass
        
        # 方法3: 通过ifconfig获取
        try:
            result = subprocess.run(
                ['ifconfig'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                import re
                # 查找非127.0.0.1的IP地址
                matches = re.findall(r'inet\s+(\d+\.\d+\.\d+\.\d+)', result.stdout)
                for ip in matches:
                    if not ip.startswith("127.") and not ip.startswith("169.254."):
                        return {
                            "current_ip": ip,
                            "method": "ifconfig"
                        }
        except:
            pass
        
        # 方法4: 通过hostname -I获取
        try:
            result = subprocess.run(
                ['hostname', '-I'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                ips = result.stdout.strip().split()
                for ip in ips:
                    if not ip.startswith("127.") and not ip.startswith("169.254."):
                        return {
                            "current_ip": ip,
                            "method": "hostname_I"
                        }
        except:
            pass
        
        raise HTTPException(status_code=500, detail="无法检测服务器IP地址")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"检测IP地址失败: {str(e)}")


@app.get("/api/v1/system/config")
async def get_system_config():
    """获取系统配置（从.env文件）"""
    try:
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env_file = os.path.join(project_root, ".env")
        
        config = {}
        if os.path.exists(env_file):
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        
        # 获取当前IP
        current_ip_info = await get_system_ip()
        current_ip = current_ip_info.get("current_ip", "")
        
        # 获取配置的IP
        configured_ip = config.get("SERVER_IP", "")
        
        return {
            "current_ip": current_ip,
            "configured_ip": configured_ip,
            "needs_update": current_ip != configured_ip and configured_ip != "",
            "config": config
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取配置失败: {str(e)}")


@app.get("/api/v1/system/admin-logs")
async def get_admin_logs(tail: int = 200):
    """获取控制台服务（Web Admin API）自身日志，供界面「日志查看」使用"""
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "api.log")
    if not os.path.exists(log_file):
        return {"logs": ["日志文件尚未生成，请稍后重试或检查 backend/logs/api.log 是否存在。"]}
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        lines = [line.rstrip("\n") for line in lines]
        return {"logs": lines[-tail:] if len(lines) > tail else lines}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取日志失败: {str(e)}")


@app.post("/api/v1/system/config/update-ip")
async def update_system_ip():
    """更新系统IP地址配置"""
    try:
        import os
        import subprocess
        
        # 获取当前IP
        current_ip_info = await get_system_ip()
        new_ip = current_ip_info.get("current_ip", "")
        
        if not new_ip:
            raise HTTPException(status_code=400, detail="无法检测当前IP地址")
        
        # 获取项目根目录
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        script_path = os.path.join(project_root, "scripts", "update-server-ip.sh")
        
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail="IP更新脚本不存在")
        
        # 执行更新脚本
        result = subprocess.run(
            ['bash', script_path, new_ip],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"执行更新脚本失败: {result.stderr}"
            )
        
        # 重启相关Docker服务
        restart_services = ["arbore-flow", "arbore-nginx"]
        restart_results = []
        
        if docker_client:
            for service_name in restart_services:
                try:
                    container = docker_client.containers.get(service_name)
                    container.restart(timeout=60)
                    restart_results.append({
                        "service": service_name,
                        "status": "restarted"
                    })
                except docker.errors.NotFound:
                    restart_results.append({
                        "service": service_name,
                        "status": "not_found"
                    })
                except Exception as e:
                    restart_results.append({
                        "service": service_name,
                        "status": "error",
                        "error": str(e)
                    })
        else:
            # 使用docker-compose命令
            try:
                compose_result = subprocess.run(
                    _docker_compose_cmd() + ["restart"] + restart_services,
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if compose_result.returncode == 0:
                    for service_name in restart_services:
                        restart_results.append({
                            "service": service_name,
                            "status": "restarted"
                        })
                else:
                    restart_results.append({
                        "service": "all",
                        "status": "error",
                        "error": compose_result.stderr
                    })
            except Exception as e:
                restart_results.append({
                    "service": "all",
                    "status": "error",
                    "error": str(e)
                })
        
        return {
            "success": True,
            "new_ip": new_ip,
            "script_output": result.stdout,
            "restart_results": restart_results,
            "message": f"IP地址已更新为 {new_ip}，相关服务已重启"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新IP配置失败: {str(e)}")


# ==================== 自定义服务管理 API ====================

class CustomServiceCreate(BaseModel):
    name: str
    port: int
    endpoint: str
    description: str
    icon: Optional[str] = "Box"
    image_name: Optional[str] = None

class CustomServiceUpdate(BaseModel):
    name: Optional[str] = None
    port: Optional[int] = None
    container_port: Optional[int] = None  # 容器内端口（可选）
    endpoint: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    env_vars: Optional[str] = None  # 环境变量JSON配置
    volumes: Optional[str] = None  # 卷挂载JSON配置，格式: ["host_path:container_path"]
    memory_limit_mb: Optional[int] = None  # 内存限制（MB），重启后生效
    memory_reservation_mb: Optional[int] = None  # 内存预留（MB）

def get_project_root():
    """获取项目根目录，支持通过 ARBORE_PROJECT_ROOT 环境变量指定（Docker 容器部署时必须设置）"""
    env_root = os.environ.get('ARBORE_PROJECT_ROOT')
    if env_root:
        return env_root
    current_file = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(current_file)))


def _docker_compose_cmd():
    """统一使用 docker compose（V2）。环境须安装 Docker Compose 插件，不在此做 fallback。"""
    return ["docker", "compose"]

def _ensure_docker_compose_file() -> str:
    """确保 docker-compose.yml 存在，不存在则自动创建基础模板。返回文件路径。"""
    project_root = get_project_root()
    docker_compose_path = os.path.join(project_root, "docker-compose.yml")
    if not os.path.exists(docker_compose_path):
        initial_content = """services:

networks:
  arbore-network:
    driver: bridge
"""
        os.makedirs(os.path.dirname(docker_compose_path), exist_ok=True)
        with open(docker_compose_path, 'w', encoding='utf-8') as f:
            f.write(initial_content)
        print(f"自动创建 docker-compose.yml: {docker_compose_path}")
    return docker_compose_path

def parse_nginx_config():
    """解析nginx配置文件，提取自定义服务信息"""
    project_root = get_project_root()
    nginx_config_path = os.path.join(project_root, "nginx", "conf.d", "default.conf")
    
    services = []
    
    if not os.path.exists(nginx_config_path):
        return services
    
    with open(nginx_config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 匹配location块，提取服务信息
    # 格式1: # {服务描述} [icon:IconName]（容器内端口 {port}，通过 nginx 统一对外）
    #        location /path { ... proxy_pass http://service-name:port/... }
    # 格式2: {服务描述} [icon:IconName]（容器内端口 {port}，通过 nginx 统一对外）
    #        location /path { ... proxy_pass http://service-name:port/... }
    # 格式3: location /path { ... proxy_pass http://service-name:port/... }（无注释）
    # 使用更灵活的正则表达式匹配多行location块
    # 先尝试匹配有注释的（包含"容器内端口"）
    location_pattern_with_comment = r'(?:#\s*)?([^\n]+?)\s*（容器内端口\s+(\d+)[^）]*）[^\n]*\n\s*location\s+([^\s{]+)\s*\{[^}]*?proxy_pass\s+http://([^:/\s]+):(\d+)([^;]*?);'
    # 再匹配没有注释但端口在7000-7999的
    location_pattern_no_comment = r'\n\s*location\s+([^\s{]+)\s*\{[^}]*?proxy_pass\s+http://([^:/\s]+):(\d+)([^;]*?);'
    
    services_found = {}  # 用于去重，key: service_name:port, value: service_info
    
    # 先匹配有注释的location块
    matches = re.finditer(location_pattern_with_comment, content, re.MULTILINE | re.DOTALL)
    
    for match in matches:
        description_line = match.group(1).strip()
        port_from_comment = int(match.group(2))
        location_path = match.group(3).strip()
        service_name = match.group(4).strip()
        try:
            port = int(match.group(5))
        except ValueError:
            continue
        
        # 检查是否是自定义服务（端口在7000-7999范围内）
        if 7000 <= port <= 7999:
            # 提取端点名称（从location路径中提取）
            endpoint = location_path.rstrip('/').lstrip('/')
            # 移除可能的等号前缀（location = /path）
            endpoint = endpoint.lstrip('= ')
            
            # 解析描述和图标
            description = description_line
            icon = "Box"  # 默认图标
            
            # 提取图标信息 [icon:IconName]
            icon_match = re.search(r'\[icon:([^\]]+)\]', description_line)
            if icon_match:
                icon = icon_match.group(1)
                # 从描述中移除图标标记
                description = re.sub(r'\s*\[icon:[^\]]+\]\s*', '', description)
            
            # 移除端口信息（如果存在）
            description = re.sub(r'（容器内端口\s+\d+[^）]*）', '', description).strip()
            
            # 从容器名提取服务名（去掉 arbore- 前缀）
            actual_service_name = service_name
            if service_name.startswith("arbore-"):
                actual_service_name = service_name[len("arbore-"):]
            
            service_key = f"{actual_service_name}:{port}"
            # 如果服务已存在，保留第一个（通常第一个是主端点）
            if service_key not in services_found:
                services_found[service_key] = {
                    "name": actual_service_name,
                    "port": port,
                    "endpoint": endpoint,
                    "description": description,
                    "icon": icon,
                    "location_path": location_path
                }
    
    # 再匹配没有注释的location块（端口在7000-7999范围内）
    matches = re.finditer(location_pattern_no_comment, content, re.MULTILINE | re.DOTALL)
    
    for match in matches:
        location_path = match.group(1).strip()
        service_name = match.group(2).strip()
        try:
            port = int(match.group(3))
        except ValueError:
            continue
        
        # 检查是否是自定义服务（端口在7000-7999范围内）
        if 7000 <= port <= 7999:
            # 提取端点名称
            endpoint = location_path.rstrip('/').lstrip('/')
            endpoint = endpoint.lstrip('= ')
            
            # 从容器名提取服务名
            actual_service_name = service_name
            if service_name.startswith("arbore-"):
                actual_service_name = service_name[len("arbore-"):]
            
            service_key = f"{actual_service_name}:{port}"
            # 如果服务已存在，跳过（保留有注释的版本）
            if service_key not in services_found:
                services_found[service_key] = {
                    "name": actual_service_name,
                    "port": port,
                    "endpoint": endpoint,
                    "description": f"{actual_service_name}服务",  # 默认描述
                    "icon": "Box",  # 默认图标
                    "location_path": location_path
                }
    
    # 将去重后的服务添加到列表
    services = list(services_found.values())
    
    return services

def get_custom_services_metadata():
    """从配置文件读取自定义服务的元数据（描述、图标等）"""
    project_root = get_project_root()
    metadata_path = os.path.join(project_root, "config", "custom-services.json")
    
    metadata = {}
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        except Exception as e:
            print(f"读取自定义服务元数据失败: {e}")
    
    return metadata

def save_custom_service_metadata(service_name: str, description: str, icon: str = "Box", has_doc: bool = None):
    """保存自定义服务的元数据到配置文件"""
    project_root = get_project_root()
    config_dir = os.path.join(project_root, "config")
    os.makedirs(config_dir, exist_ok=True)
    
    metadata_path = os.path.join(config_dir, "custom-services.json")
    metadata = get_custom_services_metadata()
    
    existing = metadata.get(service_name, {})
    existing["description"] = description
    existing["icon"] = icon
    if has_doc is not None:
        existing["has_doc"] = has_doc
    metadata[service_name] = existing
    
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存自定义服务元数据失败: {e}")

def delete_custom_service_metadata(service_name: str):
    """删除自定义服务的元数据"""
    project_root = get_project_root()
    metadata_path = os.path.join(project_root, "config", "custom-services.json")
    
    if os.path.exists(metadata_path):
        try:
            metadata = get_custom_services_metadata()
            if service_name in metadata:
                del metadata[service_name]
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"删除自定义服务元数据失败: {e}")

def parse_docker_compose_custom_services():
    """以 docker-compose.yml 为权威来源解析自定义服务列表。

    始终从 docker-compose.yml 中提取端口在 7000-7999 范围的服务，
    再用 Docker API / CLI 补充容器内存信息。即使容器未启动或不存在，
    服务仍然会出现在列表中，确保用户可以在界面上管理（查看、删除）。
    """
    services = []
    metadata = get_custom_services_metadata()
    seen_names = set()

    project_root = get_project_root()
    docker_compose_path = os.path.join(project_root, "docker-compose.yml")

    if os.path.exists(docker_compose_path):
        try:
            with open(docker_compose_path, 'r', encoding='utf-8') as f:
                compose_lines = f.readlines()

            service_blocks = {}
            current_service = None
            for line in compose_lines:
                stripped = line.rstrip()
                if stripped and not stripped[0].isspace() and not stripped.startswith('#'):
                    current_service = None
                    continue
                svc_match = re.match(r'^  ([a-z0-9][a-z0-9-]*)\s*:', line)
                if svc_match and not line.startswith('    '):
                    current_service = svc_match.group(1)
                    service_blocks[current_service] = []
                    continue
                if current_service is not None:
                    service_blocks[current_service].append(line)

            for svc_name, block_lines in service_blocks.items():
                service_block = ''.join(block_lines)

                ports_match = re.search(r'ports:\s*\n\s*-\s*"(\d+):(\d+)"', service_block)
                if not ports_match:
                    continue

                host_port = int(ports_match.group(1))
                container_port = int(ports_match.group(2))

                if not (7000 <= host_port <= 7999):
                    continue

                port = host_port
                service_metadata = metadata.get(svc_name, {})
                description = service_metadata.get("description", f"{svc_name}服务")
                icon = service_metadata.get("icon", "Box")

                if not service_metadata:
                    comment_match = re.search(r'#\s*([^\n]+)', service_block)
                    if comment_match:
                        description = comment_match.group(1).strip()
                        icon_match_inner = re.search(r'\[icon:([^\]]+)\]', description)
                        if icon_match_inner:
                            icon = icon_match_inner.group(1)
                            description = re.sub(r'\s*\[icon:[^\]]+\]\s*', '', description)
                        description = re.sub(r'（.*端口.*）', '', description).strip()
                    if not description:
                        description = f"{svc_name}服务"

                memory_limit_mb = None
                memory_reservation_mb = None
                mem_limit_match = re.search(r'mem_limit:\s*([^\n]+)', service_block)
                if mem_limit_match:
                    memory_limit_mb = _parse_memory_to_mb(mem_limit_match.group(1).strip())
                mem_res_match = re.search(r'mem_reservation:\s*([^\n]+)', service_block)
                if mem_res_match:
                    memory_reservation_mb = _parse_memory_to_mb(mem_res_match.group(1).strip())

                services.append({
                    "name": svc_name,
                    "port": port,
                    "container_port": container_port,
                    "endpoint": f"/{svc_name}",
                    "description": description,
                    "icon": icon,
                    "memory_limit_mb": memory_limit_mb if (memory_limit_mb and memory_limit_mb > 0) else None,
                    "memory_reservation_mb": memory_reservation_mb if (memory_reservation_mb and memory_reservation_mb > 0) else None,
                    "has_doc": service_metadata.get("has_doc", False) if service_metadata else False
                })
                seen_names.add(svc_name)
        except Exception as e:
            print(f"从docker-compose.yml解析服务失败: {e}")

    if docker_client:
        try:
            containers = docker_client.containers.list(all=True)
            for c in containers:
                container_name = c.name
                if not container_name.startswith("arbore-"):
                    continue
                service_name = container_name[len("arbore-"):]
                if service_name in seen_names:
                    svc = next((s for s in services if s["name"] == service_name), None)
                    if svc:
                        try:
                            host_config = c.attrs.get("HostConfig", {})
                            mem = host_config.get("Memory") or 0
                            if mem and int(mem) > 0 and not svc.get("memory_limit_mb"):
                                svc["memory_limit_mb"] = int(mem) // (1024 * 1024)
                            mem_res = host_config.get("MemoryReservation") or 0
                            if mem_res and int(mem_res) > 0 and not svc.get("memory_reservation_mb"):
                                svc["memory_reservation_mb"] = int(mem_res) // (1024 * 1024)
                        except Exception:
                            pass
                    continue

                port = None
                container_port_val = None
                try:
                    port_bindings = c.attrs.get("NetworkSettings", {}).get("Ports", {})
                    for cp, host_ports in port_bindings.items():
                        if host_ports:
                            for hp in host_ports:
                                hp_int = int(hp['HostPort'])
                                if 7000 <= hp_int <= 7999:
                                    port = hp_int
                                    container_port_val = int(cp.split('/')[0])
                                    break
                        if port:
                            break
                except Exception:
                    pass

                if not port:
                    continue

                service_metadata = metadata.get(service_name, {})
                memory_limit_mb = 0
                memory_reservation_mb = 0
                try:
                    host_config = c.attrs.get("HostConfig", {})
                    mem = host_config.get("Memory") or 0
                    if mem and int(mem) > 0:
                        memory_limit_mb = int(mem) // (1024 * 1024)
                    mem_res = host_config.get("MemoryReservation") or 0
                    if mem_res and int(mem_res) > 0:
                        memory_reservation_mb = int(mem_res) // (1024 * 1024)
                except Exception:
                    pass

                services.append({
                    "name": service_name,
                    "port": port,
                    "container_port": container_port_val or port,
                    "endpoint": f"/{service_name}",
                    "description": service_metadata.get("description", f"{service_name}服务"),
                    "icon": service_metadata.get("icon", "Box"),
                    "memory_limit_mb": memory_limit_mb or None,
                    "memory_reservation_mb": memory_reservation_mb or None,
                    "has_doc": service_metadata.get("has_doc", False)
                })
                seen_names.add(service_name)
        except Exception as e:
            print(f"从Docker API获取容器列表失败: {e}")

    return services

def get_available_port():
    """获取下一个可用端口（7000-7999）"""
    project_root = get_project_root()
    docker_compose_path = os.path.join(project_root, "docker-compose.yml")
    
    used_ports = set()
    
    # 从docker-compose.yml中提取已使用的端口
    if os.path.exists(docker_compose_path):
        with open(docker_compose_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # 匹配 ports: - "port:port" 格式（直接端口映射）
            port_matches = re.findall(r'ports:\s*\n\s*-\s*"(\d+):', content)
            for port_str in port_matches:
                port = int(port_str)
                if 7000 <= port <= 7999:
                    used_ports.add(port)
            # 也匹配 PORT=数字 环境变量
            port_env_matches = re.findall(r'PORT=(\d+)', content)
            for port_str in port_env_matches:
                port = int(port_str)
                if 7000 <= port <= 7999:
                    used_ports.add(port)
    
    # 查找第一个可用端口
    for port in range(7000, 8000):
        if port not in used_ports:
            return port
    
    raise HTTPException(status_code=400, detail="没有可用的端口（7000-7999范围已满）")

def _memory_mb_to_docker_str(mb: int) -> str:
    """将 MB 转为 Docker 可用的字符串，如 4096 -> '4g'，512 -> '512m'"""
    if mb <= 0:
        return ""
    if mb >= 1024:
        return f"{mb // 1024}g"
    return f"{mb}m"

def _parse_memory_to_mb(s) -> int:
    """解析 compose 中的 mem_limit/mem_reservation 值为 MB。如 '4g'->4096, '512m'->512"""
    if s is None:
        return 0
    s = str(s).strip().lower()
    if not s:
        return 0
    if s.endswith("g"):
        return int(float(s[:-1]) * 1024)
    if s.endswith("m"):
        return int(float(s[:-1]))
    try:
        return int(float(s))
    except ValueError:
        return 0

def add_service_to_docker_compose(service_name: str, port: int, image_name: str, config_dir: str = None, volumes: list = None, container_port: int = None, health_check_path: str = "/health", memory_limit_mb: int = None, memory_reservation_mb: int = None):
    """添加服务到docker-compose.yml
    
    Args:
        service_name: 服务名称
        port: 宿主机端口（对外访问端口）
        image_name: 镜像名称
        config_dir: 配置目录
        volumes: 卷挂载列表
        container_port: 容器内端口（如果为None，则使用port，即port:port映射）
        health_check_path: 健康检查路径，默认/health。无/health的服务（如browserless）可传"/"
        memory_limit_mb: 内存限制（MB），可选，写入 mem_limit，重启后生效
        memory_reservation_mb: 内存预留（MB），可选，写入 mem_reservation
    """
    project_root = get_project_root()
    docker_compose_path = _ensure_docker_compose_file()
    
    # 读取现有配置
    with open(docker_compose_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查服务是否已存在（使用正则匹配完整的服务定义，防止不完整配置）
    # 匹配服务名定义行（包括注释）
    service_pattern = rf'(#\s*[^\n]*{re.escape(service_name)}[^\n]*\n\s+)?{re.escape(service_name)}\s*:'
    if re.search(service_pattern, content, re.MULTILINE):
        raise HTTPException(status_code=400, detail=f"服务 {service_name} 已存在于docker-compose.yml")
    
    # 生成env_file配置（如果有配置目录）
    env_file_config = ""
    if config_dir:
        config_rel_path = os.path.relpath(config_dir, project_root).replace('\\', '/')
        env_file_config = f"    env_file:\n      - ./{config_rel_path}/.env\n"
    
    # 生成volumes配置（如果有挂载配置）
    volumes_config = ""
    if volumes and len(volumes) > 0:
        volumes_config = "    volumes:\n"
        for volume in volumes:
            # volumes格式: ["host_path:container_path"] 或 ["host_path:container_path:ro"]
            volumes_config += f"      - {volume}\n"
    
    # 生成内存限制配置（可选），重启后生效
    memory_config = ""
    if memory_limit_mb and memory_limit_mb > 0:
        memory_config += f"    mem_limit: {_memory_mb_to_docker_str(memory_limit_mb)}\n"
    if memory_reservation_mb and memory_reservation_mb > 0:
        memory_config += f"    mem_reservation: {_memory_mb_to_docker_str(memory_reservation_mb)}\n"
    
    # 确定容器内端口（如果未指定，使用宿主机端口）
    actual_container_port = container_port if container_port is not None else port
    
    # 生成服务配置（直接端口映射，不通过nginx）
    service_config = f"""
  # {service_name}（自定义服务，直接端口访问 {port}）
  {service_name}:
    image: {image_name}
    container_name: arbore-{service_name}
    restart: unless-stopped
{memory_config}{env_file_config}{volumes_config}    environment:
      - PORT={actual_container_port}
    ports:
      - "{port}:{actual_container_port}"  # 宿主机{port}映射到容器{actual_container_port}端口
    networks:
      - arbore-network
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:{actual_container_port}{health_check_path} || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
"""
    
    # 在networks定义之前插入服务配置
    # 匹配文件级别的networks:定义（前面可能有空行，后面跟着arbore-network等）
    # 使用更精确的模式：匹配独立的networks:行（不在services内部，行首可能有空格）
    # 确保匹配的是文件级别的networks:，而不是服务内部的networks:
    networks_pattern = r'(\n^networks:\s*$)'
    networks_match = re.search(networks_pattern, content, re.MULTILINE)
    
    if networks_match:
        # 检查networks:之前是否有其他服务配置
        before_networks = content[:networks_match.start()]
        # 确保插入位置正确（在最后一个服务配置之后，networks之前）
        # 在networks:之前插入服务配置
        content = content[:networks_match.start()] + service_config + content[networks_match.start():]
    else:
        # 如果找不到networks，检查是否有services:定义
        services_pattern = r'(\n^services:\s*$)'
        services_match = re.search(services_pattern, content, re.MULTILINE)
        if services_match:
            # 在services:之后插入
            content = content[:services_match.end()] + service_config + content[services_match.end():]
        else:
            # 添加到文件末尾
            content = content.rstrip() + "\n" + service_config
    
    # 验证插入后没有重复（安全检查）
    service_count = len(re.findall(rf'^{re.escape(service_name)}\s*:', content, re.MULTILINE))
    if service_count > 1:
        raise HTTPException(status_code=500, detail=f"配置插入后检测到重复的服务定义（{service_count}个），请检查docker-compose.yml")
    
    # 写回文件
    with open(docker_compose_path, 'w', encoding='utf-8') as f:
        f.write(content)

def add_service_to_nginx(service_name: str, port: int, endpoint: str, description: str, icon: str = "Box"):
    """添加服务到nginx配置"""
    project_root = get_project_root()
    nginx_config_path = os.path.join(project_root, "nginx", "conf.d", "default.conf")
    
    if not os.path.exists(nginx_config_path):
        raise HTTPException(status_code=404, detail="nginx配置文件不存在")
    
    # 读取现有配置
    with open(nginx_config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 规范化端点路径
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    if not endpoint.endswith('/'):
        endpoint = endpoint + '/'
    
    # 检查端点是否已存在（使用正则匹配完整的location块，防止不完整配置）
    endpoint_escaped = re.escape(endpoint)
    # 匹配完整的location块（包括注释和配置）
    existing_pattern = rf'(#\s*[^\n]*{re.escape(service_name)}[^\n]*\n\s+)?location\s+{endpoint_escaped}\s*\{{'
    if re.search(existing_pattern, content, re.MULTILINE):
        raise HTTPException(status_code=400, detail=f"端点 {endpoint} 已存在于nginx配置中")
    
    # 生成nginx配置（在描述中包含图标信息）
    # 注意：容器名称是 arbore-{service_name}，不是 {service_name}
    container_name = f"arbore-{service_name}"
    nginx_config = f"""
    # {description} [icon:{icon}]（容器内端口 {port}，通过 nginx 统一对外）
    location {endpoint} {{
        proxy_pass http://{container_name}:{port}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
"""
    
    # 在默认路由之前插入配置
    # 匹配 "# 默认路由" 注释（后面可能有其他文字）和 location / { 块
    # 使用DOTALL模式匹配，确保能匹配跨行的location块
    default_location_pattern = r'(\n\s+# 默认路由[^\n]*\n\s+location\s+/\s+\{.*?\})'
    if re.search(default_location_pattern, content, re.DOTALL):
        # 在匹配到的内容之前插入新配置（nginx_config已经包含开头的换行）
        # 使用count=1确保只替换一次
        content = re.sub(default_location_pattern, nginx_config + r'\1', content, count=1, flags=re.DOTALL)
    else:
        # 如果找不到默认路由注释，尝试匹配 location / { 块（在server块内）
        # 使用DOTALL模式匹配多行内容
        location_root_pattern = r'(\n\s+location\s+/\s+\{.*?return\s+\d+.*?\})'
        if re.search(location_root_pattern, content, re.DOTALL):
            # 使用count=1确保只替换一次
            content = re.sub(location_root_pattern, nginx_config + r'\1', content, count=1, flags=re.DOTALL)
        else:
            # 最后尝试：在server块的最后一个}之前插入（在server块内）
            # 匹配server块结束前的最后一个}，确保在server块内
            server_end_pattern = r'(\n\s+\}\s*$)'
            if re.search(server_end_pattern, content, re.MULTILINE):
                # 使用count=1确保只替换一次（从后往前匹配最后一个}）
                matches = list(re.finditer(server_end_pattern, content, re.MULTILINE))
                if matches:
                    # 替换最后一个匹配（server块的结束）
                    last_match = matches[-1]
                    content = content[:last_match.start()] + nginx_config + content[last_match.start():]
            else:
                raise HTTPException(status_code=500, detail="无法找到nginx配置的插入位置")
    
    # 验证插入后没有重复（安全检查）
    location_count = len(re.findall(rf'location\s+{re.escape(endpoint)}\s*\{{', content))
    if location_count > 1:
        raise HTTPException(status_code=500, detail=f"配置插入后检测到重复的location块（{location_count}个），请检查nginx配置")
    
    # 写回文件
    with open(nginx_config_path, 'w', encoding='utf-8') as f:
        f.write(content)

def remove_service_from_docker_compose(service_name: str):
    """从docker-compose.yml中删除服务，使用逐行解析确保准确性"""
    project_root = get_project_root()
    docker_compose_path = os.path.join(project_root, "docker-compose.yml")
    
    if not os.path.exists(docker_compose_path):
        raise HTTPException(status_code=404, detail="docker-compose.yml文件不存在")
    
    with open(docker_compose_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    new_lines = []
    in_service_block = False
    service_indent = -1
    service_found = False
    
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped_line = line.lstrip()
        current_indent = len(line) - len(stripped_line)
        
        # 检查是否是目标服务定义行（例如: service-name:）
        if stripped_line.startswith(f"{service_name}:"):
            # 找到目标服务，标记开始删除
            service_found = True
            in_service_block = True
            service_indent = current_indent
            print(f"找到服务 '{service_name}' 的起始行: {i+1}, 缩进: {service_indent}")
            
            # 检查前一行是否是注释，如果是，也要删除
            if len(new_lines) > 0 and new_lines[-1].strip().startswith('#'):
                # 删除注释行
                new_lines.pop()
                # 如果注释前还有空行，也删除
                if len(new_lines) > 0 and new_lines[-1].strip() == '':
                    new_lines.pop()
            
            # 跳过服务定义行
            i += 1
            continue
        
        # 如果在服务块内
        if in_service_block:
            # 如果当前行缩进小于或等于服务块的缩进，且不是空行，说明服务块结束
            if current_indent <= service_indent and stripped_line and not stripped_line.startswith('#'):
                # 服务块结束
                in_service_block = False
                service_indent = -1
                # 如果当前行是另一个服务定义或顶级键，则添加
                if stripped_line.rstrip().endswith(':') or stripped_line.startswith('networks:') or stripped_line.startswith('volumes:'):
                    new_lines.append(line)
                i += 1
                continue
            else:
                # 仍在服务块内，跳过此行
                i += 1
                continue
        
        # 不在服务块内，添加此行
        new_lines.append(line)
        i += 1
    
    # 检查是否找到服务
    if not service_found:
        raise HTTPException(status_code=404, detail=f"在docker-compose.yml中未找到服务 '{service_name}' 的配置")
    
    # 写回文件
    with open(docker_compose_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"已从docker-compose.yml删除服务 '{service_name}' 的配置")

def remove_service_from_nginx(service_name: str, endpoint: str):
    """从nginx配置中删除服务"""
    project_root = get_project_root()
    nginx_config_path = os.path.join(project_root, "nginx", "conf.d", "default.conf")
    
    if not os.path.exists(nginx_config_path):
        raise HTTPException(status_code=404, detail="nginx配置文件不存在")
    
    with open(nginx_config_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # 容器名是 arbore-{service_name}
    container_name = f"arbore-{service_name}"
    
    # 规范化endpoint路径（匹配时需要考虑各种格式）
    endpoint_normalized = endpoint.rstrip('/')
    if not endpoint_normalized.startswith('/'):
        endpoint_normalized = '/' + endpoint_normalized
    
    # 方法1: 通过容器名匹配（proxy_pass中的容器名）
    # 匹配完整的location块，包括注释和配置
    # 格式: # 注释\n    location /path { ... proxy_pass http://arbore-service-name:port/ ... }
    pattern1 = rf'(\n\s+#[^\n]*\n\s+location\s+[^{{]*\{{[^}}]*proxy_pass\s+http://{re.escape(container_name)}:[^/\s]+[^}}]*\}})'
    content = re.sub(pattern1, '', content, flags=re.MULTILINE | re.DOTALL)
    
    # 方法2: 通过endpoint路径匹配（如果方法1没匹配到）
    if content == original_content:
        # 匹配location块，包括注释
        endpoint_escaped = re.escape(endpoint_normalized)
        pattern2 = rf'(\n\s+#[^\n]*\n\s+location\s+{endpoint_escaped}[^{{]*\{{[^}}]*\}})'
        content = re.sub(pattern2, '', content, flags=re.MULTILINE | re.DOTALL)
    
    # 方法3: 也删除可能的根路径重定向（location = /path）
    redirect_pattern = rf'(\n\s+location\s+=\s+{re.escape(endpoint_normalized)}\s+\{{[^}}]*\}})'
    content = re.sub(redirect_pattern, '', content, flags=re.MULTILINE | re.DOTALL)
    
    # 验证是否真的删除了内容
    if content == original_content:
        print(f"警告: 未能从nginx配置中删除服务 {service_name} (容器名: {container_name}, endpoint: {endpoint_normalized})")
        print(f"尝试匹配的容器名: {container_name}")
        print(f"尝试匹配的endpoint: {endpoint_normalized}")
        # 打印配置文件内容以便调试
        print("当前nginx配置片段:")
        lines = original_content.split('\n')
        for i, line in enumerate(lines):
            if container_name in line or endpoint_normalized in line or service_name in line:
                print(f"Line {i+1}: {line}")
    else:
        print(f"成功从nginx配置中删除服务 {service_name}")
    
    with open(nginx_config_path, 'w', encoding='utf-8') as f:
        f.write(content)

@app.get("/api/v1/custom-services")
async def get_custom_services():
    """获取所有自定义服务（包含容器状态）"""
    try:
        services = parse_docker_compose_custom_services()
        
        # 查询每个服务的容器状态
        container_dict = {}
        container_status_dict = {}  # 存储容器状态信息
        
        if docker_client:
            try:
                containers = docker_client.containers.list(all=True)
                for c in containers:
                    # 容器名格式: arbore-{service_name}
                    if c.name.startswith("arbore-"):
                        service_name = c.name[len("arbore-"):]
                        container_dict[service_name] = c
                        # 提取状态信息
                        try:
                            health_info = c.attrs.get("State", {}).get("Health", {})
                            health = health_info.get("Status", "unknown")
                            
                            # 如果健康状态是starting，检查是否超过start_period
                            if health == "starting":
                                started_at = health_info.get("Start", "")
                                if started_at:
                                    try:
                                        from datetime import datetime
                                        start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                                        elapsed = (datetime.now(start_time.tzinfo) - start_time).total_seconds()
                                        # 如果超过60秒还在starting，可能是健康检查有问题，改为unknown
                                        if elapsed > 60:
                                            health = "unknown"
                                    except:
                                        pass
                        except:
                            health = "unknown"
                        
                        container_status_dict[service_name] = {
                            'status': c.status,
                            'container_id': c.id[:12],
                            'health': health,
                            'attrs': c.attrs
                        }
            except Exception as e:
                print(f"查询容器状态失败: {e}")
        else:
            # Fallback: 使用docker命令查询
            try:
                result = subprocess.run(
                    ['docker', 'ps', '-a', '--format', '{{.Names}}\t{{.Status}}\t{{.ID}}'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if not line.strip():
                            continue
                        parts = line.split('\t')
                        if len(parts) >= 3:
                            container_name = parts[0]
                            status_str = parts[1]
                            container_id = parts[2][:12]
                            
                            if container_name.startswith("arbore-"):
                                service_name = container_name[len("arbore-"):]
                                # 解析状态
                                if 'Up' in status_str:
                                    status = 'running'
                                elif 'Exited' in status_str:
                                    status = 'exited'
                                else:
                                    status = status_str.lower()
                                
                                container_status_dict[service_name] = {
                                    'status': status,
                                    'container_id': container_id,
                                    'health': 'unknown',  # docker ps无法获取健康状态
                                    'attrs': None
                                }
            except Exception as e:
                print(f"使用docker命令查询容器状态失败: {e}")
        
        # 为每个服务添加容器状态信息
        for service in services:
            service_name = service['name']
            container_name = f"arbore-{service_name}"
            container_info = container_status_dict.get(service_name)
            
            if container_info:
                # 容器存在，获取状态
                service['status'] = container_info['status']
                service['container_id'] = container_info['container_id']
                service['health'] = container_info['health']
                
                # 获取端口映射（如果有attrs）
                if container_info.get('attrs'):
                    try:
                        port_bindings = container_info['attrs'].get("NetworkSettings", {}).get("Ports", {})
                        ports = []
                        for container_port, host_ports in port_bindings.items():
                            if host_ports:
                                for hp in host_ports:
                                    ports.append(f"{hp['HostPort']}:{container_port.split('/')[0]}")
                        service['ports_display'] = ports
                    except:
                        service['ports_display'] = []
                else:
                    service['ports_display'] = []
            else:
                # 容器不存在
                service['status'] = "not_found"
                service['health'] = "unknown"
                service['container_id'] = None
                service['ports_display'] = []
        
        return {"services": services}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取自定义服务列表失败: {str(e)}")

@app.post("/api/v1/custom-services/validate")
async def validate_custom_service(
    name: str = Form(...),
    port: int = Form(...),
    endpoint: str = Form(None)  # 已废弃，保留以保持向后兼容
):
    """验证自定义服务参数（在上传文件之前调用）。需许可证有效方可添加服务。"""
    try:
        _license_valid_or_403()
    except HTTPException:
        raise

    try:
        # 验证端口范围（7000-7999）
        if not (7000 <= port <= 7999):
            raise HTTPException(status_code=400, detail="自定义服务端口必须在7000-7999范围内")
        
        # 验证服务名称格式
        if not re.match(r'^[a-z0-9-]+$', name):
            raise HTTPException(status_code=400, detail="服务名称只能包含小写字母、数字和连字符")
        
        # 验证唯一性（只检查端口，不再需要端点）
        existing_services = parse_docker_compose_custom_services()
        
        # 检查服务名称是否已存在
        for service in existing_services:
            if service['name'] == name:
                raise HTTPException(status_code=400, detail=f"服务名称 '{name}' 已存在")
        
        # 检查端口是否已被使用
        for service in existing_services:
            if service['port'] == port:
                raise HTTPException(status_code=400, detail=f"端口 {port} 已被服务 '{service['name']}' 使用")
        
        return {
            "valid": True,
            "message": "验证通过"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"验证失败: {str(e)}")

@app.post("/api/v1/custom-services/upload")
async def upload_custom_service(
    file: UploadFile = File(...),
    name: str = Form(...),
    port: int = Form(...),
    container_port: int = Form(None),  # 容器内端口（可选，如果不指定则使用port）
    endpoint: str = Form(None),  # 已废弃，保留以保持向后兼容，现在通过端口直接访问
    description: str = Form(...),
    icon: str = Form("Box"),
    env_vars: str = Form(None, description="环境变量JSON配置，格式: {\"KEY1\":\"value1\",\"KEY2\":\"value2\"}"),
    volumes: str = Form(None, description="卷挂载JSON配置，格式: [\"host_path:container_path\", \"host_path2:container_path2:ro\"]"),
    memory_limit_mb: int = Form(None),
    memory_reservation_mb: int = Form(None),
    doc_file: UploadFile = File(None)
):
    """上传Docker镜像tar文件并部署服务。需许可证有效方可添加服务。"""
    try:
        _license_valid_or_403()
    except HTTPException:
        raise

    try:
        # ========== 第一步：快速验证（在文件上传之前，避免浪费时间和资源）==========
        # 验证端口范围（7000-7999）
        if not (7000 <= port <= 7999):
            raise HTTPException(status_code=400, detail="自定义服务端口必须在7000-7999范围内")
        
        # 验证服务名称格式
        if not re.match(r'^[a-z0-9-]+$', name):
            raise HTTPException(status_code=400, detail="服务名称只能包含小写字母、数字和连字符")
        
        # 快速验证唯一性：服务名称、端口必须唯一（在文件操作之前）
        # 注意：这里先进行验证，如果失败可以立即返回，避免上传大文件
        existing_services = parse_docker_compose_custom_services()
        
        # 检查服务名称是否已存在
        for service in existing_services:
            if service['name'] == name:
                raise HTTPException(status_code=400, detail=f"服务名称 '{name}' 已存在")
        
        # 检查端口是否已被使用
        for service in existing_services:
            if service['port'] == port:
                raise HTTPException(status_code=400, detail=f"端口 {port} 已被服务 '{service['name']}' 使用")
        
        # ========== 第二步：验证通过后，才开始文件操作（此时文件才开始真正上传）==========
        
        # ========== 第二步：验证通过后，才开始文件操作 ==========
        project_root = get_project_root()
        temp_dir = os.path.join(project_root, "temp", "custom-services")
        os.makedirs(temp_dir, exist_ok=True)
        
        # 保存上传的文件
        tar_path = os.path.join(temp_dir, f"{name}.tar")
        with open(tar_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        
        # 加载Docker镜像
        try:
            if not os.path.exists(tar_path):
                raise HTTPException(status_code=400, detail=f"上传的文件不存在: {tar_path}")

            image_name = f"{name}:latest"

            # 优先使用 Python docker 客户端加载（避免 Docker daemon 路径访问问题）
            if docker_client:
                print(f"Using Python docker client to load image from: {tar_path}")
                try:
                    with open(tar_path, 'rb') as f:
                        loaded_images = docker_client.images.load(f.read())
                    if loaded_images and loaded_images[0].tags:
                        image_name = loaded_images[0].tags[0]
                    print(f"Successfully loaded image via Python client: {image_name}")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to load Docker image: {str(e)}")
            else:
                # Fallback: 使用 docker CLI subprocess（需要 docker 命令在 PATH 中）
                abs_tar_path = os.path.abspath(tar_path)
                print(f"Using subprocess docker load: {abs_tar_path}")
                result = subprocess.run(
                    ['docker', 'load', '-i', abs_tar_path],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=project_root,
                )
                print(f"Docker load returncode: {result.returncode}, stdout: {result.stdout}, stderr: {result.stderr}")
                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout or "Unknown error"
                    raise HTTPException(status_code=500, detail=f"Failed to load Docker image: {error_msg}")
                image_match = re.search(r'Loaded image: (.+)', result.stdout)
                if image_match:
                    image_name = image_match.group(1).strip()
                print(f"Successfully loaded image via subprocess: {image_name}")

        except HTTPException:
            raise
        except Exception as e:
            import traceback
            print(f"Docker load exception: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"加载Docker镜像失败: {str(e)}")
        finally:
            # 清理临时文件
            if os.path.exists(tar_path):
                try:
                    os.remove(tar_path)
                except Exception as e:
                    print(f"Warning: Failed to remove temp file: {e}")
        
        # 处理环境变量配置
        env_config = {}
        print(f"收到环境变量参数: env_vars={env_vars}, type={type(env_vars)}")
        if env_vars and env_vars.strip():  # 检查非空且非空白字符串
            try:
                env_config = json.loads(env_vars)
                print(f"解析后的环境变量: {env_config}")
            except json.JSONDecodeError as e:
                print(f"环境变量JSON解析失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"环境变量配置格式错误: {str(e)}")
        else:
            print("环境变量参数为空或空白，跳过处理")
        
        # 创建配置目录和.env文件（如果有环境变量）
        config_dir = None
        if env_config:
            project_root = get_project_root()
            config_dir = os.path.join(project_root, "config", name)
            os.makedirs(config_dir, exist_ok=True)
            print(f"创建配置目录: {config_dir}")
            
            env_file_path = os.path.join(config_dir, ".env")
            with open(env_file_path, 'w', encoding='utf-8') as f:
                for key, value in env_config.items():
                    f.write(f"{key}={value}\n")
            # 设置文件权限为600（仅所有者可读写）
            os.chmod(env_file_path, 0o600)
            print(f"已创建环境变量文件: {env_file_path}")
        else:
            print(f"未配置环境变量，跳过.env文件创建")
        
        # 处理卷挂载配置
        volumes_list = []
        print(f"收到卷挂载参数: volumes={volumes}, type={type(volumes)}")
        if volumes and volumes.strip():  # 检查非空且非空白字符串
            try:
                volumes_list = json.loads(volumes)
                if not isinstance(volumes_list, list):
                    raise HTTPException(status_code=400, detail="卷挂载配置必须是数组格式")
                # 验证每个挂载项的格式
                for volume in volumes_list:
                    if not isinstance(volume, str):
                        raise HTTPException(status_code=400, detail=f"卷挂载项必须是字符串格式: {volume}")
                    # 基本格式验证：应该包含冒号分隔符
                    if ':' not in volume:
                        raise HTTPException(status_code=400, detail=f"卷挂载格式错误，应使用 'host_path:container_path' 格式: {volume}")
                print(f"解析后的卷挂载: {volumes_list}")
            except json.JSONDecodeError as e:
                print(f"卷挂载JSON解析失败: {str(e)}")
                raise HTTPException(status_code=400, detail=f"卷挂载配置格式错误: {str(e)}")
        else:
            print("卷挂载参数为空或空白，跳过处理")
        
        # 添加到docker-compose.yml（browserless 无 /health 路由，健康检查用 /）
        health_check_path = "/" if name == "browserless" else "/health"
        try:
            add_service_to_docker_compose(name, port, image_name, config_dir, volumes_list, container_port, health_check_path, memory_limit_mb=memory_limit_mb, memory_reservation_mb=memory_reservation_mb)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"添加到docker-compose.yml失败: {str(e)}")
        
        # 保存说明文档PDF（如果上传了）
        has_doc = False
        if doc_file and doc_file.filename:
            try:
                if not doc_file.filename.lower().endswith('.pdf'):
                    print(f"警告: 说明文档不是PDF格式: {doc_file.filename}")
                else:
                    project_root_doc = get_project_root()
                    doc_dir = os.path.join(project_root_doc, "config", name)
                    os.makedirs(doc_dir, exist_ok=True)
                    doc_path = os.path.join(doc_dir, "doc.pdf")
                    with open(doc_path, "wb") as df:
                        shutil.copyfileobj(doc_file.file, df)
                    has_doc = True
                    print(f"已保存说明文档: {doc_path}")
            except Exception as e:
                print(f"警告: 保存说明文档失败: {e}")

        # 保存服务元数据（描述、图标）
        try:
            save_custom_service_metadata(name, description, icon, has_doc=has_doc)
            print(f"已保存服务元数据: {name}")
        except Exception as e:
            print(f"警告: 保存服务元数据失败: {e}")
        
        # 启动新服务
        startup_warning = None
        try:
            result = subprocess.run(
                _docker_compose_cmd() + ["up", "-d", name],
                cwd=project_root,
                timeout=120,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                startup_warning = f"服务配置已写入 docker-compose.yml，但自动启动失败: {result.stderr or result.stdout}"
                print(f"Service startup failed: returncode={result.returncode}, stderr={result.stderr}")
            else:
                print(f"Service {name} started successfully")
        except Exception as e:
            startup_warning = f"服务配置已写入 docker-compose.yml，但自动启动异常: {str(e)}"
            print(f"Service startup exception: {str(e)}")

        response = {
            "success": True,
            "message": f"服务 {name} 部署成功，访问地址: http://服务器IP:{port}",
            "service": {
                "name": name,
                "port": port,
                "endpoint": endpoint or f"/{name}",
                "description": description,
                "image_name": image_name
            }
        }
        if startup_warning:
            response["warning"] = startup_warning
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"部署服务异常: {str(e)}")
        print(f"完整错误堆栈: {error_trace}")
        error_detail = f"部署服务失败: {str(e)}"
        raise HTTPException(status_code=500, detail=error_detail)

@app.delete("/api/v1/custom-services/{service_name}")
async def delete_custom_service(service_name: str):
    """删除自定义服务"""
    try:
        # 获取服务信息（从docker-compose.yml）
        services = parse_docker_compose_custom_services()
        service_info = None
        for s in services:
            if s['name'] == service_name:
                service_info = s
                break
        
        if not service_info:
            raise HTTPException(status_code=404, detail=f"服务 {service_name} 不存在")
        
        # 停止并删除容器
        try:
            print(f"正在停止并删除容器: arbore-{service_name}")
            if docker_client:
                container_name = f"arbore-{service_name}"
                try:
                    container = docker_client.containers.get(container_name)
                    container.stop(timeout=30)
                    container.remove()
                    print(f"容器 {container_name} 已删除")
                except docker.errors.NotFound:
                    print(f"容器 {container_name} 不存在，跳过")
            else:
                # 使用docker-compose命令
                result1 = subprocess.run(
                    _docker_compose_cmd() + ["stop", service_name],
                    cwd=get_project_root(),
                    timeout=60,
                    capture_output=True,
                    text=True
                )
                if result1.returncode != 0:
                    print(f"停止容器警告: {result1.stderr}")
                
                result2 = subprocess.run(
                    _docker_compose_cmd() + ["rm", "-f", service_name],
                    cwd=get_project_root(),
                    timeout=60,
                    capture_output=True,
                    text=True
                )
                if result2.returncode != 0:
                    print(f"删除容器警告: {result2.stderr}")
                else:
                    print(f"容器 {service_name} 已删除")
        except Exception as e:
            print(f"警告: 删除容器失败: {str(e)}")
            import traceback
            print(traceback.format_exc())
        
        # 从docker-compose.yml中删除
        try:
            print(f"正在从docker-compose.yml删除服务配置: {service_name}")
            remove_service_from_docker_compose(service_name)
            print(f"已从docker-compose.yml删除服务配置")
        except HTTPException:
            # HTTPException需要向上抛出
            raise
        except Exception as e:
            # 其他异常也要抛出，不能静默吞掉
            print(f"错误: 从docker-compose.yml删除失败: {str(e)}")
            import traceback
            print(traceback.format_exc())
            raise HTTPException(status_code=500, detail=f"从docker-compose.yml删除失败: {str(e)}")
        
        # 清理配置目录（如果存在）
        try:
            project_root = get_project_root()
            config_dir = os.path.join(project_root, "config", service_name)
            if os.path.exists(config_dir):
                shutil.rmtree(config_dir)
                print(f"已清理配置目录: {config_dir}")
        except Exception as e:
            print(f"警告: 清理配置目录失败: {str(e)}")
        
        # 删除服务元数据
        try:
            delete_custom_service_metadata(service_name)
            print(f"已删除服务元数据: {service_name}")
        except Exception as e:
            print(f"警告: 删除服务元数据失败: {e}")
        
        return {
            "success": True,
            "message": f"服务 {service_name} 已删除"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除服务失败: {str(e)}")

@app.put("/api/v1/custom-services/{service_name}")
async def update_custom_service(service_name: str, update: CustomServiceUpdate):
    """更新自定义服务配置"""
    try:
        # 获取现有服务信息（从docker-compose.yml）
        services = parse_docker_compose_custom_services()
        service_info = None
        for s in services:
            if s['name'] == service_name:
                service_info = s
                break
        
        if not service_info:
            raise HTTPException(status_code=404, detail=f"服务 {service_name} 不存在")
        
        # 更新服务元数据（如果更新了描述或图标）
        if update.description is not None or update.icon is not None:
            try:
                new_description = update.description or service_info.get('description', f"{service_name}服务")
                new_icon = update.icon or service_info.get('icon', 'Box')
                save_custom_service_metadata(service_name, new_description, new_icon)
                print(f"已更新服务元数据: {service_name}")
            except Exception as e:
                print(f"警告: 更新服务元数据失败: {e}")
        
        # 处理环境变量更新
        if update.env_vars is not None:
            project_root = get_project_root()
            config_dir = os.path.join(project_root, "config", service_name)
            os.makedirs(config_dir, exist_ok=True)
            
            try:
                env_config = json.loads(update.env_vars) if update.env_vars else {}
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"环境变量配置格式错误: {str(e)}")
            
            env_file_path = os.path.join(config_dir, ".env")
            with open(env_file_path, 'w', encoding='utf-8') as f:
                for key, value in env_config.items():
                    f.write(f"{key}={value}\n")
            os.chmod(env_file_path, 0o600)
            print(f"已更新环境变量配置: {env_file_path}")
        
        # 处理卷挂载更新
        volumes_list = None
        if update.volumes is not None:
            try:
                if update.volumes.strip():
                    volumes_list = json.loads(update.volumes)
                    if not isinstance(volumes_list, list):
                        raise HTTPException(status_code=400, detail="卷挂载配置必须是数组格式")
                    # 验证每个挂载项的格式
                    for volume in volumes_list:
                        if not isinstance(volume, str):
                            raise HTTPException(status_code=400, detail=f"卷挂载项必须是字符串格式: {volume}")
                        if ':' not in volume:
                            raise HTTPException(status_code=400, detail=f"卷挂载格式错误，应使用 'host_path:container_path' 格式: {volume}")
                else:
                    volumes_list = []
                print(f"已更新卷挂载配置: {volumes_list}")
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=400, detail=f"卷挂载配置格式错误: {str(e)}")
        
        # 如果更新了端口、卷挂载、内存或环境变量，需要更新docker-compose配置
        if update.port or volumes_list is not None or update.env_vars is not None or update.memory_limit_mb is not None or update.memory_reservation_mb is not None:
            project_root = get_project_root()
            docker_compose_path = os.path.join(project_root, "docker-compose.yml")
            # 在删除前先读取当前 compose 中的 image_name 和 volumes（仅当未在本次提交中提供时需要保留）
            content_before_remove = ""
            if os.path.exists(docker_compose_path):
                with open(docker_compose_path, 'r', encoding='utf-8') as f:
                    content_before_remove = f.read()
            
            image_name = f"{service_name}:latest"
            image_match = re.search(rf'{service_name}:\s*\n\s+image:\s*([^\n]+)', content_before_remove)
            if image_match:
                image_name = image_match.group(1).strip()
            
            # 若本次未提交卷挂载，则从当前 compose 中读取
            if volumes_list is None and content_before_remove:
                service_pattern = rf'{re.escape(service_name)}\s*:.*?(?=\n  [a-z]|\n\n|\Z)'
                service_match = re.search(service_pattern, content_before_remove, re.DOTALL)
                if service_match:
                    service_config = service_match.group(0)
                    volumes_pattern = r'volumes:\s*\n((?:\s+- .+\n?)+)'
                    volumes_match = re.search(volumes_pattern, service_config)
                    if volumes_match:
                        volumes_block = volumes_match.group(1)
                        volume_items = re.findall(r'-\s*(.+)', volumes_block)
                        volumes_list = [item.strip() for item in volume_items]
                    else:
                        volumes_list = []
                else:
                    volumes_list = []
            elif volumes_list is None:
                volumes_list = []
            
            # 删除旧配置
            remove_service_from_docker_compose(service_name)
            
            # 使用新配置添加
            new_port = update.port or service_info['port']
            new_description = update.description or service_info['description']
            
            # 验证端口范围
            if not (7000 <= new_port <= 7999):
                raise HTTPException(status_code=400, detail="端口必须在7000-7999范围内")
            
            # 验证唯一性（排除当前服务）
            existing_services = parse_docker_compose_custom_services()
            for service in existing_services:
                if service['name'] == service_name:
                    continue  # 排除当前服务
                
                # 检查端口是否冲突
                if service['port'] == new_port:
                    raise HTTPException(status_code=400, detail=f"端口 {new_port} 已被服务 '{service['name']}' 使用")
            
            new_icon = update.icon or service_info.get('icon', 'Box')
            
            # 获取配置目录（用于env_file）
            config_dir = os.path.join(project_root, "config", service_name)
            # 如果更新了环境变量，确保config_dir存在
            if update.env_vars is not None:
                os.makedirs(config_dir, exist_ok=True)
            config_dir = config_dir if os.path.exists(os.path.join(config_dir, ".env")) else None
            
            # 获取容器端口（如果更新了container_port，使用新值；否则默认使用宿主机端口）
            new_container_port = update.container_port
            if new_container_port is None:
                # 如果未指定容器端口，默认使用宿主机端口（保持端口一致）
                new_container_port = new_port
            # 内存限制：优先用本次提交值，否则保留原配置（service_info 中可能无此键则传 None）
            new_memory_limit_mb = update.memory_limit_mb if update.memory_limit_mb is not None else service_info.get("memory_limit_mb")
            new_memory_reservation_mb = update.memory_reservation_mb if update.memory_reservation_mb is not None else service_info.get("memory_reservation_mb")
            health_check_path = "/" if service_name == "browserless" else "/health"
            add_service_to_docker_compose(service_name, new_port, image_name, config_dir, volumes_list, new_container_port, health_check_path, memory_limit_mb=new_memory_limit_mb, memory_reservation_mb=new_memory_reservation_mb)
        
        # 如果只更新了环境变量（没有更新端口/卷挂载/内存），需要重启容器以加载新的环境变量
        # 注意：如果更新了端口/卷挂载/内存，上面的代码已经会重新生成 docker-compose 并重建容器
        if update.env_vars is not None and not (update.port or update.endpoint or (volumes_list is not None) or update.memory_limit_mb is not None or update.memory_reservation_mb is not None):
            try:
                container_name = f"arbore-{service_name}"
                print(f"环境变量已更新，重启容器以加载新配置: {container_name}")
                if docker_client:
                    try:
                        container = docker_client.containers.get(container_name)
                        container.restart(timeout=30)
                        print(f"容器 {container_name} 已重启")
                    except Exception as e:
                        print(f"使用Docker客户端重启失败，尝试使用docker compose: {str(e)}")
                        subprocess.run(
                            _docker_compose_cmd() + ["restart", service_name],
                            cwd=get_project_root(),
                            timeout=60
                        )
                else:
                    subprocess.run(
                        _docker_compose_cmd() + ["restart", service_name],
                        cwd=get_project_root(),
                        timeout=60
                    )
                print(f"容器 {container_name} 已重启，新环境变量已生效")
            except Exception as e:
                print(f"警告: 重启容器失败: {str(e)}")
                # 不抛出异常，因为环境变量文件已更新，用户可以手动重启
        
        return {
            "success": True,
            "message": f"服务 {service_name} 已更新"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新服务失败: {str(e)}")

@app.post("/api/v1/custom-services/{service_name}/restart")
async def restart_custom_service(service_name: str):
    """重启自定义服务容器（重新创建以加载最新的env_file配置）"""
    try:
        container_name = f"arbore-{service_name}"
        project_root = get_project_root()
        
        print(f"正在重启服务: {service_name} (重新创建容器以加载最新配置)")
        
        # 使用 docker compose up -d 重新创建容器（会加载最新的env_file）
        # 这比 restart 更好，因为 restart 不会重新加载 env_file
        result = subprocess.run(
            _docker_compose_cmd() + ["up", "-d", "--force-recreate", service_name],
            cwd=project_root,
            timeout=120,
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"服务 {service_name} 已重新创建并启动")
            return {
                "success": True,
                "message": f"服务 {service_name} 已重启（已重新创建容器，新环境变量已生效）"
            }
        else:
            error_msg = result.stderr or result.stdout or "未知错误"
            print(f"重启服务失败: {error_msg}")
            raise HTTPException(status_code=500, detail=f"重启服务失败: {error_msg}")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重启服务失败: {str(e)}")

@app.get("/api/v1/custom-services/{service_name}/env")
async def get_service_env_vars(service_name: str):
    """获取服务的环境变量配置"""
    try:
        project_root = get_project_root()
        config_dir = os.path.join(project_root, "config", service_name)
        env_file_path = os.path.join(config_dir, ".env")
        
        env_vars = {}
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
        
        # 即使文件不存在也返回空对象，而不是404
        return {"env_vars": env_vars}
    except Exception as e:
        # 返回空对象而不是错误，因为.env文件可能不存在
        print(f"读取环境变量失败（可能文件不存在）: {str(e)}")
        return {"env_vars": {}}

@app.get("/api/v1/custom-services/{service_name}/volumes")
async def get_service_volumes(service_name: str):
    """获取服务的卷挂载配置"""
    try:
        project_root = get_project_root()
        docker_compose_path = os.path.join(project_root, "docker-compose.yml")
        
        volumes_list = []
        if os.path.exists(docker_compose_path):
            with open(docker_compose_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 查找服务配置中的 volumes 部分
            # 匹配服务定义块
            service_pattern = rf'{re.escape(service_name)}\s*:.*?(?=\n  [a-z]|\n\n|\Z)'
            service_match = re.search(service_pattern, content, re.DOTALL)
            
            if service_match:
                service_config = service_match.group(0)
                # 查找 volumes: 部分
                volumes_pattern = r'volumes:\s*\n((?:\s+- .+\n?)+)'
                volumes_match = re.search(volumes_pattern, service_config)
                
                if volumes_match:
                    volumes_block = volumes_match.group(1)
                    # 提取每个挂载项
                    volume_items = re.findall(r'-\s*(.+)', volumes_block)
                    volumes_list = [item.strip() for item in volume_items]
        
        # 即使没有配置也返回空数组，而不是404
        return {"volumes": volumes_list}
    except Exception as e:
        # 返回空数组而不是错误，因为volumes可能不存在
        print(f"读取卷挂载失败（可能配置不存在）: {str(e)}")
        return {"volumes": []}

@app.post("/api/v1/custom-services/{service_name}/doc")
async def upload_service_doc(service_name: str, doc_file: UploadFile = File(...)):
    """上传或替换自定义服务的说明文档（仅限PDF）"""
    try:
        if not doc_file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="只支持PDF格式的说明文档")
        
        services = parse_docker_compose_custom_services()
        found = any(s['name'] == service_name for s in services)
        if not found:
            raise HTTPException(status_code=404, detail=f"服务 {service_name} 不存在")
        
        project_root = get_project_root()
        doc_dir = os.path.join(project_root, "config", service_name)
        os.makedirs(doc_dir, exist_ok=True)
        doc_path = os.path.join(doc_dir, "doc.pdf")
        with open(doc_path, "wb") as f:
            shutil.copyfileobj(doc_file.file, f)
        
        metadata = get_custom_services_metadata()
        if service_name in metadata:
            metadata[service_name]["has_doc"] = True
            metadata_path = os.path.join(project_root, "config", "custom-services.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return {"success": True, "message": "说明文档上传成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传说明文档失败: {str(e)}")

@app.get("/api/v1/custom-services/{service_name}/doc")
async def get_service_doc(service_name: str):
    """下载自定义服务的说明文档PDF"""
    try:
        project_root = get_project_root()
        doc_path = os.path.join(project_root, "config", service_name, "doc.pdf")
        if not os.path.exists(doc_path):
            raise HTTPException(status_code=404, detail="该服务没有说明文档")
        return FileResponse(doc_path, media_type="application/pdf", filename=f"{service_name}-doc.pdf")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取说明文档失败: {str(e)}")

@app.delete("/api/v1/custom-services/{service_name}/doc")
async def delete_service_doc(service_name: str):
    """删除自定义服务的说明文档"""
    try:
        project_root = get_project_root()
        doc_path = os.path.join(project_root, "config", service_name, "doc.pdf")
        if os.path.exists(doc_path):
            os.remove(doc_path)
        
        metadata = get_custom_services_metadata()
        if service_name in metadata:
            metadata[service_name]["has_doc"] = False
            metadata_path = os.path.join(project_root, "config", "custom-services.json")
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        return {"success": True, "message": "说明文档已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除说明文档失败: {str(e)}")

@app.get("/api/v1/custom-services/available-port")
async def get_available_port_api():
    """获取下一个可用端口"""
    try:
        port = get_available_port()
        return {"port": port}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取可用端口失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)

