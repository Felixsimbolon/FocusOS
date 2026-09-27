import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pydantic import ValidationError
from focusos_api.approval_payload import CalendarAction, canonical_action_hash

class ApprovalPayloadTests(unittest.TestCase):
    def action(self):
        start=datetime(2026,9,28,10,tzinfo=timezone.utc)
        return CalendarAction(run_id=uuid4(),block_index=0,task_id=uuid4(),task_version=1,
            connection_id=uuid4(),event_id="f"+uuid4().hex,title="Write report",start=start,
            end=start+timedelta(hours=1),timezone="UTC")
    def test_hash_binds_exact_payload_and_ignores_serialization_order(self):
        action=self.action()
        self.assertEqual(canonical_action_hash(action),canonical_action_hash(CalendarAction.model_validate(action.model_dump())))
        self.assertNotEqual(canonical_action_hash(action),canonical_action_hash(action.model_copy(update={"title":"Other"})))
    def test_no_guest_or_arbitrary_calendar_or_approved_flag(self):
        action=self.action().model_dump()
        for altered in ({"guests":["x@example.com"]},{"calendar_id":"other"},{"approved":True}):
            with self.assertRaises(ValidationError): CalendarAction.model_validate({**action,**altered})
