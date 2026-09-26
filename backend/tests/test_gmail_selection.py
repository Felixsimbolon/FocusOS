import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from focusos_api.gmail_selection import list_selected_metadata, GmailSelectionMissing
from focusos_api.main import app

class Response:
    status_code = 200
    headers = {}
    content = b"{}"
    def __init__(self, data): self.data=data
    def json(self): return self.data

class FakeClient:
    def __init__(self): self.calls=[]
    def get(self,url,*,params,headers,timeout):
        self.calls.append((url,params,headers))
        if url.endswith("/labels"):
            return Response({"labels":[{"name":"Other","id":"Label_0","type":"user"},
                                       {"name":"FocusOS","id":"Label_1","type":"user"}]})
        if url.endswith("/messages"):
            return Response({"messages":[{"id":"msg_1","threadId":"thr_1"}],
                             "nextPageToken":"abc_2","resultSizeEstimate":1})
        return Response({"id":"msg_1","threadId":"thr_1","historyId":"55",
                         "internalDate":"1799990000000","labelIds":["Label_1"],
                         "snippet":"PRIVATE CONTENT","payload":{"headers":[
                             {"name":"Subject","value":"Finish slides"},
                             {"name":"From","value":"Sender <sender@example.test>"}]}})

class GmailMetadataTests(unittest.TestCase):
    def test_selected_label_only_and_metadata_without_body(self):
        client=FakeClient()
        with patch("focusos_api.gmail_selection.google_bearer",return_value=(object(),"secret-token")):
            page=list_selected_metadata("user-token",http_client=client)
        self.assertEqual(page.items[0].subject,"Finish slides")
        self.assertEqual(page.next_page_token,"abc_2")
        self.assertEqual(client.calls[1][1]["labelIds"],"Label_1")
        self.assertEqual(client.calls[1][1]["maxResults"],10)
        self.assertEqual(client.calls[2][1][0],("format","metadata"))
        self.assertNotIn("PRIVATE CONTENT",page.model_dump_json())
        self.assertNotIn("secret-token",page.model_dump_json())

    def test_missing_label_fails_closed(self):
        client=FakeClient()
        original=client.get
        def no_label(url,*,params,headers,timeout):
            if url.endswith("/labels"): return Response({"labels":[]})
            return original(url,params=params,headers=headers,timeout=timeout)
        client.get=no_label
        with patch("focusos_api.gmail_selection.google_bearer",return_value=(object(),"token")):
            with self.assertRaises(GmailSelectionMissing):
                list_selected_metadata("user-token",http_client=client)

    def test_anonymous_route(self):
        self.assertEqual(TestClient(app).get("/connections/google/gmail/selected").status_code,401)

if __name__=="__main__": unittest.main()
