import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from focusos_api.gmail_fetch import fetch_selected_messages
from focusos_api.gmail_selection import GmailSelectionError
from focusos_api.main import app

class Response:
    headers={}
    def __init__(self,data,status=200):
        self.data=data; self.status_code=status; self.content=b"{}"
    def json(self): return self.data

class Client:
    def __init__(self,selected=True): self.calls=[]; self.selected=selected
    def get(self,url,*,params,headers,timeout):
        self.calls.append((url,params))
        if url.endswith("/labels"): return Response({"labels":[{"name":"FocusOS","type":"user","id":"Label_1"}]})
        if not self.selected: return Response({"id":"msg_1","threadId":"thr_1","labelIds":["INBOX"],
            "payload":{"headers":[]}})
        if params == {"format":"full"}:
            return Response({"id":"msg_1","threadId":"thr_1","labelIds":["Label_1"],
                "payload":{"mimeType":"text/plain","body":{"data":"U2VjcmV0"}}})
        return Response({"id":"msg_1","threadId":"thr_1","labelIds":["Label_1"],
            "payload":{"headers":[]}})

class SelectedFetchTests(unittest.TestCase):
    def test_checks_label_before_full_and_never_returns_body_from_route(self):
        client=Client()
        with patch("focusos_api.gmail_fetch.google_bearer",return_value=(object(),"token")):
            result=fetch_selected_messages("user",["msg_1"],http_client=client)
        self.assertEqual(result[0].status,"available")
        self.assertEqual(client.calls[1][1][0],("format","metadata"))
        self.assertEqual(client.calls[2][1],{"format":"full"})

    def test_unselected_id_does_not_fetch_body(self):
        client=Client(selected=False)
        with patch("focusos_api.gmail_fetch.google_bearer",return_value=(object(),"token")):
            with self.assertRaises(GmailSelectionError):
                fetch_selected_messages("user",["msg_1"],http_client=client)
        self.assertEqual(len(client.calls),2)

    def test_invalid_ids_rejected_before_google(self):
        with patch("focusos_api.gmail_fetch.google_bearer") as bearer:
            with self.assertRaises(GmailSelectionError):
                fetch_selected_messages("user",["../bad"])
        bearer.assert_not_called()

    def test_anonymous_route(self):
        response=TestClient(app).post("/connections/google/gmail/selected/fetch",json={"ids":["msg_1"]})
        self.assertEqual(response.status_code,401)

if __name__=="__main__": unittest.main()
