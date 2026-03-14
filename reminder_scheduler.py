import os
import json
import boto3
from datetime import datetime, timezone, timedelta

scheduler = boto3.client("scheduler")
SNS_TOPIC_ARN = os.environ.get("REMINDER_TOPIC_ARN")
SCHEDULER_ROLE_ARN = os.environ.get("SCHEDULER_ROLE_ARN")


def schedule_reminder(user_id: str, task_id: str, task_name: str, delay_minutes: int):
    """
    Creates a one-time EventBridge schedule that fires after `delay_minutes`.
    Publishes to SNS when it fires, which can fan out to push/email/SMS.
    Returns the schedule name.
    """
    fire_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    schedule_name = f"reminder-{task_id}"

    scheduler.create_schedule(
        Name=schedule_name,
        GroupName="adhd-reminders",
        ScheduleExpression=f"at({fire_at.strftime('%Y-%m-%dT%H:%M:%S')})",
        ScheduleExpressionTimezone="UTC",
        FlexibleTimeWindow={"Mode": "OFF"},
        Target={
            "Arn": SNS_TOPIC_ARN,
            "RoleArn": SCHEDULER_ROLE_ARN,
            "Input": json.dumps({
                "user_id": user_id,
                "task_id": task_id,
                "task_name": task_name,
                "message": f"Time to work on: {task_name}",
            }),
        },
        ActionAfterCompletion="DELETE",  # auto-clean one-time schedules
    )

    return schedule_name


def cancel_reminder(task_id: str):
    """Deletes a pending reminder schedule (e.g. task was completed early)."""
    try:
        scheduler.delete_schedule(
            Name=f"reminder-{task_id}",
            GroupName="adhd-reminders",
        )
    except scheduler.exceptions.ResourceNotFoundException:
        pass  # already fired or never existed


def schedule_triaged_reminders(user_id: str, triaged_tasks: list):
    """
    Takes the ordered output of triage_engine.triage() and staggers reminders
    so the highest-priority task fires first, with 30-minute gaps between tasks.
    This prevents ADHD overwhelm from multiple simultaneous alerts.
    """
    for i, task in enumerate(triaged_tasks[:3]):  # cap at top 3
        delay = 5 + (i * 30)  # 5 min, 35 min, 65 min
        schedule_reminder(
            user_id=user_id,
            task_id=task["TaskId"],
            task_name=task["Name"],
            delay_minutes=delay,
        )
