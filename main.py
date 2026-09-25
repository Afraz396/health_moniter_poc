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
# Nginx systemd service
# ------------------------------------------------------------

NGINX_SERVICE = os.getenv(
    "NGINX_SERVICE",
    "nginx.service"
)


# ------------------------------------------------------------
# PostgreSQL systemd service
# ------------------------------------------------------------

POSTGRESQL_SERVICE = os.getenv(
    "POSTGRESQL_SERVICE",
    "postgresql.service"
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

    # Systemd services

    "backend": {
        "type": "systemd",
        "name": BACKEND_SERVICE
    },

    "nginx": {
        "type": "systemd",
        "name": NGINX_SERVICE
    },

    "postgresql": {
        "type": "systemd",
        "name": POSTGRESQL_SERVICE
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
        "/usr/bin/systemctl",
        "is-active",
        service_name
    ],
            capture_output=True,
            text=True,
            timeout=5
        )

        status = result.stdout.strip()

        latency = calculate_latency(
            start_time
        )

        if status == "active":

            return {
                "status": "up",
                "service": service_name
                # "latency_ms": latency,
            }

        return {
            "status": "down",
            "service": service_name,
            "error": (
                f"{service_name} is "
                f"{status or 'inactive'}"
            )
            # "latency_ms": latency,
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
# PROXY HTTP CHECK
# ============================================================

# def check_proxy_http() -> Dict[str, Any]:

#     start_time = time.time()

#     try:

#         response = requests.get(
#             PROXY_HEALTH_URL,
#             timeout=5
#         )

#         latency = calculate_latency(
#             start_time
#         )

#         if response.status_code < 500:

#             return {
#                 "status": "up",
#                 "http_status": response.status_code,
#                 # "url": PROXY_HEALTH_URL
#                 # "latency_ms": latency,
#             }

#         return {
#             "status": "down",
#             "http_status": response.status_code,
#             # "url": PROXY_HEALTH_URL,
#             "error": "Proxy returned server error"
#             # "latency_ms": latency,
#         }

#     except requests.RequestException as exc:

#         return {
#             "status": "down",
#             # "url": PROXY_HEALTH_URL,
#             "error": str(exc)
#         }


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

        latency = calculate_latency(
            start_time
        )

        return {
            "status": "up",
            "host": SMTP_HOST,
            "port": SMTP_PORT
            # "latency_ms": latency,
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

        # Backend
        "backend_service":
            check_systemd_service(
                BACKEND_SERVICE
            ),

        # Nginx
        "nginx":
            check_systemd_service(
                NGINX_SERVICE
            ),

        # PostgreSQL
        "postgresql":
            check_systemd_service(
                POSTGRESQL_SERVICE
            ),

        # Proxy HTTP
        # "proxy_http":
        #     check_proxy_http(),
    }


    # --------------------------------------------------------
    # Overall status
    # --------------------------------------------------------

    overall_status = "healthy"

    for service in services.values():

        if service.get("status") != "up":

            overall_status = "unhealthy"

            break


    # --------------------------------------------------------
    # Return HTTP 503 when any service is unhealthy
    # --------------------------------------------------------

    if overall_status == "unhealthy":

        response.status_code = 503


    return {

        "status": overall_status,

        "server": {

            "hostname":
                socket.gethostname(),

            "os":
                platform.platform(),

            "timestamp_utc":
                time.strftime(
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
        "/usr/bin/systemctl",
        action,
        service_name
    ],
    capture_output=True,
    text=True,
    timeout=30
)
    
    print("RETURN CODE:", result.returncode)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)



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