import unittest
from focusos_api.agent_tools import ToolValidationError, argument_hash, validate_tool_request


class ToolBoundaryTests(unittest.TestCase):
    def test_tasks_list_is_bounded(self):
        request = validate_tool_request("tasks.list", {"limit": 10, "status": "open"})
        self.assertEqual(request.arguments.limit, 10)

    def test_unknown_tool_and_model_owned_identity_rejected(self):
        for name, args in (
            ("calendar.create_event", {}),
            ("tasks.list", {"user_id": "foreign"}),
            ("tasks.list", {"limit": 999}),
        ):
            with self.assertRaises(ToolValidationError):
                validate_tool_request(name, args)

    def test_canonical_argument_hash(self):
        first = argument_hash("tasks.list", {"limit": 2, "status": "open"})
        second = argument_hash("tasks.list", {"status": "open", "limit": 2})
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)


if __name__ == "__main__":
    unittest.main()
