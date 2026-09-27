import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4
from fastapi.testclient import TestClient
from focusos_api.lifecycle import disconnect_google, delete_imported_source
from focusos_api.main import app

class FakeCall:
    def __init__(self, data): self.data=data
    def execute(self): return self
class FakeClient:
    def __init__(self, data): self.data=data; self.name=None; self.args=None
    def rpc(self, name, args=None): self.name=name; self.args=args; return FakeCall(self.data)

class LifecycleTests(unittest.TestCase):
    def test_disconnect_uses_owner_scoped_rpc(self):
        client=FakeClient({"disconnected":True})
        @contextmanager
        def scoped(_): yield "owner",client
        with patch("focusos_api.lifecycle.scoped_client",scoped):
            self.assertTrue(disconnect_google("session").disconnected)
        self.assertEqual(client.name,"focusos_disconnect_google")
        self.assertEqual(client.args,{})

    def test_delete_sends_only_selected_id(self):
        client=FakeClient({"deleted":True,"tasks_deleted":1,"command_runs_deleted":1})
        @contextmanager
        def scoped(_): yield "owner",client
        source=uuid4()
        with patch("focusos_api.lifecycle.scoped_client",scoped):
            self.assertTrue(delete_imported_source("session",source).deleted)
        self.assertEqual(client.args,{"p_source_id":str(source)})

    def test_anonymous_lifecycle_routes_are_denied(self):
        client=TestClient(app)
        self.assertEqual(client.delete("/connections/google").status_code,401)
        self.assertEqual(client.delete(f"/sources/{uuid4()}").status_code,401)

if __name__=='__main__': unittest.main()
