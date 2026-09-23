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


app = FastAPI(
    title="Production Health Monitoring API",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:5173"
)

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

# Systemd services
BACKEND_SERVICE = os.getenv(
    "BACKEND_SERVICE",
    "ttg_investor.service"
)

NGINX_SERVICE = os.getenv(
    "NGINX_SERVICE",
    "nginx.service"
)

MAIL_DAEMON_SERVICE = os.getenv(
    "MAIL_DAEMON_SERVICE",
    "postfix.service"
)


# PostgreSQL Docker container
POSTGRES_CONTAINER = os.getenv(
    "POSTGRES_CONTAINER",
    "coolify-db"
)


# Nginx health URL
NGINX_HEALTH_URL = os.getenv(
    "NGINX_HEALTH_URL",
    "http://127.0.0.1"
)


# SMTP
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
    "backend": BACKEND_SERVICE,
    "nginx": NGINX_SERVICE,
    "mail": MAIL_DAEMON_SERVICE,
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
            "error": f"{service_name} is {status or 'inactive'}"
        }

    except subprocess.TimeoutExpired:

        return {
            "status": "down",
            "error": f"Timeout checking {service_name}"
        }

    except Exception as exc:

        return {
            "status": "down",
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
                "error": result.stderr.strip()
                or f"Container {container_name} not found"
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
            "error": f"Container {container_name} is not running"
        }

    except subprocess.TimeoutExpired:

        return {
            "status": "down",
            "error": f"Timeout checking Docker container {container_name}"
        }

    except Exception as exc:

        return {
            "status": "down",
            "error": str(exc)
        }


# ============================================================
# NGINX HTTP CHECK
# ============================================================

def check_nginx_http() -> Dict[str, Any]:

    start_time = time.time()

    try:

        response = requests.get(
            NGINX_HEALTH_URL,
            timeout=5
        )

        latency = calculate_latency(start_time)

        if response.status_code < 500:

            return {
                "status": "up",
                "http_status": response.status_code,
                "latency_ms": latency
            }

        return {
            "status": "down",
            "http_status": response.status_code,
            "latency_ms": latency,
            "error": "Nginx returned server error"
        }

    except requests.RequestException as exc:

        return {
            "status": "down",
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
# SERVICE STATUS
# ============================================================

@app.get("/health")
def health_check(response: Response):

    services = {

        "backend_service":
            check_systemd_service(
                BACKEND_SERVICE
            ),

        "nginx":
            check_systemd_service(
                NGINX_SERVICE
            ),

        "nginx_http":
            check_nginx_http(),

        "postgresql":
            check_docker_container(
                POSTGRES_CONTAINER
            ),

        "smtp_relay":
            check_smtp_relay(),

        "local_mail_daemon":
            check_systemd_service(
                MAIL_DAEMON_SERVICE
            ),
    }

    overall_status = "healthy"

    for service in services.values():

        if service.get("status") != "up":

            overall_status = "unhealthy"
            break

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
# SERVICE STATUS DETAIL
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
            detail=result.stderr.strip()
            or f"Failed to {action} {service_name}"
        )

    return {
        "success": True,
        "action": action,
        "service": service_name,
        "message": (
            f"{service_name} "
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

    service_name = ALLOWED_SERVICES[
        service_key
    ]

    return execute_systemctl(
        "start",
        service_name
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

    service_name = ALLOWED_SERVICES[
        service_key
    ]

    return execute_systemctl(
        "restart",
        service_name
    )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "application": "Production Health Monitoring API",
        "status": "running"
    }