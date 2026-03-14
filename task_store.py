import os
import uuid
import boto3
from datetime import datetime, timezone

TABLE_NAME = os.environ.get("TASKS_TABLE", "UserTasks")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


def save_task(user_id: str, task: dict) -> str:
    """
    Persists a single parsed task to DynamoDB.
    Expects task dict with keys: name, EnergyLevel, RequiresBreakdown, EstimatedMinutes (optional).
    Returns the generated TaskId.
    """
    task_id = str(uuid.uuid4())
    item = {
        "UserId": user_id,
        "TaskId": task_id,
        "Status": "pending",
        "Name": task["name"],
        "EnergyLevel": task["EnergyLevel"],
        "RequiresBreakdown": task["RequiresBreakdown"],
        "EstimatedMinutes": task.get("EstimatedMinutes"),
        "SnoozeCount": 0,
        "ActualMinutes": None,
        "CreatedAt": datetime.now(timezone.utc).isoformat(),
    }
    table.put_item(Item=item)
    return task_id


def get_pending_tasks(user_id: str) -> list:
    """
    Returns all pending tasks for a user, sorted by creation time.
    """
    response = table.query(
        KeyConditionExpression="UserId = :uid",
        FilterExpression="#s = :status",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":uid": user_id, ":status": "pending"},
    )
    tasks = response.get("Items", [])
    return sorted(tasks, key=lambda t: t["CreatedAt"])


def complete_task(user_id: str, task_id: str, actual_minutes: int):
    """
    Marks a task as done and records how long it actually took.
    """
    table.update_item(
        Key={"UserId": user_id, "TaskId": task_id},
        UpdateExpression="SET #s = :done, ActualMinutes = :actual",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":done": "done", ":actual": actual_minutes},
    )


def snooze_task(user_id: str, task_id: str):
    """
    Increments the snooze counter and sets status to snoozed.
    """
    table.update_item(
        Key={"UserId": user_id, "TaskId": task_id},
        UpdateExpression="SET #s = :snoozed ADD SnoozeCount :one",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":snoozed": "snoozed", ":one": 1},
    )


def unsnooze_task(user_id: str, task_id: str):
    """Sets a snoozed task back to pending."""
    table.update_item(
        Key={"UserId": user_id, "TaskId": task_id},
        UpdateExpression="SET #s = :pending",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":pending": "pending"},
    )


def get_tasks_by_status(user_id: str, status: str) -> list:
    """Returns all tasks for a user filtered by status."""
    response = table.query(
        KeyConditionExpression="UserId = :uid",
        FilterExpression="#s = :status",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":uid": user_id, ":status": status},
    )
    return sorted(response.get("Items", []), key=lambda t: t["CreatedAt"])


def get_task_history(user_id: str, limit: int = 10) -> list:
    """
    Returns the last `limit` completed tasks for friction score calculation.
    """
    response = table.query(
        KeyConditionExpression="UserId = :uid",
        FilterExpression="#s = :done",
        ExpressionAttributeNames={"#s": "Status"},
        ExpressionAttributeValues={":uid": user_id, ":done": "done"},
        ScanIndexForward=False,
        Limit=limit,
    )
    return response.get("Items", [])
