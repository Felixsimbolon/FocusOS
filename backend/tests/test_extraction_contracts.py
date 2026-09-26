import unittest
from datetime import datetime

from pydantic import ValidationError
from focusos_api.extraction_contracts import ExtractionEnvelope, validate_grounding

REF = datetime.fromisoformat("2026-09-21T09:00:00+07:00")
BODY = "The final presentation is Friday September 25. Slides must be submitted one day before."

def sample():
    return {
        "schema_version":"1", "source_ref":"source-1",
        "tasks":[{
            "schema_version":"1","local_ref":"task-1","title":"Submit slides","description":"",
            "deadline":{"kind":"date","value":"2026-09-24","timezone":"Asia/Jakarta",
                "raw_text":"Slides must be submitted one day before",
                "reference_time":REF.isoformat(),"relation":{"event_ref":"event-1","offset_days":-1}},
            "estimate_minutes":None,"estimate_origin":"unknown","priority_hint":"unspecified",
            "project_candidate":None,"confidence":0.9,
            "evidence":[{"source_ref":"source-1","quote":"Slides must be submitted one day before"}],
            "uncertainties":["Submission cutoff is unknown"]}],
        "events":[{"schema_version":"1","local_ref":"event-1","title":"Presentation",
            "start":{"kind":"date","value":"2026-09-25","timezone":"Asia/Jakarta"},
            "end":None,"evidence":[{"source_ref":"source-1","quote":"The final presentation is Friday September 25"}],
            "confidence":0.9,"uncertainties":["Time unknown"]}],
        "facts":[],"requests":[],"project_candidates":[],"uncertainties":[]}


class ContractFixtures(unittest.TestCase):
    def test_relative_thursday_before_friday(self):
        validate_grounding(ExtractionEnvelope.model_validate(sample()), "source-1", BODY, REF)

    def test_wrong_relative_date_rejected(self):
        case = sample(); case["tasks"][0]["deadline"]["value"] = "2026-09-23"
        with self.assertRaises(ValueError):
            validate_grounding(ExtractionEnvelope.model_validate(case), "source-1", BODY, REF)

    def test_fabricated_evidence_rejected(self):
        case = sample(); case["tasks"][0]["evidence"][0]["quote"] = "not in source"
        with self.assertRaises(ValueError):
            validate_grounding(ExtractionEnvelope.model_validate(case), "source-1", BODY, REF)

    def test_ambiguous_date_stays_unresolved(self):
        case = sample(); case["tasks"][0]["deadline"].update(kind="unresolved", value=None, timezone=None, relation=None)
        validate_grounding(ExtractionEnvelope.model_validate(case), "source-1", BODY, REF)

    def test_date_only_and_invalid_calendar_date(self):
        case = sample(); case["tasks"][0]["deadline"]["value"] = "2026-09-31"
        with self.assertRaises(ValidationError):
            ExtractionEnvelope.model_validate(case)

    def test_explicit_datetime_with_matching_zone(self):
        case = sample(); case["tasks"][0]["deadline"].update(
            kind="datetime", value="2026-09-24T14:00:00+07:00", relation=None)
        validate_grounding(ExtractionEnvelope.model_validate(case), "source-1", BODY, REF)

    def test_extra_fields_and_missing_evidence_rejected(self):
        case = sample(); case["tasks"][0]["unknown"] = "x"
        with self.assertRaises(ValidationError):
            ExtractionEnvelope.model_validate(case)
        case = sample(); case["tasks"][0]["evidence"] = []
        with self.assertRaises(ValidationError):
            ExtractionEnvelope.model_validate(case)


if __name__ == "__main__":
    unittest.main()
