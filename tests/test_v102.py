"""0.10.2 - pod gunicornem (Render, wczytanie aplikacji w procesie głównym) piłka nie dotyka bazy przed fork().

Błąd: load_local + wątek odświeżania startowały przy wczytaniu aplikacji, czyli w procesie głównym. Fork w trakcie
zapisu kopiował do procesu stron stan blokad SQLite i KAŻDY późniejszy zapis kończył się „database is locked”."""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fbpred import bootstrap, config, picks


@unittest.skipUnless(hasattr(os, "fork"), "fork tylko na Linuksie (Render)")
class TestNoDbBeforeFork(unittest.TestCase):
    def setUp(self):
        self._old = (config.DB_PATH, config.GITHUB_TOKEN, config.AUTO_BOOTSTRAP, sys.argv[0], bootstrap._bg_pid)
        config.DB_PATH = Path(tempfile.mkdtemp()) / "fork.db"
        config.GITHUB_TOKEN, config.AUTO_BOOTSTRAP = "", False
        sys.argv[0] = "/opt/render/project/src/.venv/bin/gunicorn"
        bootstrap._bg_pid = None

    def tearDown(self):
        config.DB_PATH, config.GITHUB_TOKEN, config.AUTO_BOOTSTRAP, sys.argv[0], bootstrap._bg_pid = self._old

    def test_master_does_not_touch_db_and_child_can_write(self):
        self.assertTrue(bootstrap.under_preloading_server())
        from fbpred.web import create_app
        threads = {t.name for t in threading.enumerate()}
        app = create_app()                                                       # „proces główny gunicorna”
        self.assertFalse(Path(config.DB_PATH).exists(), "proces główny otworzył bazę przed fork()")
        self.assertEqual({t.name for t in threading.enumerate()} - threads, set(), "proces główny uruchomił wątek")
        pid = os.fork()
        if pid == 0:                                                             # „proces stron”
            code = 1
            try:
                app.test_client().get("/healthz")                                # pierwsze zapytanie startuje pracę na bazie
                for _ in range(300):
                    if not any(t.name == "fbpred-start" for t in threading.enumerate()):
                        break
                    time.sleep(0.2)
                ok_pid = bootstrap._bg_pid == os.getpid()
                conn = sqlite3.connect(config.DB_PATH, timeout=3)
                picks.ensure(conn)
                picks.add(conn, "E0~2099-01-01~A~B~1", "1", 0.5)                  # zapis typu jak z kafelka
                code = 0 if ok_pid and len(picks.legs(conn)) == 1 else 2
            except Exception as e:  # noqa: BLE001
                print("dziecko:", e, flush=True)
            os._exit(code)
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_single_process_starts_eagerly(self):
        sys.argv[0] = "waitress"
        self.assertFalse(bootstrap.under_preloading_server())
        self.assertTrue(bootstrap.ensure_background(False, eager=True))
        self.assertTrue(Path(config.DB_PATH).exists())
        self.assertFalse(bootstrap.ensure_background(False))                     # leniwie w tym samym procesie - już było


if __name__ == "__main__":
    unittest.main()
