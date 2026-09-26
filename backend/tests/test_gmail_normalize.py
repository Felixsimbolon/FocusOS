import base64
import unittest
from focusos_api.gmail_normalize import normalize_gmail_message, GmailNormalizationError

def enc(text,charset="utf-8"): return base64.urlsafe_b64encode(text.encode(charset)).decode().rstrip("=")
def msg(part):
    return {"id":"msg_1","threadId":"thr_1","historyId":"123","internalDate":"1799990000000",
      "labelIds":["Label_1"],"payload":{"mimeType":"multipart/mixed",
        "headers":[{"name":"Subject","value":"Schedule &amp; slides"},{"name":"From","value":"A <a@example.test>"}],
        "parts":[part]}}

class NormalizationTests(unittest.TestCase):
    def test_unicode_plain_and_quoted_reply(self):
        data=msg({"mimeType":"text/plain","headers":[{"name":"Content-Type","value":"text/plain; charset=iso-8859-1"}],
          "body":{"data":enc("Préseñtación\nOn Monday wrote:\n> old private text","iso-8859-1")}})
        result=normalize_gmail_message(data)
        self.assertEqual(result.normalized_body,"Préseñtación")
        self.assertEqual(result.title,"Schedule & slides")
        self.assertEqual(result.history_id,"123")

    def test_nested_html_drops_scripts_images_and_links(self):
        data=msg({"mimeType":"multipart/alternative","parts":[
          {"mimeType":"text/html","body":{"data":enc("<p>Finish <b>slides</b></p><script>steal()</script><img src='https://evil.test/x'>")}}]})
        body=normalize_gmail_message(data).normalized_body
        self.assertIn("Finish slides",body)
        self.assertNotIn("steal",body)
        self.assertNotIn("evil.test",body)

    def test_attachment_only_is_nonactionable(self):
        data=msg({"mimeType":"application/pdf","filename":"secret.pdf",
          "body":{"attachmentId":"ATT_1","size":100}})
        result=normalize_gmail_message(data)
        self.assertTrue(result.has_attachments)
        self.assertIsNone(result.normalized_body)

    def test_long_body_caps_utf8(self):
        data=msg({"mimeType":"text/plain","body":{"data":enc("é"*15000)}})
        result=normalize_gmail_message(data)
        self.assertTrue(result.body_truncated)
        self.assertLessEqual(len(result.normalized_body.encode("utf-8")),20480)

    def test_invalid_encoding_rejected(self):
        data=msg({"mimeType":"text/plain","body":{"data":"%%%"}})
        with self.assertRaises(GmailNormalizationError):
            normalize_gmail_message(data)

if __name__=="__main__": unittest.main()
