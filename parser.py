import json
import os
import traceback
from decimal import Decimal

class _DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def _dumps(obj):
    return json.dumps(obj, cls=_DecimalEncoder)
import anthropic
from task_store import save_task, snooze_task, unsnooze_task, complete_task, get_tasks_by_status, update_importance, clear_all_tasks
from triage_engine import triage
from reminder_scheduler import schedule_triaged_reminders

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def handler(event, context):
    try:
        method = event.get("requestContext", {}).get("http", {}).get("method", "POST")
        path = event.get("rawPath", "/tasks")
        path_params = event.get("pathParameters") or {}
        task_id = path_params.get("taskId")

        try:
            body = json.loads(event.get("body") or "{}")
        except Exception:
            body = event

        user_id = body.get("user_id") or (event.get("queryStringParameters") or {}).get("user_id", "anonymous")

        # DELETE /tasks — clear all tasks for user
        if method == "DELETE" and path == "/tasks":
            clear_all_tasks(user_id)
            return {"statusCode": 200, "body": _dumps({"cleared": True})}

        # GET /tasks — return tasks by status
        if method == "GET" and path == "/tasks":
            status = (event.get("queryStringParameters") or {}).get("status", "pending")
            tasks = get_tasks_by_status(user_id, status)
            return {"statusCode": 200, "body": _dumps({"tasks": [
                {"task_id": t["TaskId"], "name": t["Name"], "status": t["Status"],
                 "energy": t["EnergyLevel"], "snooze_count": t.get("SnoozeCount", 0),
                 "created_at": t["CreatedAt"]}
                for t in tasks
            ]})}

        # PATCH /tasks/{taskId} — update status
        if method == "PATCH" and task_id:
            new_status = body.get("status")
            if new_status == "snoozed":
                snooze_task(user_id, task_id)
            elif new_status == "done":
                complete_task(user_id, task_id, body.get("actual_minutes", 0))
            elif new_status == "pending":
                unsnooze_task(user_id, task_id)
            if "importance" in body:
                update_importance(user_id, task_id, int(body["importance"]))
            return {"statusCode": 200, "body": _dumps({"updated": task_id})}

        user_input = body.get("input") or body.get("text_input")

        if not user_input:
            return {"statusCode": 400, "body": _dumps({"error": "input is required"})}

        # Step 1: Parse natural language into structured tasks
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=(
                "You are an executive function coach for someone with ADHD. Analyze the input and extract tasks. "
                "For each task: "
                "1. Separate multiple tasks mentioned. "
                "2. Assign 'EnergyLevel' (Low/Medium/High). "
                "3. If vague (e.g. 'clean house'), set 'RequiresBreakdown' to true. "
                "4. Extract 'DueDate' if mentioned (ISO 8601 format, e.g. '2026-03-15T17:00:00'). Leave null if not mentioned. "
                "5. Assign 'ImportanceScore' 1-5 based on urgency and consequence (5=critical, 1=nice-to-have). "
                "6. Estimate 'EstimatedMinutes'. "
                f"Current datetime: {__import__('datetime').datetime.utcnow().isoformat()}"
            ),
            messages=[{"role": "user", "content": user_input}],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "EnergyLevel": {"type": "string", "enum": ["Low", "Medium", "High"]},
                                        "RequiresBreakdown": {"type": "boolean"},
                                        "EstimatedMinutes": {"type": "integer"},
                                        "DueDate": {"type": "string"},
                                        "ImportanceScore": {"type": "integer"}
                                    },
                                    "required": ["name", "EnergyLevel", "RequiresBreakdown", "ImportanceScore"],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": ["tasks"],
                        "additionalProperties": False
                    }
                }
            }
        )

        text = next(b.text for b in response.content if b.type == "text")
        parsed = json.loads(text)

        # Step 2: Persist each task
        task_ids = [save_task(user_id, task) for task in parsed["tasks"]]

        # Step 3: Re-triage all pending tasks (includes the ones just saved)
        triaged = triage(user_id)

        # Step 4: Schedule staggered reminders for the top 3
        schedule_triaged_reminders(user_id, triaged)

        return {
            "statusCode": 200,
            "body": _dumps({
                "saved": task_ids,
                "triaged_tasks": [
                    {
                        "task_id": t["TaskId"],
                        "name": t["Name"],
                        "priority_score": t["priority_score"],
                        "friction_score": t["friction_score"],
                        "energy": t["EnergyLevel"],
                        "importance": t.get("ImportanceScore", 3),
                        "due_date": t.get("DueDate"),
                    }
                    for t in triaged
                ],
            }),
        }

    except Exception as e:
        traceback.print_exc()
        return {"statusCode": 500, "body": _dumps({"error": str(e)})}

