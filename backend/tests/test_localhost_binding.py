# -*- coding: utf-8 -*-
"""Property-based tests for localhost binding security (bug condition exploration).

These tests verify that server configurations bind ONLY to loopback addresses.
On UNFIXED code, these tests will FAIL — confirming the bug exists.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Project root (two levels up from backend/tests/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ── Strategies ───────────────────────────────────────────────────────────────

# Generate arbitrary non-loopback IPs to represent external attackers
external_ips = st.tuples(
    st.integers(min_value=1, max_value=254),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=1, max_value=254),
).filter(
    lambda t: t[0] != 127  # Exclude loopback range
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}")


# ── Helper: Read actual config values ────────────────────────────────────────

def _read_uvicorn_host() -> str:
    """Extract the host parameter from uvicorn.run() in main.py."""
    main_py = PROJECT_ROOT / "main.py"
    content = main_py.read_text(encoding="utf-8")
    # Match host="..." in uvicorn.run() call
    match = re.search(r'uvicorn\.run\([^)]*host\s*=\s*"([^"]+)"', content, re.DOTALL)
    if match:
        return match.group(1)
    return ""


def _read_vite_host() -> str:
    """Extract the server.host value from frontend/vite.config.ts."""
    vite_config = PROJECT_ROOT / "frontend" / "vite.config.ts"
    content = vite_config.read_text(encoding="utf-8")
    # Match host: true or host: 'value' or host: "value"
    match = re.search(r'host\s*:\s*(true|false|[\'"]([^\'"]+)[\'"])', content)
    if match:
        return match.group(1)
    return ""


# ── Property 1: Bug Condition — External Network Binding Exposure ────────────
# Validates: Requirements 1.1, 1.2
#
# Bug Condition: isBugCondition(input) = input.source_ip ≠ "127.0.0.1"
#                AND server_bind_address = "0.0.0.0"
#
# This test asserts the EXPECTED (fixed) behavior:
#   - uvicorn host must be "127.0.0.1" (loopback only)
#   - vite host must be "localhost" (loopback only)
#
# On UNFIXED code this will FAIL because:
#   - main.py has host="0.0.0.0"
#   - vite.config.ts has host: true


@given(source_ip=external_ips)
@settings(max_examples=50, deadline=None)
def test_backend_binds_to_loopback_only(source_ip: str):
    """Property 1a: Backend server must bind to loopback address only.

    For any external IP, the server configuration must ensure the connection
    is refused by binding exclusively to 127.0.0.1.

    **Validates: Requirements 1.1**
    """
    host = _read_uvicorn_host()
    # The server must bind to loopback — external IPs should never reach it
    assert host == "127.0.0.1", (
        f"Bug condition confirmed: uvicorn binds to '{host}' instead of '127.0.0.1'. "
        f"External IP {source_ip} can reach the server."
    )


@given(source_ip=external_ips)
@settings(max_examples=50, deadline=None)
def test_frontend_binds_to_loopback_only(source_ip: str):
    """Property 1b: Frontend dev server must bind to localhost only.

    For any external IP, the Vite server configuration must ensure the
    connection is refused by binding exclusively to 'localhost'.

    **Validates: Requirements 1.2**
    """
    vite_host = _read_vite_host()
    # Must be 'localhost' (string), not `true` (which means 0.0.0.0)
    assert vite_host in ("'localhost'", '"localhost"'), (
        f"Bug condition confirmed: Vite server host is {vite_host} instead of 'localhost'. "
        f"External IP {source_ip} can reach the frontend dev server."
    )


# ── Property 2: Preservation — Settings OTHER than host binding remain unchanged ──
# These tests MUST PASS on the current (unfixed) code.
# They establish the baseline: all non-host settings are preserved after the fix.


# ── Strategies for preservation tests ────────────────────────────────────────

# Loopback addresses that should always work (preservation of local access)
loopback_addresses = st.sampled_from(["127.0.0.1", "localhost", "::1"])


# ── Helpers: Observe current configuration values ────────────────────────────

def _read_main_py() -> str:
    """Read main.py content."""
    return (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")


def _read_vite_config() -> str:
    """Read frontend/vite.config.ts content."""
    return (PROJECT_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")


def _read_sectorflow_command() -> str:
    """Read SectorFlow.command content."""
    return (PROJECT_ROOT / "SectorFlow.command").read_text(encoding="utf-8")


# ── Property 2a: main.py uvicorn settings preservation ──────────────────────
# Validates: Requirements 3.1, 3.5

@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_uvicorn_port_preserved(loopback: str):
    """Property 2a-1: uvicorn port must remain 8000.

    For any loopback address used for local access, the uvicorn port
    configuration must remain at 8000.

    **Validates: Requirements 3.1**
    """
    content = _read_main_py()
    match = re.search(r'uvicorn\.run\([^)]*port\s*=\s*(\d+)', content, re.DOTALL)
    assert match is not None, "uvicorn.run() port parameter not found in main.py"
    assert match.group(1) == "8000", (
        f"uvicorn port changed from 8000 to {match.group(1)}"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_uvicorn_app_path_preserved(loopback: str):
    """Property 2a-2: uvicorn app path must remain 'app.web.app:app'.

    **Validates: Requirements 3.1**
    """
    content = _read_main_py()
    match = re.search(r'uvicorn\.run\(\s*"([^"]+)"', content, re.DOTALL)
    assert match is not None, "uvicorn.run() app path not found in main.py"
    assert match.group(1) == "app.web.app:app", (
        f"uvicorn app path changed from 'app.web.app:app' to '{match.group(1)}'"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_uvicorn_log_level_preserved(loopback: str):
    """Property 2a-3: uvicorn log_level must remain 'info'.

    **Validates: Requirements 3.1**
    """
    content = _read_main_py()
    match = re.search(r'uvicorn\.run\([^)]*log_level\s*=\s*"([^"]+)"', content, re.DOTALL)
    assert match is not None, "uvicorn.run() log_level parameter not found in main.py"
    assert match.group(1) == "info", (
        f"uvicorn log_level changed from 'info' to '{match.group(1)}'"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_uvicorn_ws_ping_interval_preserved(loopback: str):
    """Property 2a-4: uvicorn ws_ping_interval must remain 30.

    **Validates: Requirements 3.5**
    """
    content = _read_main_py()
    match = re.search(r'uvicorn\.run\([^)]*ws_ping_interval\s*=\s*(\d+)', content, re.DOTALL)
    assert match is not None, "uvicorn.run() ws_ping_interval parameter not found in main.py"
    assert match.group(1) == "30", (
        f"uvicorn ws_ping_interval changed from 30 to {match.group(1)}"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_uvicorn_ws_ping_timeout_preserved(loopback: str):
    """Property 2a-5: uvicorn ws_ping_timeout must remain 10.

    **Validates: Requirements 3.5**
    """
    content = _read_main_py()
    match = re.search(r'uvicorn\.run\([^)]*ws_ping_timeout\s*=\s*(\d+)', content, re.DOTALL)
    assert match is not None, "uvicorn.run() ws_ping_timeout parameter not found in main.py"
    assert match.group(1) == "10", (
        f"uvicorn ws_ping_timeout changed from 10 to {match.group(1)}"
    )


# ── Property 2b: frontend/vite.config.ts settings preservation ───────────────
# Validates: Requirements 3.2, 3.3

@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_vite_port_preserved(loopback: str):
    """Property 2b-1: Vite server port must remain 5173.

    **Validates: Requirements 3.2**
    """
    content = _read_vite_config()
    match = re.search(r'port\s*:\s*(\d+)', content)
    assert match is not None, "Vite server port not found in vite.config.ts"
    assert match.group(1) == "5173", (
        f"Vite server port changed from 5173 to {match.group(1)}"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_vite_proxy_target_preserved(loopback: str):
    """Property 2b-2: Vite proxy target must remain 'http://localhost:8000'.

    **Validates: Requirements 3.3**
    """
    content = _read_vite_config()
    match = re.search(r"target\s*:\s*['\"]([^'\"]+)['\"]", content)
    assert match is not None, "Vite proxy target not found in vite.config.ts"
    assert match.group(1) == "http://localhost:8000", (
        f"Vite proxy target changed from 'http://localhost:8000' to '{match.group(1)}'"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_vite_proxy_ws_preserved(loopback: str):
    """Property 2b-3: Vite proxy WebSocket support must remain true.

    **Validates: Requirements 3.3**
    """
    content = _read_vite_config()
    match = re.search(r'ws\s*:\s*(true|false)', content)
    assert match is not None, "Vite proxy ws setting not found in vite.config.ts"
    assert match.group(1) == "true", (
        f"Vite proxy ws changed from true to {match.group(1)}"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_vite_proxy_change_origin_preserved(loopback: str):
    """Property 2b-4: Vite proxy changeOrigin must remain true.

    **Validates: Requirements 3.3**
    """
    content = _read_vite_config()
    match = re.search(r'changeOrigin\s*:\s*(true|false)', content)
    assert match is not None, "Vite proxy changeOrigin setting not found in vite.config.ts"
    assert match.group(1) == "true", (
        f"Vite proxy changeOrigin changed from true to {match.group(1)}"
    )


# ── Property 2c: SectorFlow.command preservation ─────────────────────────────
# Validates: Requirements 3.4

@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_sectorflow_healthcheck_url_preserved(loopback: str):
    """Property 2c-1: SectorFlow.command must use localhost:8000/health for healthcheck.

    **Validates: Requirements 3.4**
    """
    content = _read_sectorflow_command()
    assert "http://localhost:8000/health" in content, (
        "SectorFlow.command no longer uses http://localhost:8000/health for healthcheck"
    )


@given(loopback=loopback_addresses)
@settings(max_examples=20, deadline=None)
def test_sectorflow_frontend_url_preserved(loopback: str):
    """Property 2c-2: SectorFlow.command must use localhost:5173 for frontend.

    **Validates: Requirements 3.2**
    """
    content = _read_sectorflow_command()
    assert "http://localhost:5173" in content, (
        "SectorFlow.command no longer uses http://localhost:5173 for frontend check"
    )
