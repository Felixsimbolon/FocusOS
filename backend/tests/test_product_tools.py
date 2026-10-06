import unittest
from unittest.mock import patch,MagicMock
from scripts.validate_export import validate_export,TABLES
from scripts.work_jobs import drain

class ProductToolsTests(unittest.TestCase):
 def fixture(self):return {"schema_version":1,"tables":{t:[] for t in TABLES},"truncated":{t:False for t in TABLES}}
 def test_export_validator_accepts_complete_versioned_snapshot(self):
  self.assertEqual(validate_export(self.fixture()),{t:0 for t in TABLES})
 def test_export_validator_rejects_credentials_and_truncated_data(self):
  data=self.fixture();data["tables"]["tasks"]=[{"access_token":"private"}]
  with self.assertRaises(ValueError):validate_export(data)
  data=self.fixture();data["truncated"]["tasks"]=True
  with self.assertRaises(ValueError):validate_export(data)
 def test_export_validator_rejects_incomplete_or_unsupported_formats(self):
  for data in ({},{"schema_version":2},[] , {**self.fixture(),"tables":{}}):
   with self.assertRaises(ValueError):validate_export(data)
 def test_worker_secret_never_sent_to_insecure_remote_url(self):
  with patch("scripts.work_jobs.httpx.Client") as client:
   with self.assertRaises(ValueError):drain("http://remote.example.test","x"*32)
   client.assert_not_called()
 def test_worker_drain_stops_when_no_jobs_are_ready(self):
  client=MagicMock();client.post.return_value.status_code=200;client.post.return_value.json.return_value={"state":"idle"}
  with patch("scripts.work_jobs.httpx.Client") as transport:
   transport.return_value.__enter__.return_value=client
   self.assertEqual(drain("https://api.example.test","x"*32),0)
   self.assertEqual(client.post.call_count,1)
