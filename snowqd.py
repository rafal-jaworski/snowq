#!/usr/bin/env python3
"""snowqd — jeden długo-żyjący proces trzymający JEDNO połączenie do Snowflake.
Loguje się raz (externalbrowser popup przy starcie), trzyma sesję żywą i obsługuje
zapytania od klienta `snowq` przez unix-socket. Wiele klientów może dobijać
równolegle — zapytania serializują się na jednym połączeniu (lock).
Stan (socket/log) i venv leżą obok tego pliku."""
import json
import os
import socketserver
import threading

import snowflake.connector

HOME = os.path.dirname(os.path.abspath(__file__))
SOCK = os.path.join(HOME, "snowqd.sock")
LOG = os.path.join(HOME, "snowqd.log")

CONN_KW = dict(
    account=os.environ.get("SNOWQ_ACCOUNT", "rw35960-opendoor"),
    user=os.environ.get("SNOWQ_USER", "rafal.jaworski@opendoor.com"),
    authenticator="externalbrowser",
    client_session_keep_alive=True,
    client_store_temporary_credential=True,
)
for env_key, kw in [
    ("SNOWQ_WAREHOUSE", "warehouse"),
    ("SNOWQ_DATABASE", "database"),
    ("SNOWQ_SCHEMA", "schema"),
    ("SNOWQ_ROLE", "role"),
]:
    val = os.environ.get(env_key)
    if val:
        CONN_KW[kw] = val

_lock = threading.Lock()
_conn = None


def log(msg):
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def get_conn():
    global _conn
    if _conn is None:
        _conn = snowflake.connector.connect(**CONN_KW)
        log("connected")
    return _conn


def _jsonable(v):
    return v if isinstance(v, (int, float, bool, type(None))) else str(v)


def run_sql(sql):
    global _conn
    with _lock:
        for attempt in (1, 2):
            try:
                cur = get_conn().cursor()
                try:
                    cur.execute(sql)
                    cols = [c[0] for c in cur.description] if cur.description else []
                    rows = cur.fetchall() if cur.description else []
                    rows = [[_jsonable(v) for v in r] for r in rows]
                    return {"ok": True, "columns": cols, "rows": rows, "rowcount": cur.rowcount}
                finally:
                    cur.close()
            except snowflake.connector.errors.ProgrammingError as e:
                # Błąd SQL (kompilacja, zła kolumna) — NIE reconnectuj, zwróć od razu.
                return {"ok": False, "error": str(e)}
            except (
                snowflake.connector.errors.OperationalError,
                snowflake.connector.errors.InterfaceError,
            ) as e:
                # Błąd połączenia / wygasły token — odśwież raz (token z cache, bez popupu).
                if attempt == 1:
                    log(f"reconnect after: {e}")
                    try:
                        _conn.close()
                    except Exception:
                        pass
                    _conn = None
                    continue
                return {"ok": False, "error": str(e)}
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            req = json.loads(self.rfile.read().decode("utf-8"))
            res = run_sql(req["sql"])
        except Exception as e:
            res = {"ok": False, "error": f"bad request: {e}"}
        self.wfile.write(json.dumps(res).encode("utf-8"))


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main():
    if os.path.exists(SOCK):
        os.unlink(SOCK)
    log("starting — authenticating (externalbrowser)…")
    get_conn()  # popup TERAZ, raz; potem keep-alive + cache tokena
    srv = Server(SOCK, Handler)
    log(f"listening on {SOCK}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
