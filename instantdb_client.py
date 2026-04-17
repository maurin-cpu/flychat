"""
InstantDB Admin API Client fuer Flychat.
Wrapper fuer die InstantDB HTTP Admin API mit Soft-Fail (Logging statt Exceptions).
"""

import logging
import uuid
import requests

logger = logging.getLogger(__name__)


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

    def query(self, table_name: str, filters: dict | None = None) -> dict | None:
        """Fuehrt eine Query auf eine Tabelle aus. Gibt die Antwort-Daten zurueck oder None bei Fehler."""
        url = f"{self.api_url}/admin/query"
        payload = {"query": {table_name: filters or {}}}

        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
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
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
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
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
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
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=15)
            resp.raise_for_status()
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
                resp = requests.post(url, json=payload, headers=self._headers(), timeout=30)
                resp.raise_for_status()
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
