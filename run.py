#!/usr/bin/env python3
"""Cross-platform launcher for the FastAPI backend and Streamlit UI."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"


def fail(message: str) -> None:
    print(f"Ошибка: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(command: list[str], **kwargs) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def venv_python() -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return VENV / relative


def ensure_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        example = ROOT / ".env.example"
        if not example.exists():
            fail("отсутствуют и .env, и .env.example")
        shutil.copyfile(example, env_file)
        print("Создан .env из .env.example. Впишите OPENAI_API_KEY и запустите run.py снова.")
        raise SystemExit(1)


def ensure_venv() -> Path:
    python = venv_python()
    uv = shutil.which("uv")
    valid_existing = False
    if python.exists():
        valid_existing = subprocess.run(
            [str(python), "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    if not valid_existing:
        if uv:
            run([uv, "venv", "--python", "3.12", "--clear", str(VENV)])
        else:
            if sys.version_info < (3, 10):
                fail("нужен Python 3.10+ или установленный uv")
            run([sys.executable, "-m", "venv", "--clear", str(VENV)])
    if not python.exists():
        fail(f"не удалось создать виртуальное окружение: {VENV}")
    version_ok = subprocess.check_output(
        [str(python), "-c", "import sys; print(sys.version_info >= (3, 10))"], text=True,
    ).strip()
    if version_ok != "True":
        fail("Python внутри .venv должен быть версии 3.10 или новее")
    return python


def install_dependencies(python: Path) -> None:
    uv = shutil.which("uv")
    if uv:
        run([uv, "pip", "install", "--python", str(python), "-r", "requirements.txt"])
    else:
        run([str(python), "-m", "pip", "install", "-r", "requirements.txt"])


def port_is_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def check_ports(api_port: int, ui_port: int) -> None:
    command_hint = "set" if os.name == "nt" else "export"
    for port, name, hint in (
        (api_port, "FastAPI", f"PORT={api_port + 1}"),
        (ui_port, "Streamlit", f"STREAMLIT_PORT={ui_port + 1}"),
    ):
        if port_is_busy(port):
            if os.name == "nt":
                restart = f"set {hint}={port + 1} && py -3 run.py"
            else:
                restart = f"{command_hint} {hint}={port + 1}; python3 run.py"
            print(
                f"Порт {port} ({name}) уже занят. Освободите его или запустите с другим портом: "
                f"{restart}",
                file=sys.stderr,
            )
            raise SystemExit(1)


def terminate_processes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 5
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()


def main() -> int:
    ensure_env()
    python = ensure_venv()
    install_dependencies(python)
    api_port = int(os.getenv("PORT", "8000"))
    ui_port = int(os.getenv("STREAMLIT_PORT", "8501"))
    check_ports(api_port, ui_port)

    backend = [str(python), "-m", "uvicorn", "backend.app:app", "--port", str(api_port)]
    streamlit = [
        str(python), "-m", "streamlit", "run", str(ROOT / "Soile-Voice-Router" / "app.py"),
        "--server.address", "127.0.0.1", "--server.port", str(ui_port),
        "--server.headless", "true", "--browser.gatherUsageStats", "false",
    ]
    print(f"FastAPI:   http://127.0.0.1:{api_port}")
    print(f"Streamlit: http://127.0.0.1:{ui_port}")
    processes = [subprocess.Popen(backend, cwd=ROOT), subprocess.Popen(streamlit, cwd=ROOT)]
    try:
        while True:
            if any(process.poll() is not None for process in processes):
                return 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nОстанавливаю backend и Streamlit…")
        return 0
    finally:
        terminate_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
