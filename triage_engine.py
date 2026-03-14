from task_store import get_pending_tasks, get_task_history
from habit_engine import calculate_friction_factor

# Maps EnergyLevel to a numeric weight for scoring
ENERGY_WEIGHT = {"Low": 1, "Medium": 2, "High": 3}


class _TaskAdapter:
    """Wraps a DynamoDB dict so habit_engine's attribute-based code works unchanged."""
    def __init__(self, item: dict):
        self.id = item["TaskId"]
        self.actual_duration = item.get("ActualMinutes") or 0
        self.estimated_duration = item.get("EstimatedMinutes") or 1  # avoid div-by-zero
        self.snooze_count = int(item.get("SnoozeCount", 0))


def triage(user_id: str) -> list:
    """
    Returns the user's pending tasks ranked by priority.

    Priority score = energy_weight / friction_score
      - High-energy tasks rank higher when friction is low.
      - Tasks the user keeps avoiding (high friction) are deprioritised until
        trigger_atomic_breakdown() has split them into micro-steps.

    Each returned dict includes a 'priority_score' and 'friction_score' field.
    """
    pending = get_pending_tasks(user_id)
    if not pending:
        return []

    history_raw = get_task_history(user_id, limit=10)
    history = [_TaskAdapter(t) for t in history_raw]
    friction = calculate_friction_factor(history) if history else 1.0

    for task in pending:
        energy = ENERGY_WEIGHT.get(task.get("EnergyLevel", "Medium"), 2)
        task["friction_score"] = friction
        task["priority_score"] = round(energy / friction, 3)

    return sorted(pending, key=lambda t: t["priority_score"], reverse=True)
