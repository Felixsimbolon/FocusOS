import unittest
from uuid import uuid4
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient

from focusos_api.gmail_sync import run_one_sync_page, _initial_page
from focusos_api.gmail_fetch import RawSelectedMessage
from focusos_api.gmail_selection import GmailSelectionError
from focusos_api.main import app

class InitialSyncTests(unittest.TestCase):
    def test_checkpoint_after_upsert_only(self):
        connection=Mock(id=uuid4())
        calls=[]
        def upsert(*args):
            calls.append("upsert")
            return Mock(status="saved")
        def finish(*args,**kwargs):
            calls.append("checkpoint")
        with patch("focusos_api.gmail_sync.google_bearer",return_value=(connection,"token")),              patch("focusos_api.gmail_sync.selected_label_id",return_value="Label_1"),              patch("focusos_api.gmail_sync._history_anchor",return_value="100"),              patch("focusos_api.gmail_sync._claim",return_value={"state":"claimed","lease_token":str(uuid4()),"mode":"initial","initial_page_token":None}),              patch("focusos_api.gmail_sync._initial_page",return_value=(["msg_1"],"next_2")),              patch("focusos_api.gmail_sync.fetch_selected_with_bearer",return_value=[RawSelectedMessage("msg_1","available",{"id":"msg_1"},"Label_1")]),              patch("focusos_api.gmail_sync.upsert_gmail_source",side_effect=upsert),              patch("focusos_api.gmail_sync._finish",side_effect=finish):
            result=run_one_sync_page("user",http_client=Mock())
        self.assertEqual(result.state,"partial")
        self.assertEqual(calls,["upsert","checkpoint"])

    def test_invalid_provider_page_does_not_advance(self):
        with patch("focusos_api.gmail_sync.provider_json",return_value={"messages":[{"id":"../bad"}]}):
            with self.assertRaises(GmailSelectionError):
                _initial_page(Mock(),"token","Label_1",None)

    def test_anonymous_route(self):
        self.assertEqual(TestClient(app).post("/connections/google/gmail/sync").status_code,401)

if __name__=="__main__": unittest.main()
