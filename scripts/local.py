#!/usr/bin/env python3.11
"""Isolated native stack: python3.11 scripts/local.py setup|run (see --help)."""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'run'])
    parser.add_argument('--state-dir', type=Path, default=Path.home() / '.local/share/ed-native')
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--web-port', type=int, default=3000)
    parser.add_argument('--provision-models', action='store_true', help='Download EasyOCR weights during setup')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.error('Use Python 3.11; this script never modifies backend/.venv.')
    state = args.state_dir.expanduser().resolve()
    state.mkdir(parents=True, exist_ok=True)
    lock = (state / 'launcher.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error('Another launcher owns this state directory.')
    python = state / 'venv/bin/python'
    env = os.environ.copy()
    env.update(DATABASE_URL=f'sqlite:///{state / "ed.db"}', UPLOAD_DIR=str(state / 'uploads'),
               EASYOCR_MODULE_PATH=str(state / 'models'),
               PYTHONPATH=str(ROOT / 'backend'), CORS_ORIGINS=f'http://localhost:{args.web_port}',
               API_INTERNAL_URL=f'http://127.0.0.1:{args.api_port}')
    node = shutil.which('node')
    npm = shutil.which('npm')
    if not node or not npm:
        parser.error('Put Node.js 22 and npm on PATH.')
    version = subprocess.check_output([node, '--version'], text=True).strip()
    if version.split('.')[0] != 'v22':
        parser.error(f'Expected Node.js 22, found {version}')

    def run(command, cwd=ROOT / 'backend'):
        subprocess.run([str(x) for x in command], cwd=cwd, env=env, check=True)

    if args.command == 'setup':
        if not python.exists():
            run([sys.executable, '-m', 'venv', state / 'venv'])
        run([python, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple', 'pip==26.3', 'setuptools==84.2.1'])
        run([python, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple', '--require-hashes', '-r', 'requirements.lock'])
        run([python, '-m', 'pip', 'install', '--index-url', 'https://pypi.org/simple', '-c', 'requirements.lock', '-r', 'requirements-easyocr.txt'])
        run([python, '-m', 'pip', 'check'])
        run([npm, 'ci'], ROOT / 'frontend')
        if args.provision_models:
            run([python, 'scripts/provision_models.py', '--engine', 'easyocr'])
        return
    if not python.exists():
        parser.error('Run setup first with this state directory.')
    # Check both ports before migrations or starting any child.
    for port in (args.api_port, args.web_port):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                parser.error(f'Port {port} unavailable; choose another port. Existing processes are untouched.')
    run([python, '-m', 'alembic', 'upgrade', 'head'])
    children = []

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        commands = [([python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(args.api_port)], ROOT / 'backend'),
                    ([python, '-m', 'app.worker'], ROOT / 'backend'),
                    ([npm, 'run', 'dev', '--', '--hostname', '127.0.0.1', '--port', str(args.web_port)], ROOT / 'frontend')]
        for command, cwd in commands:
            children.append(subprocess.Popen([str(x) for x in command], cwd=cwd, env=env, start_new_session=True))
        print(f'Web: http://localhost:{args.web_port}; state: {state}', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        raise RuntimeError('A stack process exited; stopping the other launcher children.')
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == '__main__':
    main()
