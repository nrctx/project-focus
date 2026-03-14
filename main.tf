# main.tf - Infrastructure for ADHD Reminder Backend

resource "aws_dynamodb_table" "tasks_table" {
  name           = "UserTasks"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "UserId"
  range_key      = "TaskId"

  attribute {
    name = "UserId"
    type = "S"
  }
  attribute {
    name = "TaskId"
    type = "S"
  }

  # GSI to query tasks by status (e.g., 'pending')
  global_secondary_index {
    name               = "StatusIndex"
    hash_key           = "Status"
    range_key          = "TaskId"
    projection_type    = "ALL"
  }

  attribute {
    name = "Status"
    type = "S"
  }
}

resource "aws_iam_role" "lambda_exec" {
  name = "adhd_lambda_exec_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name = "adhd_lambda_dynamodb_policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query"
      ]
      Resource = [
        aws_dynamodb_table.tasks_table.arn,
        "${aws_dynamodb_table.tasks_table.arn}/index/StatusIndex"
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "task_parser" {
  function_name = "ADHD_Task_Parser"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "parser.handler"
  runtime       = "python3.11"
  filename      = "parser.zip"

  environment {
    variables = {
      TASKS_TABLE        = aws_dynamodb_table.tasks_table.name
      ANTHROPIC_API_KEY  = var.anthropic_api_key
      REMINDER_TOPIC_ARN = aws_sns_topic.reminders.arn
      SCHEDULER_ROLE_ARN = aws_iam_role.scheduler_exec.arn
    }
  }
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude"
  type        = string
  sensitive   = true
}

resource "aws_apigatewayv2_api" "http_api" {
  name          = "adhd-reminder-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["POST", "GET"]
    allow_headers = ["Content-Type"]
  }
}

resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.task_parser.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "parse_tasks" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "POST /tasks"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.task_parser.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}

output "api_endpoint" {
  value = aws_apigatewayv2_stage.default.invoke_url
}

# --- Reminders ---

resource "aws_sns_topic" "reminders" {
  name = "adhd-reminders"
}

resource "aws_scheduler_schedule_group" "reminders" {
  name = "adhd-reminders"
}

# IAM role that EventBridge Scheduler uses to publish to SNS
resource "aws_iam_role" "scheduler_exec" {
  name = "adhd_scheduler_exec_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "scheduler_sns" {
  name = "adhd_scheduler_sns_policy"
  role = aws_iam_role.scheduler_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sns:Publish"
      Resource = aws_sns_topic.reminders.arn
    }]
  })
}

# Allow Lambda to create/delete EventBridge schedules
resource "aws_iam_role_policy" "lambda_scheduler" {
  name = "adhd_lambda_scheduler_policy"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = [
        "scheduler:CreateSchedule",
        "scheduler:DeleteSchedule",
        "iam:PassRole"
      ]
      Resource = [
        "arn:aws:scheduler:*:*:schedule/adhd-reminders/*",
        aws_iam_role.scheduler_exec.arn
      ]
    }]
  })
}

output "reminder_topic_arn" {
  value = aws_sns_topic.reminders.arn
}