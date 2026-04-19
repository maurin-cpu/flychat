"""
InstantDB Admin API Client fuer Flychat.
Wrapper fuer die InstantDB HTTP Admin API mit Soft-Fail (Logging statt Exceptions)
und Retry-Logik (Exponential Backoff bei 429/5xx/Connection-Errors).
"""

import logging
import random
import time
import uuid
import requests

logger = logging.getLogger(__name__)

# Retry-Konfiguration: max 3 Versuche, Basis-Delay 1s, verdoppelt (1s, 2s, 4s).
# Gesamt-Worst-Case: 7s Wait + 3× Request-Timeout → OK fuer Daemon-Threads,
# nicht fuer Request-Handler blockierend einsetzbar.
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class InstantDBClient:
    """Wrapper fuer die InstantDB Admin HTTP API."""

    def __init__(self, app_id: str, admin_token: str, api_url: str = "https://api.instantdb.com"):
        self.app_id = app_id
        self.admin_token = admin_token
        self.api_url = api_url.rstrip("/")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.admin_token}",
            "App-Id": self.app_id,
            "Content-Type": "application/json",
        }

    @staticmethod
    def make_id(name: str) -> str:
        """Erzeugt eine deterministische UUID v5 aus einem Namen."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"flychat.{name}"))

    def _post_with_retry(self, url: str, payload: dict, timeout: int = 10, label: str = ""):
        """POST mit Exponential Backoff bei 429/5xx/Connection-Errors.

        Raises die letzte Exception bei finalem Fehlschlag. Respektiert Retry-After
        fuer 429. Bei 4xx (ausser 429) sofortiger Abbruch (kein Retry).
        """
        last_exc = None
        for attempt in range(_RETRY_MAX_ATTEMPTS):
            try:
                resp = requests.post(url, json=payload, headers=self._headers(), timeout=timeout)
                if resp.status_code in _RETRYABLE_STATUS:
                    # Retry-After beachten (nur bei 429)
                    retry_after = None
                    if resp.status_code == 429:
                        try:
                            retry_after = float(resp.headers.get("Retry-After", ""))
                        except (TypeError, ValueError):
                            retry_after = None
                    if attempt < _RETRY_MAX_ATTEMPTS - 1:
                        delay = retry_after if retry_after else (
                            _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.25)
                        )
                        logger.warning(
                            "InstantDB %s: HTTP %d — Retry %d/%d in %.1fs",
                            label, resp.status_code, attempt + 1, _RETRY_MAX_ATTEMPTS, delay,
                        )
                        time.sleep(delay)
                        continue
                resp.raise_for_status()
                return resp
            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < _RETRY_MAX_ATTEMPTS - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.25)
                    logger.warning(
                        "InstantDB %s: %s — Retry %d/%d in %.1fs",
                        label, type(e).__name__, attempt + 1, _RETRY_MAX_ATTEMPTS, delay,
                    )
                    time.sleep(delay)
                    continue
                raise
            except requests.HTTPError as e:
                # 4xx (ausser 429) → nicht retrybar
                raise
        if last_exc:
            raise last_exc

    def query(self, table_name: str, filters: dict | None = None) -> dict | None:
        """Fuehrt eine Query auf eine Tabelle aus. Gibt die Antwort-Daten zurueck oder None bei Fehler."""
        url = f"{self.api_url}/admin/query"
        payload = {"query": {table_name: filters or {}}}

        try:
            resp = self._post_with_retry(url, payload, timeout=10, label=f"query({table_name})")
            return resp.json()
        except Exception as e:
            logger.error(f"InstantDB query fehlgeschlagen ({table_name}): {e}")
            return None

    def upsert(self, table_name: str, doc_id: str, data: dict) -> bool:
        """Erstellt oder aktualisiert ein Dokument. Gibt True bei Erfolg zurueck."""
        url = f"{self.api_url}/admin/transact"
        payload = {
            "steps": [
                ["update", table_name, doc_id, data],
            ],
        }

        try:
            self._post_with_retry(url, payload, timeout=10, label=f"upsert({table_name})")
            logger.debug(f"InstantDB upsert OK: {table_name}/{doc_id}")
            return True
        except Exception as e:
            logger.error(f"InstantDB upsert fehlgeschlagen ({table_name}/{doc_id}): {e}")
            return False

    def delete(self, table_name: str, doc_id: str) -> bool:
        """Loescht ein Dokument. Gibt True bei Erfolg zurueck."""
        url = f"{self.api_url}/admin/transact"
        payload = {
            "steps": [
                ["delete", table_name, doc_id],
            ],
        }

        try:
            self._post_with_retry(url, payload, timeout=10, label=f"delete({table_name})")
            logger.debug(f"InstantDB delete OK: {table_name}/{doc_id}")
            return True
        except Exception as e:
            logger.error(f"InstantDB delete fehlgeschlagen ({table_name}/{doc_id}): {e}")
            return False

    def delete_all(self, table_name: str) -> bool:
        """Loescht alle Records einer Tabelle. Query + Batch-Delete."""
        data = self.query(table_name)
        if data is None:
            return False

        records = data.get(table_name, [])
        if not records:
            logger.debug(f"InstantDB delete_all: {table_name} ist bereits leer")
            return True

        ids = [r["id"] for r in records if "id" in r]
        if not ids:
            return True

        url = f"{self.api_url}/admin/transact"
        steps = [["delete", table_name, doc_id] for doc_id in ids]
        payload = {"steps": steps}

        try:
            self._post_with_retry(url, payload, timeout=15, label=f"delete_all({table_name})")
            logger.info(f"InstantDB delete_all OK: {table_name} ({len(ids)} records geloescht)")
            return True
        except Exception as e:
            logger.error(f"InstantDB delete_all fehlgeschlagen ({table_name}): {e}")
            return False

    def batch_upsert(self, table_name: str, docs: dict[str, dict], chunk_size: int = 500) -> bool:
        """Erstellt/aktualisiert mehrere Dokumente. Splittet in Chunks, da InstantDB transact
        ein Payload-Size-Limit (~1 MB) hat. Bei 486 Spots × 5 Tagen = 2430 Docs (~2 MB)
        muss gechunkt werden, sonst 400 Bad Request."""
        url = f"{self.api_url}/admin/transact"
        items = list(docs.items())
        if not items:
            return True

        total = len(items)
        n_chunks = (total + chunk_size - 1) // chunk_size
        for i in range(0, total, chunk_size):
            chunk = items[i:i + chunk_size]
            steps = [["update", table_name, doc_id, data] for doc_id, data in chunk]
            payload = {"steps": steps}
            try:
                self._post_with_retry(
                    url, payload, timeout=30,
                    label=f"batch_upsert({table_name}, chunk {i//chunk_size + 1}/{n_chunks})",
                )
            except requests.HTTPError as e:
                body = ""
                try:
                    body = e.response.text[:500] if e.response is not None else ""
                except Exception:
                    pass
                logger.error(
                    f"InstantDB batch_upsert fehlgeschlagen ({table_name}, chunk {i//chunk_size + 1}/{n_chunks}, {len(chunk)} docs): {e} | Body: {body}"
                )
                return False
            except Exception as e:
                logger.error(
                    f"InstantDB batch_upsert fehlgeschlagen ({table_name}, chunk {i//chunk_size + 1}/{n_chunks}): {e}"
                )
                return False

        logger.debug(f"InstantDB batch_upsert OK: {table_name} ({total} docs in {n_chunks} chunk(s))")
        return True
