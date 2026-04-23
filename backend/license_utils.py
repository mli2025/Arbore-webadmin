"""
Arbore 许可证模块 - 宿主机硬件指纹与校验码验证
Arbore License Utilities – host hardware fingerprint & validation code.

硬件指纹始终使用宿主机标识，不使用容器 ID。
在容器化部署环境中，任何依赖容器自身 ID 作为授权依据的做法都不够稳定，
因此本模块统一通过宿主机 machine-id 计算出稳定的指纹，用于生成和校验许可证。

Docker 部署时需将宿主机 /etc/machine-id 挂载到容器内，例如：
  -v /etc/machine-id:/host/etc/machine-id:ro
或设置环境变量 HOST_MACHINE_ID_FILE 指向宿主机 machine-id 文件路径。

High‑level description (English):
- The license system always binds to the physical host identity instead of
  ephemeral container identifiers.
- A stable fingerprint is derived from the host `machine-id` using SHA‑256,
  and then combined with company information and version prefix to generate
  an HMAC based validation code.
- This module is intentionally self‑contained so that it can be reused by
  both the backend API and offline tooling used to issue licenses.
"""
import os
import json
import hmac
import hashlib
from typing import Optional, Tuple, Dict

# 宿主机 machine-id 候选路径（优先使用显式挂载的宿主机路径）
HOST_MACHINE_ID_PATHS = [
    os.environ.get("HOST_MACHINE_ID_FILE"),  # 显式指定宿主机 machine-id 文件路径
    "/host/etc/machine-id",   # 常见：宿主机挂载到容器内
    "/etc/machine-id",        # 直接跑在宿主机上，或宿主机挂载到此
]
LICENSE_FILENAME = "license.json"
# 版本号只取主段，如 1.1.0 -> 001
VERSION_MAJOR_PREFIX = "001"


def _get_project_root() -> str:
    env_root = os.environ.get('ARBORE_PROJECT_ROOT')
    if env_root:
        return env_root
    current_file = os.path.abspath(__file__)
    return os.path.dirname(os.path.dirname(os.path.dirname(current_file)))


def get_host_hardware_fingerprint() -> Tuple[Optional[str], str]:
    """
    获取宿主机硬件指纹（只读宿主机，不使用容器 ID）。
    依次尝试: HOST_MACHINE_ID_FILE -> /host/etc/machine-id -> /etc/machine-id
    返回 (fingerprint_id, display_id)，例如 ("abc123", "host-abc123")。
    若无法获取则 fingerprint_id 为 None，display_id 为错误描述。
    """
    for path in HOST_MACHINE_ID_PATHS:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                continue
            # 使用 SHA256 得到固定长度指纹（与文档一致）
            fingerprint = hashlib.sha256(raw.encode()).hexdigest()
            display_id = f"host-{fingerprint[:16]}"
            return (fingerprint, display_id)
        except Exception:
            continue
    return (None, "host-unavailable (mount host /etc/machine-id)")


# 与 validation-code-generator.js 中硬编码密钥一致，未配置环境变量时使用
DEFAULT_LICENSE_SECRET = "Arbore-License-Secret-Key-2024"

def get_license_secret() -> Optional[str]:
    """从环境变量读取 HMAC 密钥（与 validation-code-generator.js 一致），未配置时使用默认密钥"""
    return os.environ.get("ARBORE_LICENSE_SECRET") or os.environ.get("LICENSE_HMAC_SECRET") or DEFAULT_LICENSE_SECRET


def _version_major(version: str) -> str:
    """版本号取主段，如 1.1.0 / 001.0064 -> 001"""
    if not version:
        return VERSION_MAJOR_PREFIX
    part = version.split(".")[0].strip()
    if not part.isdigit():
        return VERSION_MAJOR_PREFIX
    return part.zfill(3)


def _version_major_for_hmac(version: str) -> str:
    """与 validation-code-generator.js 一致：主段取 3 位（如 001.0001->001，1.1.0->001），与 JS fallback 对齐"""
    part = (version or "").split(".")[0].strip()
    if not part or not part.isdigit():
        return "001"
    return part.zfill(3)

def compute_validation_code(company_id: str, host_id: str, version: str, secret: str) -> str:
    """与 validation-code-generator.js 完全一致：HMAC-SHA256(companyId-hostId-versionMajor)，取前16位大写。
    host_id 使用界面展示的主机标识，如 host-a5b50f0617a557b8（与 JS 的 hostId 一致）。"""
    version_major = _version_major_for_hmac(version)
    message = f"{company_id}-{host_id}-{version_major}"
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest().upper()
    return digest[:16]


def get_license_path() -> str:
    """license.json 存放路径：项目 config 目录"""
    root = _get_project_root()
    config_dir = os.path.join(root, "config")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, LICENSE_FILENAME)


def load_license() -> Optional[Dict]:
    """读取当前 license.json，不存在或格式错误返回 None"""
    path = get_license_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_license(data: Dict) -> None:
    """写入 license.json"""
    path = get_license_path()
    root = _get_project_root()
    config_dir = os.path.join(root, "config")
    os.makedirs(config_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def validate_license(version: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
    """
    验证当前许可证是否有效。
    返回 (is_valid, error_code, license_data)。
    error_code: LICENSE_NOT_FOUND, LICENSE_INVALID, HARDWARE_MISMATCH, VERSION_MISMATCH, SECRET_NOT_CONFIGURED
    """
    secret = get_license_secret()
    if not secret:
        return (False, "SECRET_NOT_CONFIGURED", None)

    license_data = load_license()
    if not license_data:
        return (False, "LICENSE_NOT_FOUND", None)

    company_id = license_data.get("companyId") or license_data.get("company_id")
    validation_code = license_data.get("validationCode") or license_data.get("validation_code")
    company_name = license_data.get("companyName") or license_data.get("company_name")
    if not company_id or not validation_code:
        return (False, "LICENSE_INVALID", None)

    host_fingerprint, display_id = get_host_hardware_fingerprint()
    if not host_fingerprint:
        return (False, "HARDWARE_MISMATCH", None)

    # 使用 display_id（host-xxx）与 validation-code-generator.js 的 hostId 一致
    expected_code = compute_validation_code(company_id, display_id, version, secret)
    if not hmac.compare_digest(expected_code.upper(), str(validation_code).upper()):
        return (False, "LICENSE_INVALID", None)

    version_major = _version_major(version)
    # 可选：校验版本主段与签发时一致（若 license 中存了 version）
    stored_version = license_data.get("version") or license_data.get("versionInfo")
    if stored_version and _version_major(str(stored_version)) != version_major:
        return (False, "VERSION_MISMATCH", None)

    return (True, None, {
        "companyId": company_id,
        "companyName": company_name or "",
        "validationCode": validation_code,
        "versionInfo": version_major,
    })
