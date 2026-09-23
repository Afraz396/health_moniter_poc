import os
import time
import socket
import platform
import subprocess
import socket as socket_lib

import requests

from typing import Dict, Any

from fastapi import FastAPI, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="Production Health Monitoring API",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ENVIRONMENT CONFIGURATION
# ============================================================

# ------------------------------------------------------------
# Backend systemd service
# ------------------------------------------------------------

BACKEND_SERVICE = os.getenv(
    "BACKEND_SERVICE",
    "ttg_investor.service"
)


# ------------------------------------------------------------
# Coolify / Docker containers
# ------------------------------------------------------------

PROXY_CONTAINER = os.getenv(
    "PROXY_CONTAINER",
    "coolify-proxy"
)

COOLIFY_CONTAINER = os.getenv(
    "COOLIFY_CONTAINER",
    "coolify"
)

POSTGRES_CONTAINER = os.getenv(
    "POSTGRES_CONTAINER",
    "coolify-db"
)

REDIS_CONTAINER = os.getenv(
    "REDIS_CONTAINER",
    "coolify-redis"
)

REALTIME_CONTAINER = os.getenv(
    "REALTIME_CONTAINER",
    "coolify-realtime"
)


# ------------------------------------------------------------
# Mail daemon
# ------------------------------------------------------------

MAIL_DAEMON_SERVICE = os.getenv(
    "MAIL_DAEMON_SERVICE",
    "postfix.service"
)


# ------------------------------------------------------------
# Proxy HTTP health check
# ------------------------------------------------------------

PROXY_HEALTH_URL = os.getenv(
    "PROXY_HEALTH_URL",
    "http://127.0.0.1"
)


# ------------------------------------------------------------
# SMTP
# ------------------------------------------------------------

SMTP_HOST = os.getenv(
    "SMTP_HOST",
    "smtp.gmail.com"
)

SMTP_PORT = int(
    os.getenv(
        "SMTP_PORT",
        "587"
    )
)


# ============================================================
# ALLOWED SERVICES
# ============================================================

ALLOWED_SERVICES = {

    # Systemd
    "backend": {
        "type": "systemd",
        "name": BACKEND_SERVICE
    },

    "mail": {
        "type": "systemd",
        "name": MAIL_DAEMON_SERVICE
    },

    # Docker
    "proxy": {
        "type": "docker",
        "name": PROXY_CONTAINER
    },

    "coolify": {
        "type": "docker",
        "name": COOLIFY_CONTAINER
    },

    "postgresql": {
        "type": "docker",
        "name": POSTGRES_CONTAINER
    },

    "redis": {
        "type": "docker",
        "name": REDIS_CONTAINER
    },

    "realtime": {
        "type": "docker",
        "name": REALTIME_CONTAINER
    },
}


# ============================================================
# UTILITY
# ============================================================

def calculate_latency(start_time: float) -> int:
    return int(
        (time.time() - start_time) * 1000
    )


# ============================================================
# SYSTEMD SERVICE CHECK
# ============================================================

def check_systemd_service(
    service_name: str
) -> Dict[str, Any]:

    start_time = time.time()

    try:

        result = subprocess.run(
            [
                "systemctl",
                "is-active",
                service_name
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        status = result.stdout.strip()

        latency = calculate_latency(start_time)

        if status == "active":

            return {
                "status": "up",
                "latency_ms": latency,
                "service": service_name
            }

        return {
            "status": "down",
            "latency_ms": latency,
            "service": service_name,
            "error": (
                f"{service_name} is "
                f"{status or 'inactive'}"
            )
        }

    except subprocess.TimeoutExpired:

        return {
            "status": "down",
            "service": service_name,
            "error": (
                f"Timeout checking "
                f"{service_name}"
            )
        }

    except Exception as exc:

        return {
            "status": "down",
            "service": service_name,
            "error": str(exc)
        }


# ============================================================
# DOCKER CONTAINER CHECK
# ============================================================

def check_docker_container(
    container_name: str
) -> Dict[str, Any]:

    start_time = time.time()

    try:

        result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                container_name
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        latency = calculate_latency(start_time)

        if result.returncode != 0:

            return {
                "status": "down",
                "latency_ms": latency,
                "container": container_name,
                "error": (
                    result.stderr.strip()
                    or
                    f"Container {container_name} "
                    f"not found"
                )
            }

        running = (
            result.stdout.strip().lower()
            == "true"
        )

        if running:

            return {
                "status": "up",
                "latency_ms": latency,
                "container": container_name
            }

        return {
            "status": "down",
            "latency_ms": latency,
            "container": container_name,
            "error": (
                f"Container {container_name} "
                f"is not running"
            )
        }

    except subprocess.TimeoutExpired:

        return {
            "status": "down",
            "container": container_name,
            "error": (
                f"Timeout checking Docker "
                f"container {container_name}"
            )
        }

    except Exception as exc:

        return {
            "status": "down",
            "container": container_name,
            "error": str(exc)
        }


# ============================================================
# PROXY HTTP CHECK
# ============================================================

def check_proxy_http() -> Dict[str, Any]:

    start_time = time.time()

    try:

        response = requests.get(
            PROXY_HEALTH_URL,
            timeout=5
        )

        latency = calculate_latency(start_time)

        if response.status_code < 500:

            return {
                "status": "up",
                "http_status": response.status_code,
                "latency_ms": latency,
                "url": PROXY_HEALTH_URL
            }

        return {
            "status": "down",
            "http_status": response.status_code,
            "latency_ms": latency,
            "url": PROXY_HEALTH_URL,
            "error": "Proxy returned server error"
        }

    except requests.RequestException as exc:

        return {
            "status": "down",
            "url": PROXY_HEALTH_URL,
            "error": str(exc)
        }


# ============================================================
# SMTP CHECK
# ============================================================

def check_smtp_relay() -> Dict[str, Any]:

    start_time = time.time()

    try:

        with socket_lib.socket(
            socket_lib.AF_INET,
            socket_lib.SOCK_STREAM
        ) as sock:

            sock.settimeout(5)

            sock.connect(
                (
                    SMTP_HOST,
                    SMTP_PORT
                )
            )

        latency = calculate_latency(start_time)

        return {
            "status": "up",
            "latency_ms": latency,
            "host": SMTP_HOST,
            "port": SMTP_PORT
        }

    except Exception as exc:

        return {
            "status": "down",
            "host": SMTP_HOST,
            "port": SMTP_PORT,
            "error": str(exc)
        }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health_check(response: Response):

    services = {

        # Systemd
        "backend_service":
            check_systemd_service(
                BACKEND_SERVICE
            ),

        "local_mail_daemon":
            check_systemd_service(
                MAIL_DAEMON_SERVICE
            ),

        # Docker
        "proxy":
            check_docker_container(
                PROXY_CONTAINER
            ),

        "coolify":
            check_docker_container(
                COOLIFY_CONTAINER
            ),

        "postgresql":
            check_docker_container(
                POSTGRES_CONTAINER
            ),

        "redis":
            check_docker_container(
                REDIS_CONTAINER
            ),

        "realtime":
            check_docker_container(
                REALTIME_CONTAINER
            ),

        # Network
        "proxy_http":
            check_proxy_http(),

        "smtp_relay":
            check_smtp_relay(),
    }


    # --------------------------------------------------------
    # Overall status
    # --------------------------------------------------------

    overall_status = "healthy"

    for service in services.values():

        if service.get("status") != "up":

            overall_status = "unhealthy"

            break


    # Return HTTP 503 when any service is unhealthy
    if overall_status == "unhealthy":

        response.status_code = 503


    return {

        "status": overall_status,

        "server": {
            "hostname": socket.gethostname(),
            "os": platform.platform(),
            "timestamp_utc": time.strftime(
                "%Y-%m-%d %H:%M:%S UTC",
                time.gmtime()
            )
        },

        "services": services
    }


# ============================================================
# SERVICE LIST
# ============================================================

@app.get("/services")
def services():

    return {
        "services": ALLOWED_SERVICES
    }


# ============================================================
# SYSTEMD ACTION
# ============================================================

def execute_systemctl(
    action: str,
    service_name: str
) -> Dict[str, Any]:

    if action not in {
        "start",
        "restart"
    }:

        raise HTTPException(
            status_code=400,
            detail="Invalid service action"
        )


    result = subprocess.run(
        [
            "sudo",
            "systemctl",
            action,
            service_name
        ],
        capture_output=True,
        text=True,
        timeout=30
    )


    if result.returncode != 0:

        raise HTTPException(
            status_code=500,
            detail=(
                result.stderr.strip()
                or
                f"Failed to {action} "
                f"{service_name}"
            )
        )


    return {
        "success": True,
        "action": action,
        "service": service_name,
        "type": "systemd",
        "message": (
            f"{service_name} "
            f"{action} command executed successfully"
        )
    }


# ============================================================
# DOCKER ACTION
# ============================================================

def execute_docker(
    action: str,
    container_name: str
) -> Dict[str, Any]:

    if action not in {
        "start",
        "restart"
    }:

        raise HTTPException(
            status_code=400,
            detail="Invalid Docker action"
        )


    result = subprocess.run(
        [
            "sudo",
            "docker",
            action,
            container_name
        ],
        capture_output=True,
        text=True,
        timeout=30
    )


    if result.returncode != 0:

        raise HTTPException(
            status_code=500,
            detail=(
                result.stderr.strip()
                or
                f"Failed to {action} "
                f"{container_name}"
            )
        )


    return {
        "success": True,
        "action": action,
        "container": container_name,
        "type": "docker",
        "message": (
            f"{container_name} "
            f"{action} command executed successfully"
        )
    }


# ============================================================
# START SERVICE
# ============================================================

@app.post("/services/{service_key}/start")
def start_service(
    service_key: str
):

    if service_key not in ALLOWED_SERVICES:

        raise HTTPException(
            status_code=404,
            detail="Service not allowed"
        )


    service = ALLOWED_SERVICES[
        service_key
    ]


    if service["type"] == "docker":

        return execute_docker(
            "start",
            service["name"]
        )


    return execute_systemctl(
        "start",
        service["name"]
    )


# ============================================================
# RESTART SERVICE
# ============================================================

@app.post("/services/{service_key}/restart")
def restart_service(
    service_key: str
):

    if service_key not in ALLOWED_SERVICES:

        raise HTTPException(
            status_code=404,
            detail="Service not allowed"
        )


    service = ALLOWED_SERVICES[
        service_key
    ]


    if service["type"] == "docker":

        return execute_docker(
            "restart",
            service["name"]
        )


    return execute_systemctl(
        "restart",
        service["name"]
    )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "application":
            "Production Health Monitoring API",

        "status":
            "running",

        "version":
            "1.0.0"
    }