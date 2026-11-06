"""Single-command launcher for SIPEKA-Banjir 3D (`python run.py`)."""

from __future__ import annotations

import socket
import uvicorn


def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main() -> None:
    """Start the FastAPI / Uvicorn server on http://0.0.0.0:8000 (accessible from Desktop & Mobile)."""
    lan_ip = _get_local_ip()
    print("=" * 72)
    print("  SIPEKA-Banjir 3D — Sistem Pemetaan Kerawanan Banjir Kota Pekanbaru")
    print("  Metode: Multi-Criteria Evaluation (MCE) & Weighted Overlay (30m)")
    print("-" * 72)
    print("  🖥️  Buka di Laptop / Desktop : http://localhost:8000")
    print(f"  📱 Buka di HP (Wi-Fi sama)  : http://{lan_ip}:8000")
    print("=" * 72)
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
