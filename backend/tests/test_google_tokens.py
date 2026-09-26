import threading
import unittest
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx

from focusos_api.google_tokens import (
    GoogleOAuthClient,
    GoogleReconnectRequired,
    GoogleRefreshInProgress,
    StoredGoogleCredentials,
    get_google_access_token,
)
from focusos_api.token_crypto import TokenCipher


CONNECTION_ID = UUID("a4e0ce3a-c955-4b30-9d67-f47859cd38af")
NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, cipher, *, expired=True):
        self.cipher = cipher
        self.lock = threading.Lock()
        self.lease_id = None
        self.saved = 0
        self.reconnect = False
        expiry = NOW - timedelta(seconds=1) if expired else NOW + timedelta(hours=1)
        self.row = StoredGoogleCredentials(
            connection_id=CONNECTION_ID,
            encrypted_refresh_token=cipher.encrypt(CONNECTION_ID, "refresh", "refresh-secret").ciphertext,
            encrypted_access_token=cipher.encrypt(CONNECTION_ID, "access", "old-access").ciphertext,
            access_token_expires_at=expiry,
            encryption_key_version=1,
            token_version=3,
        )

    def read(self, _connection_id):
        return self.row

    def claim(self, _connection_id, expected_version, lease_id, _lease_seconds):
        with self.lock:
            if self.lease_id is not None or self.row.token_version != expected_version:
                return None
            self.lease_id = lease_id
            return self.row

    def save(self, _connection_id, expected_version, lease_id, access, refresh, expires_at, key_version):
        with self.lock:
            if self.lease_id != lease_id or self.row.token_version != expected_version:
                return False
            self.row = self.row.model_copy(update={
                "encrypted_access_token": access,
                "encrypted_refresh_token": refresh,
                "access_token_expires_at": expires_at,
                "encryption_key_version": key_version,
                "token_version": expected_version + 1,
            })
            self.saved += 1
            self.lease_id = None
            return True

    def mark_reconnect_required(self, _connection_id, lease_id):
        self.reconnect = True
        self.lease_id = None

    def release(self, _connection_id, lease_id):
        with self.lock:
            if self.lease_id == lease_id:
                self.lease_id = None


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def json(self):
        return self.body


class FakeHttp:
    def __init__(self, response, *, entered=None, release=None):
        self.response = response
        self.calls = 0
        self.entered = entered
        self.release = release

    def post(self, _url, *, data, timeout):
        self.calls += 1
        self.data = data
        self.timeout = timeout
        if self.entered:
            self.entered.set()
        if self.release:
            self.release.wait(timeout=3)
        return self.response


class GoogleTokenRefreshTests(unittest.TestCase):
    def setUp(self):
        self.cipher = TokenCipher({1: b"x" * 32}, 1)
        self.oauth = GoogleOAuthClient("client-id", "client-secret")

    def test_unexpired_access_token_is_reused_without_network(self):
        store = FakeStore(self.cipher, expired=False)
        client = FakeHttp(FakeResponse({}))
        token = get_google_access_token(CONNECTION_ID, store, self.cipher, self.oauth, http_client=client, now=NOW)
        self.assertEqual(token, "old-access")
        self.assertEqual(client.calls, 0)
        self.assertEqual(store.saved, 0)

    def test_expired_token_refreshes_once_and_preserves_missing_refresh_token(self):
        store = FakeStore(self.cipher)
        client = FakeHttp(FakeResponse({"access_token": "new-access", "expires_in": 3600}))
        token = get_google_access_token(CONNECTION_ID, store, self.cipher, self.oauth, http_client=client, now=NOW)
        self.assertEqual(token, "new-access")
        self.assertEqual(client.calls, 1)
        self.assertEqual(store.saved, 1)
        self.assertEqual(store.row.token_version, 4)
        self.assertEqual(
            self.cipher.decrypt(CONNECTION_ID, "refresh", store.row.encrypted_refresh_token, 1),
            "refresh-secret",
        )
        self.assertEqual(client.data["grant_type"], "refresh_token")

    def test_invalid_grant_requires_reconnect_without_leaking_provider_body(self):
        store = FakeStore(self.cipher)
        client = FakeHttp(FakeResponse({"error": "invalid_grant", "error_description": "private"} , 400))
        with self.assertRaises(GoogleReconnectRequired):
            get_google_access_token(CONNECTION_ID, store, self.cipher, self.oauth, http_client=client, now=NOW)
        self.assertTrue(store.reconnect)
        self.assertIsNone(store.lease_id)

    def test_competing_refresh_calls_only_make_one_provider_request(self):
        store = FakeStore(self.cipher)
        entered, release = threading.Event(), threading.Event()
        client = FakeHttp(FakeResponse({"access_token": "new-access", "expires_in": 3600}), entered=entered, release=release)
        result = []

        def first():
            result.append(get_google_access_token(CONNECTION_ID, store, self.cipher, self.oauth, http_client=client, now=NOW))

        worker = threading.Thread(target=first)
        worker.start()
        self.assertTrue(entered.wait(timeout=2))
        with self.assertRaises(GoogleRefreshInProgress):
            get_google_access_token(CONNECTION_ID, store, self.cipher, self.oauth, http_client=client, now=NOW)
        release.set()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, ["new-access"])
        self.assertEqual(client.calls, 1)
        self.assertEqual(store.saved, 1)


if __name__ == "__main__":
    unittest.main()
