import anthropic
import os

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

def trigger_atomic_breakdown(task_id):
    """
    Calls Claude to split a repeatedly-snoozed task into small, actionable micro-steps.
    Returns a list of micro-step strings. The caller is responsible for saving them.
    """
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=(
            "You are an executive function coach for someone with ADHD. "
            "Break the given task into 3-5 concrete micro-steps that each take under 10 minutes. "
            "Output strictly as JSON: {\"micro_steps\": [\"step1\", \"step2\", ...]}"
        ),
        messages=[
            {"role": "user", "content": f"Break down task_id: {task_id} into micro-steps."}
        ],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "micro_steps": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["micro_steps"],
                    "additionalProperties": False
                }
            }
        }
    )
    import json
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["micro_steps"]


def calculate_friction_factor(task_history):
    """
    Analyzes the last 10 tasks of a similar category.
    If 'ActualTime' > 'EstimatedTime', it increases the 'TimeBlindnessBuffer'.
    If 'SnoozeCount' > 2, it triggers an automatic 'Micro-Breakdown'.
    """
    friction_score = 1.0
    
    for task in task_history:
        # Check for Time Blindness (Estimation vs Reality)
        if task.actual_duration > task.estimated_duration:
            ratio = task.actual_duration / task.estimated_duration
            friction_score += (ratio * 0.1)
            
        # Check for Task Avoidance (Snoozing)
        if task.snooze_count >= 3:
            # FLAG: This task type is causing paralysis
            trigger_atomic_breakdown(task.id)
            
    return round(friction_score, 2)