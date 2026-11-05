variable "image_uri" {
  description = "Immutable ECR image URI with @sha256 digest; empty provisions storage/repository only."
  type        = string
  default     = ""
  validation {
    condition     = var.image_uri == "" || can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/.+@sha256:[a-f0-9]{64}$", var.image_uri))
    error_message = "Pin the worker image by its ECR sha256 digest."
  }
}

variable "schedule_enabled" {
  type    = bool
  default = false
}

variable "telegram_secret_arn" {
  description = "Optional secret with bot_token and tenant-to-chat recipients."
  type        = string
  default     = ""
}

variable "webhook_delivery_enabled" {
  description = "Send customer-verified webhooks. False preserves shadow/Telegram-only behavior."
  type        = bool
  default     = false
}

variable "worker_max_targets" {
  description = "Maximum due targets per bounded invocation; compatible targets reuse Chrome."
  type        = number
  default     = 1
  validation {
    condition     = var.worker_max_targets >= 1 && var.worker_max_targets <= 20 && floor(var.worker_max_targets) == var.worker_max_targets
    error_message = "worker_max_targets must be an integer between 1 and 20."
  }
}

variable "worker_schedule_minutes" {
  description = "Wake-up interval; only due targets launch Chrome."
  type        = number
  default     = 5
  validation {
    condition     = contains([1, 5, 15], var.worker_schedule_minutes)
    error_message = "Use a 1, 5 or 15 minute worker schedule."
  }
}

variable "product_delivery_enabled" {
  description = "Enable customer Telegram/inbox and verified webhook delivery."
  type        = bool
  default     = false
}

variable "customer_telegram_secret_arn" {
  description = "Optional shared bot configuration for customer connections."
  type        = string
  default     = ""
}

variable "legacy_bot_function_arn" {
  description = "Existing family handler to receive authenticated family commands."
  type        = string
  default     = ""
}

resource "aws_ecr_repository" "worker" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  lifecycle {
    prevent_destroy = true
  }
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_iam_role" "worker" {
  count = var.image_uri == "" ? 0 : 1
  name  = "${var.name}-worker"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${var.name}"
  retention_in_days = 14
}

resource "aws_iam_role_policy" "worker" {
  count = var.image_uri == "" ? 0 : 1
  role  = aws_iam_role.worker[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:TransactWriteItems"]
        Resource = [aws_dynamodb_table.documents.arn, "${aws_dynamodb_table.documents.arn}/index/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["${aws_cloudwatch_log_group.worker.arn}:*"]
      }
      ], var.telegram_secret_arn == "" ? [] : [{
        Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.telegram_secret_arn]
        }], var.customer_telegram_secret_arn == "" ? [] : [{
        Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.customer_telegram_secret_arn]
    }])
  })
}

resource "aws_lambda_function" "worker" {
  count                          = var.image_uri == "" ? 0 : 1
  function_name                  = var.name
  role                           = aws_iam_role.worker[0].arn
  package_type                   = "Image"
  image_uri                      = var.image_uri
  architectures                  = ["arm64"]
  memory_size                    = 2048
  timeout                        = 180
  reserved_concurrent_executions = 1
  lifecycle {
    prevent_destroy = true
  }
  ephemeral_storage {
    size = 512
  }
  environment {
    variables = {
      GFPT_NEXT_TABLE                        = aws_dynamodb_table.documents.name
      GFPT_NEXT_DELIVERY                     = var.product_delivery_enabled ? "product" : (var.webhook_delivery_enabled ? (var.telegram_secret_arn == "" ? "webhooks" : "routed") : (var.telegram_secret_arn == "" ? "shadow" : "telegram"))
      GFPT_NEXT_MAX_TARGETS                  = tostring(var.worker_max_targets)
      GFPT_NEXT_TELEGRAM_SECRET_ARN          = var.telegram_secret_arn
      GFPT_NEXT_CUSTOMER_TELEGRAM_SECRET_ARN = var.customer_telegram_secret_arn
      GFPT_NEXT_PUBLIC_URL                   = aws_apigatewayv2_api.public.api_endpoint
    }
  }
  depends_on = [aws_iam_role_policy.worker, aws_cloudwatch_log_group.worker]
}

resource "aws_lambda_function_event_invoke_config" "worker" {
  count                        = var.image_uri == "" ? 0 : 1
  function_name                = aws_lambda_function.worker[0].function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 60
}

resource "aws_cloudwatch_event_rule" "worker" {
  count               = var.image_uri == "" ? 0 : 1
  name                = "${var.name}-schedule"
  schedule_expression = "rate(${var.worker_schedule_minutes} ${var.worker_schedule_minutes == 1 ? "minute" : "minutes"})"
  state               = var.schedule_enabled ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "worker" {
  count = var.image_uri == "" ? 0 : 1
  rule  = aws_cloudwatch_event_rule.worker[0].name
  arn   = aws_lambda_function.worker[0].arn
  input = jsonencode({ source = "gfpt-next.scheduler" })
  retry_policy {
    maximum_event_age_in_seconds = 60
    maximum_retry_attempts       = 0
  }
}

resource "aws_lambda_permission" "schedule" {
  count         = var.image_uri == "" ? 0 : 1
  statement_id  = "AllowNextSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.worker[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.worker[0].arn
}

resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  count               = var.image_uri == "" ? 0 : 1
  alarm_name          = "${var.name}-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.worker[0].function_name
  }
}

output "repository_url" {
  value = aws_ecr_repository.worker.repository_url
}

resource "aws_cloudwatch_metric_alarm" "collection_failures" {
  count               = var.image_uri == "" ? 0 : 1
  alarm_name          = "${var.name}-collection-failures"
  namespace           = "GFPTNext"
  metric_name         = "failed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    ServiceName = var.name
  }
}
