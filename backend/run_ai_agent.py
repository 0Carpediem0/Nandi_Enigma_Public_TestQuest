"""
Агент: периодически забирает последнее письмо из INBOX и запускает AI-пайплайн.
Запуск: из папки backend выполнить
  python run_ai_agent.py
Требуется запущенный backend на http://localhost:8000
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

API_BASE = os.getenv("AI_AGENT_API_BASE", "http://localhost:8000")
INTERVAL_SEC = int(os.getenv("AI_AGENT_INTERVAL_SEC", "60"))


def process_latest():
    url = f"{API_BASE}/mvp/process-latest"
    data = json.dumps({"mailbox": "INBOX"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        try:
            return e.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return e.code, {"error": body}
    except urllib.error.URLError as e:
        return None, {"error": str(e.reason)}
    except Exception as e:
        return None, {"error": str(e)}


def main():
    print(f"AI-агент: опрос {API_BASE} каждые {INTERVAL_SEC} сек. Остановка: Ctrl+C")
    while True:
        try:
            status, result = process_latest()
            if status == 200:
                print(
                    f"[OK] Обработано: от={result.get('source_from', '?')} "
                    f"тема={result.get('source_subject', '?')[:50]} "
                    f"ticket -> оператору"
                )
            elif status == 404:
                print("[--] В ящике нет писем, ждём...")
            elif status is not None:
                print(f"[ERR] HTTP {status}: {result.get('error', result)}")
            else:
                print(f"[ERR] {result.get('error', 'нет связи с backend')}")
        except KeyboardInterrupt:
            print("\nОстановка агента.")
            sys.exit(0)
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    main()
