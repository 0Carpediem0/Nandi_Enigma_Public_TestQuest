# -*- coding: utf-8 -*-
"""
Invoke-задачи: запуск проекта, инициализация БД, тесты.
Запуск: invoke up && invoke init-db && invoke test
Или одной командой: invoke run
"""
import os
import time
from pathlib import Path

from invoke import task

ROOT = Path(__file__).resolve().parent


def _cd_run(c, cmd, **kwargs):
    """Выполнить команду из корня проекта (совместимо с Windows Invoke)."""
    c.run(f"cd /d {ROOT} && {cmd}", **kwargs)


@task
def up(c):
    """Поднять PostgreSQL и backend (docker compose up -d). Пароль БД из backend/.env."""
    env_file = ROOT / "backend" / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass
    _cd_run(c, "docker compose up -d --build", pty=False)
    print("Ждём готовности сервисов (15 сек)...")
    time.sleep(15)


@task
def down(c, volumes=False):
    """Остановить контейнеры. invoke down -v — удалить и тома (для сброса пароля БД)."""
    cmd = "docker compose down"
    if volumes:
        cmd += " -v"
    _cd_run(c, cmd, pty=False)


@task
def init_db(c, drop=False):
    """
    Инициализировать БД и заполнить из kb_test.xlsx.
    Использует backend/.env, подключается к localhost:5432 (проброс из Docker).
    """
    os.chdir(ROOT)
    env = os.environ.copy()
    env.setdefault("PGHOST", "localhost")
    env.setdefault("PGPORT", "5432")
    env.setdefault("PGDATABASE", "test")
    cmd = "python init_database.py --seed"
    if drop:
        cmd += " --drop-existing"
    c.run(cmd, pty=False, env=env)


def _http_get(url: str) -> tuple[int, str]:
    """GET запрос (urllib), возвращает (status_code, text)."""
    import urllib.request
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def _http_post(url: str, data: str) -> tuple[int, str]:
    """POST JSON (urllib), возвращает (status_code, text)."""
    import urllib.request
    try:
        req = urllib.request.Request(
            url,
            data=data.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


@task
def test(c):
    """
    Проверить API: health, поиск по БЗ, ответ через /kb/ask.
    """
    base = "http://localhost:8000"
    print("1. GET /health")
    code, _ = _http_get(f"{base}/health")
    if code != 200:
        print(f"   Ошибка: health вернул {code}")
        return
    print("   OK")

    print("2. GET /kb/search?q=пароль&limit=2")
    code, out = _http_get(f"{base}/kb/search?q=пароль&limit=2")
    if code != 200 or "entries" not in out:
        print(f"   Предупреждение: код {code}, нет entries (пустая БЗ?)")
    else:
        print("   OK")

    print("3. POST /kb/ask")
    code, out = _http_post(
        f"{base}/kb/ask",
        '{"question": "Как установить пароль?", "limit": 3}',
    )
    if code != 200 or "answer" not in out:
        print(f"   Предупреждение: код {code}, нет answer")
    else:
        print("   OK")
        # Показать начало ответа
        import json
        try:
            d = json.loads(out)
            ans = (d.get("answer") or "")[:200]
            if ans:
                print(f"   Ответ: {ans}...")
        except Exception:
            pass

    print("\nГотово. Открой http://localhost:8000/docs для полного API.")


@task
def run(c, drop=False):
    """
    Полный цикл: поднять контейнеры, инициализировать БД (--seed), прогнать тесты.
    invoke run --drop  — пересоздать таблицы перед заполнением.
    """
    up(c)
    init_db(c, drop=drop)
    test(c)
