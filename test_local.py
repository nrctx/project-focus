"""
Local smoke test — stubs out AWS so you can verify the Claude API
and triage logic without a live DynamoDB or EventBridge.

Run with:
    ANTHROPIC_API_KEY=sk-... python test_local.py
"""
import json
import unittest
from unittest.mock import patch, MagicMock


# --- Stub AWS clients before any project code imports boto3 ---

def _make_task(name, energy, breakdown, minutes=15):
    return {
        "TaskId": f"task-{name[:4].lower()}",
        "UserId": "test-user",
        "Name": name,
        "EnergyLevel": energy,
        "RequiresBreakdown": breakdown,
        "EstimatedMinutes": minutes,
        "ActualMinutes": None,
        "SnoozeCount": 0,
        "Status": "pending",
        "CreatedAt": "2026-01-01T00:00:00+00:00",
    }


FAKE_TASKS = [
    _make_task("Email boss", "High", False, 10),
    _make_task("Clean house", "Low", True, 60),
    _make_task("Buy groceries", "Medium", False, 20),
]


class TestPipeline(unittest.TestCase):

    @patch("task_store.table")
    @patch("reminder_scheduler.scheduler")
    def test_full_pipeline(self, mock_scheduler, mock_table):
        # DynamoDB stubs
        mock_table.put_item = MagicMock()
        mock_table.query = MagicMock(return_value={"Items": FAKE_TASKS})

        # EventBridge scheduler stub
        mock_scheduler.create_schedule = MagicMock()
        mock_scheduler.exceptions.ResourceNotFoundException = Exception

        from parser import handler

        event = {
            "body": json.dumps({
                "user_id": "test-user",
                "input": "I need to email my boss, clean the house, and buy groceries",
            })
        }

        result = handler(event, {})

        print("\n--- Response ---")
        print(json.dumps(result, indent=2))

        self.assertEqual(result["statusCode"], 200)
        body = json.loads(result["body"])

        # Tasks were saved
        self.assertTrue(len(body["saved"]) > 0)
        print(f"\nSaved {len(body['saved'])} task(s)")

        # Triage returned ranked results
        self.assertTrue(len(body["triaged_tasks"]) > 0)
        print("\nTriaged order:")
        for t in body["triaged_tasks"]:
            print(f"  [{t['priority_score']}] {t['name']} ({t['energy']})")

        # Schedules were created (capped at 3)
        call_count = mock_scheduler.create_schedule.call_count
        self.assertLessEqual(call_count, 3)
        print(f"\nScheduled {call_count} reminder(s)")

    @patch("task_store.table")
    @patch("reminder_scheduler.scheduler")
    def test_missing_input(self, mock_scheduler, mock_table):
        from parser import handler
        result = handler({"user_id": "test-user"}, {})
        self.assertEqual(result["statusCode"], 400)
        print("\nMissing input correctly returns 400")


if __name__ == "__main__":
    unittest.main(verbosity=2)
