from datetime import datetime, timezone
from task_store import get_pending_tasks, get_task_history
from habit_engine import calculate_friction_factor

ENERGY_WEIGHT = {"Low": 1, "Medium": 2, "High": 3}

# Time of day energy mapping — morning favors high energy, evening favors low
def _time_of_day_multiplier(energy_level: str) -> float:
    hour = datetime.now(timezone.utc).hour
    if 6 <= hour < 12:       # morning — reward high energy tasks
        return 1.3 if energy_level == "High" else 1.0
    elif 12 <= hour < 17:    # afternoon — neutral
        return 1.0
    else:                    # evening — reward low energy tasks
        return 1.3 if energy_level == "Low" else 0.8


def _due_date_urgency(due_date_str: str | None) -> float:
    """Returns a multiplier based on how soon the task is due."""
    if not due_date_str:
        return 1.0
    try:
        due = datetime.fromisoformat(due_date_str)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        hours_until_due = (due - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_until_due <= 0:
            return 3.0    # overdue
        elif hours_until_due <= 2:
            return 2.5    # due very soon
        elif hours_until_due <= 24:
            return 2.0    # due today
        elif hours_until_due <= 72:
            return 1.5    # due this week
        else:
            return 1.0
    except Exception:
        return 1.0


class _TaskAdapter:
    def __init__(self, item: dict):
        self.id = item["TaskId"]
        self.actual_duration = item.get("ActualMinutes") or 0
        self.estimated_duration = item.get("EstimatedMinutes") or 1
        self.snooze_count = int(item.get("SnoozeCount", 0))


def triage(user_id: str) -> list:
    """
    Ranks pending tasks by priority score combining:
    - User importance (1-5, highest weight)
    - Due date urgency
    - Energy level + time of day match
    - Friction (avoidance penalty)
    """
    pending = get_pending_tasks(user_id)
    if not pending:
        return []

    history_raw = get_task_history(user_id, limit=10)
    history = [_TaskAdapter(t) for t in history_raw]
    friction = calculate_friction_factor(history) if history else 1.0

    for task in pending:
        energy = ENERGY_WEIGHT.get(task.get("EnergyLevel", "Medium"), 2)
        importance = int(task.get("ImportanceScore", 3))
        due_multiplier = _due_date_urgency(task.get("DueDate"))
        tod_multiplier = _time_of_day_multiplier(task.get("EnergyLevel", "Medium"))

        base = (importance * 2) + energy
        task["friction_score"] = friction
        task["priority_score"] = round((base * due_multiplier * tod_multiplier) / friction, 3)

    return sorted(pending, key=lambda t: t["priority_score"], reverse=True)
