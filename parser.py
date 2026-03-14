import json
import os
import traceback
import anthropic
from task_store import save_task
from triage_engine import triage
from reminder_scheduler import schedule_triaged_reminders

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def handler(event, context):
    try:
        try:
            body = json.loads(event.get("body") or "{}")
        except Exception:
            body = event

        user_id = body.get("user_id", "anonymous")
        user_input = body.get("input") or body.get("text_input")

        if not user_input:
            return {"statusCode": 400, "body": json.dumps({"error": "input is required"})}

        # Step 1: Parse natural language into structured tasks
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            thinking={"type": "adaptive"},
            system=(
                "You are an executive function coach. Analyze the input. "
                "1. Separate multiple tasks. "
                "2. Assign 'EnergyLevel' (Low/Medium/High). "
                "3. If a task is vague (e.g., 'Clean house'), set 'RequiresBreakdown' to True. "
                "4. Output strictly in JSON."
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
                                        "EstimatedMinutes": {"type": "integer"}
                                    },
                                    "required": ["name", "EnergyLevel", "RequiresBreakdown"],
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
            "body": json.dumps({
                "saved": task_ids,
                "triaged_tasks": [
                    {
                        "task_id": t["TaskId"],
                        "name": t["Name"],
                        "priority_score": t["priority_score"],
                        "friction_score": t["friction_score"],
                        "energy": t["EnergyLevel"],
                    }
                    for t in triaged
                ],
            }),
        }

    except Exception as e:
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

