import unittest
from uuid import uuid4
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient

from focusos_api.gmail_sync import run_one_sync_page, _initial_page, _history_ids
from focusos_api.gmail_fetch import RawSelectedMessage
from focusos_api.gmail_selection import GmailSelectionError, GmailMessageGone, GmailSelectionUnavailable
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


    def test_history_uses_added_and_labeled_ids_once(self):
        data={"historyId":"130","nextPageToken":"page_2","history":[
          {"messagesAdded":[{"message":{"id":"msg_1"}}]},
          {"labelsAdded":[{"labelIds":["Label_1"],"message":{"id":"msg_1"}},
                          {"labelIds":["Label_1"],"message":{"id":"msg_2"}},
                          {"labelIds":["Other"],"message":{"id":"skip"}}]}]}
        ids, token, history = _history_ids(data,"Label_1")
        self.assertEqual(ids,["msg_1","msg_2"])
        self.assertEqual((token,history),("page_2","130"))

    def test_history_stages_before_fetching_bodies(self):
        connection=Mock(id=uuid4())
        finished=[]
        claim={"state":"claimed","mode":"history","history_id":"100",
               "history_page_token":None,"pending_ids":[],"lease_token":str(uuid4())}
        with patch("focusos_api.gmail_sync.google_bearer",return_value=(connection,"token")),              patch("focusos_api.gmail_sync.selected_label_id",return_value="Label_1"),              patch("focusos_api.gmail_sync._history_anchor",return_value="120"),              patch("focusos_api.gmail_sync._claim",return_value=claim),              patch("focusos_api.gmail_sync.provider_json",return_value={
               "historyId":"130","history":[{"messagesAdded":[{"message":{"id":"msg_1"}}]}]}),              patch("focusos_api.gmail_sync.fetch_selected_with_bearer") as fetch,              patch("focusos_api.gmail_sync._finish",side_effect=lambda *a,**kw:finished.append((a,kw))):
            result=run_one_sync_page("user",http_client=Mock())
        self.assertEqual(result.state,"partial")
        self.assertEqual(finished[0][0][3],"history_staged")
        self.assertEqual(finished[0][1]["pending_ids"],["msg_1"])
        fetch.assert_not_called()

    def test_expired_history_resets_initial_scan(self):
        connection=Mock(id=uuid4())
        claim={"state":"claimed","mode":"history","history_id":"100",
               "pending_ids":[],"lease_token":str(uuid4())}
        finished=[]
        with patch("focusos_api.gmail_sync.google_bearer",return_value=(connection,"token")),              patch("focusos_api.gmail_sync.selected_label_id",return_value="Label_1"),              patch("focusos_api.gmail_sync._history_anchor",return_value="200"),              patch("focusos_api.gmail_sync._claim",return_value=claim),              patch("focusos_api.gmail_sync.provider_json",side_effect=GmailMessageGone()),              patch("focusos_api.gmail_sync._finish",side_effect=lambda *a,**kw:finished.append((a,kw))):
            result=run_one_sync_page("user",http_client=Mock())
        self.assertEqual(result.state,"rescan_required")
        self.assertEqual(finished[0][0][3],"rescan")
        self.assertEqual(finished[0][1]["history_id"],"200")

    def test_rate_limit_keeps_checkpoint_and_sets_retry(self):
        connection=Mock(id=uuid4())
        claim={"state":"claimed","mode":"initial","lease_token":str(uuid4()),"initial_page_token":None}
        finished=[]
        with patch("focusos_api.gmail_sync.google_bearer",return_value=(connection,"token")),              patch("focusos_api.gmail_sync.selected_label_id",return_value="Label_1"),              patch("focusos_api.gmail_sync._history_anchor",return_value="100"),              patch("focusos_api.gmail_sync._claim",return_value=claim),              patch("focusos_api.gmail_sync._initial_page",side_effect=GmailSelectionUnavailable(120)),              patch("focusos_api.gmail_sync._finish",side_effect=lambda *a,**kw:finished.append((a,kw))):
            result=run_one_sync_page("user",http_client=Mock())
        self.assertEqual(result.state,"retry_wait")
        self.assertEqual(finished[0][0][3],"retry")
        self.assertEqual(finished[0][1]["retry_seconds"],120)

    def test_anonymous_route(self):
        self.assertEqual(TestClient(app).post("/connections/google/gmail/sync").status_code,401)

if __name__=="__main__": unittest.main()
