from contextlib import contextmanager
import json
import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
from focusos_api.main import app
from focusos_api import product
from focusos_api.calendar_cancel import delete_owned_event
from focusos_api.calendar_write import CalendarWriteConflict

class ProductTests(unittest.TestCase):
 def test_all_product_endpoints_require_auth(self):
  client=TestClient(app)
  for path in ("diagnostics","history","export","focus-blocks"):
   self.assertEqual(client.get("/product/"+path).status_code,401)
  self.assertEqual(client.post(f"/product/focus-blocks/{uuid4()}/cancel").status_code,401)
 def test_exports_select_only_explicit_safe_fields_and_owner(self):
  query=MagicMock();query.select.return_value=query;query.eq.return_value=query;query.limit.return_value=query;query.order.return_value=query;query.execute.return_value.data=[{"id":"owned"}]
  client=MagicMock();client.table.return_value=query
  @contextmanager
  def scoped(_):yield "owner",client
  with patch.object(product,"scoped_client",scoped): result=product.export_data("private-session")
  self.assertEqual(result["schema_version"],1)
  self.assertEqual(query.eq.call_args_list[0].args,("id","owner"))
  for call in query.eq.call_args_list[1:]: self.assertEqual(call.args,("user_id","owner"))
  for fields in product.EXPORT_FIELDS.values():
   for forbidden in ("ciphertext","refresh_token","access_token","embedding,","lease_token","checkpoint","service_role"):
    self.assertNotIn(forbidden,fields)
  self.assertNotIn("private-session",json.dumps(result))
 def test_export_marks_truncation_instead_of_claiming_full_backup(self):
  query=MagicMock();query.select.return_value=query;query.eq.return_value=query;query.limit.return_value=query;query.order.return_value=query;query.execute.return_value.data=[{"id":str(i)} for i in range(1001)]
  client=MagicMock();client.table.return_value=query
  @contextmanager
  def scoped(_):yield "owner",client
  with patch.object(product,"scoped_client",scoped):result=product.export_data("token")
  self.assertTrue(all(result["truncated"].values()));self.assertEqual(len(result["tables"]["tasks"]),1000)
 def test_diagnostics_report_presence_not_values_or_provider_success(self):
  client=MagicMock()
  @contextmanager
  def scoped(_):yield "owner",client
  with patch.object(product,"scoped_client",scoped),patch.dict(os.environ,{"GEMINI_API_KEY":"private-gemini-key","FOCUSOS_WORKER_SECRET":"secret"*8}),patch.object(product.TokenCipher,"from_environment"):
   result=product.diagnostics("private-session")
  self.assertTrue(result["configured"]["GEMINI_API_KEY"]);self.assertFalse(result["provider_live_tested"])
  self.assertNotIn("private-gemini-key",json.dumps(result));self.assertNotIn("private-session",json.dumps(result))
 def test_missing_migrations_are_visible(self):
  client=MagicMock();client.table.side_effect=[MagicMock(),RuntimeError(),RuntimeError()]
  @contextmanager
  def scoped(_):yield "owner",client
  with patch.object(product,"scoped_client",scoped),patch.object(product.TokenCipher,"from_environment"):
   result=product.diagnostics("token")
  self.assertFalse(result["queue_ready"]);self.assertFalse(result["lifecycle_ready"])

class CancellationTests(unittest.TestCase):
 def setUp(self):
  self.approval=MagicMock(status="succeeded",calendar_id="primary",event_id="focusos123")
  self.event={"id":"focusos123","etag":"\"v1\"","status":"confirmed"}
 def adapter(self,handler):return httpx.Client(transport=httpx.MockTransport(handler))
 def test_marker_and_etag_checked_before_delete(self):
  calls=[]
  def handler(request):
   calls.append(request)
   if request.method=="GET":return httpx.Response(200,json=self.event)
   self.assertEqual(request.headers["If-Match"],self.event["etag"]);self.assertEqual(request.url.params["sendUpdates"],"none")
   return httpx.Response(204)
  with self.adapter(handler) as client,patch("focusos_api.calendar_cancel._verify_event") as verify:
   self.assertEqual(delete_owned_event(self.approval,"bearer",client=client),"cancelled");verify.assert_called_once()
  self.assertEqual([r.method for r in calls],["GET","DELETE"])
 def test_changed_event_never_deleted(self):
  calls=[]
  def handler(r):calls.append(r.method);return httpx.Response(200,json=self.event)
  with self.adapter(handler) as client,patch("focusos_api.calendar_cancel._verify_event",side_effect=CalendarWriteConflict()):
   self.assertEqual(delete_owned_event(self.approval,"bearer",client=client),"changed")
  self.assertEqual(calls,["GET"])
 def test_racing_edit_returns_changed_on_412(self):
  with self.adapter(lambda r:httpx.Response(200,json=self.event) if r.method=="GET" else httpx.Response(412)) as client,patch("focusos_api.calendar_cancel._verify_event"):
   self.assertEqual(delete_owned_event(self.approval,"bearer",client=client),"changed")
 def test_lost_delete_response_is_unknown_then_absent_event_reconciles(self):
  def handler(r):
   if r.method=="GET":return httpx.Response(200,json=self.event)
   raise httpx.ReadTimeout("response lost",request=r)
  with self.adapter(handler) as client,patch("focusos_api.calendar_cancel._verify_event"):
   self.assertEqual(delete_owned_event(self.approval,"bearer",client=client),"unknown")
  with self.adapter(lambda r:httpx.Response(404)) as client:
   self.assertEqual(delete_owned_event(self.approval,"bearer",client=client),"cancelled")
 def test_missing_etag_denies_delete(self):
  self.event.pop("etag");methods=[]
  def handler(r):methods.append(r.method);return httpx.Response(200,json=self.event)
  with self.adapter(handler) as client,patch("focusos_api.calendar_cancel._verify_event"):
   self.assertEqual(delete_owned_event(self.approval,"bearer",client=client),"unknown")
  self.assertEqual(methods,["GET"])
