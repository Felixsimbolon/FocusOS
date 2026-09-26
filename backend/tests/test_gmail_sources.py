import unittest
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

from focusos_api.gmail_fetch import RawSelectedMessage
from focusos_api.gmail_sources import upsert_gmail_source
from focusos_api.main import app

class UpsertTests(unittest.TestCase):
    def test_unavailable_message_never_touches_database(self):
        with patch("focusos_api.gmail_sources.scoped_client") as client:
            result=upsert_gmail_source("user",uuid4(),RawSelectedMessage("msg_1","unavailable",None,"Label_1"))
        self.assertEqual(result.status,"unavailable")
        client.assert_not_called()

    def test_upsert_uses_provider_identity_and_bounded_text(self):
        connection=uuid4()
        source_id=uuid4()
        message={"id":"msg_1","threadId":"thr_1","historyId":"44","internalDate":"1799990000000",
            "labelIds":["Label_1"],"payload":{"mimeType":"text/plain",
                "headers":[{"name":"Subject","value":"Finish slides"}],
                "body":{"data":"RmluaXNoIHNsaWRlcw"}}}
        calls=[]
        @contextmanager
        def client(_):
            class DB:
                def rpc(self,name,args):
                    calls.append((name,args))
                    if name=="focusos_upsert_gmail_source":
                        return Mock(execute=lambda:Mock(data={"outcome":"saved","created":True,"changed":False,
                            "source":{"id":str(source_id),"kind":"gmail","title":"Finish slides",
                              "source_ref":"gmail:"+str(source_id),"normalized_body":"Finish slides",
                              "body_hash":"0"*64,"normalization_version":"1","body_truncated":False,
                              "received_at":"2027-01-15T00:00:00+00:00",
                              "created_at":"2027-01-15T00:00:00+00:00",
                              "body_expires_at":"2027-02-15T00:00:00+00:00"}}))
                    return Mock(execute=lambda:Mock(data=0))
            yield ("owner",DB())
        with patch("focusos_api.gmail_sources.scoped_client",client):
            result=upsert_gmail_source("user",connection,RawSelectedMessage("msg_1","available",message,"Label_1"))
        self.assertTrue(result.created)
        self.assertEqual(result.source.kind,"gmail")
        params=calls[1][1]
        self.assertEqual(params["p_connection_id"],str(connection))
        self.assertEqual(params["p_message_id"],"msg_1")
        self.assertEqual(params["p_label_id"],"Label_1")
        self.assertEqual(params["p_body"],"Finish slides")

    def test_anonymous_ingest_denied(self):
        response=TestClient(app).post("/connections/google/gmail/selected/ingest",json={"ids":["msg_1"]})
        self.assertEqual(response.status_code,401)

if __name__=="__main__": unittest.main()
