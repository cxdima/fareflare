variable "api_image_uri" {
  description = "Pinned application image; empty creates the API address/repository without serving traffic."
  type        = string
  default     = ""
  validation {
    condition     = var.api_image_uri == "" || can(regex("^[0-9]{12}\\.dkr\\.ecr\\.[a-z0-9-]+\\.amazonaws\\.com/.+@sha256:[a-f0-9]{64}$", var.api_image_uri))
    error_message = "Pin the API image by its ECR sha256 digest."
  }
}

variable "product_name" {
  type    = string
  default = "Fareflare"
}

variable "registration_mode" {
  description = "open lets anyone create an account; closed stops new sign-ups."
  type        = string
  default     = "open"
  validation {
    condition     = contains(["open", "closed"], var.registration_mode)
    error_message = "Use open or closed registration."
  }
}

variable "search_enabled" {
  description = "Admit validated fixed-date nonstop one-way USD route searches."
  type        = bool
  default     = false
}

variable "billing_enabled" {
  description = "Billing is disabled during development. A payment provider must be implemented before enabling it."
  type        = bool
  default     = false
  validation {
    condition     = !var.billing_enabled
    error_message = "Keep billing disabled during the free development release."
  }
}

resource "aws_ecr_repository" "api" {
  name                 = "${var.name}-api"
  image_tag_mutability = "IMMUTABLE"
  lifecycle {
    prevent_destroy = true
  }
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_apigatewayv2_api" "public" {
  name          = "${var.name}-api"
  protocol_type = "HTTP"
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.name}-api"
  retention_in_days = 14
}

resource "aws_iam_role" "api" {
  name = "${var.name}-api"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "api" {
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:TransactWriteItems"],
      Resource = [aws_dynamodb_table.documents.arn, "${aws_dynamodb_table.documents.arn}/index/*"] },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"],
      Resource = ["${aws_cloudwatch_log_group.api.arn}:*"] }
      ], var.customer_telegram_secret_arn == "" ? [] : [{
        Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.customer_telegram_secret_arn]
        }], local.email_enabled ? [{
        Effect = "Allow", Action = ["ses:SendEmail"], Resource = [aws_sesv2_email_identity.domain[0].arn]
    }] : [])
  })
}

resource "aws_lambda_function" "api" {
  count                          = var.api_image_uri == "" ? 0 : 1
  function_name                  = "${var.name}-api"
  role                           = aws_iam_role.api.arn
  package_type                   = "Image"
  image_uri                      = var.api_image_uri
  architectures                  = ["arm64"]
  memory_size                    = 1024
  timeout                        = 29
  reserved_concurrent_executions = 8
  lifecycle {
    prevent_destroy = true
  }
  environment {
    variables = {
      FAREFLARE_TABLE                        = aws_dynamodb_table.documents.name
      FAREFLARE_PUBLIC_URL                   = local.public_url
      FAREFLARE_ADDITIONAL_HOSTS             = replace(aws_apigatewayv2_api.public.api_endpoint, "https://", "")
      FAREFLARE_PRODUCT_NAME                 = var.product_name
      FAREFLARE_REGISTRATION_MODE            = var.registration_mode
      FAREFLARE_BILLING_ENABLED              = tostring(var.billing_enabled)
      FAREFLARE_SEARCH_ENABLED               = tostring(var.search_enabled)
      FAREFLARE_MONITOR_LIMIT                = tostring(var.monitor_limit)
      FAREFLARE_MIN_INTERVAL                 = "900"
      FAREFLARE_GLOBAL_TARGET_LIMIT          = "20"
      FAREFLARE_CUSTOMER_TELEGRAM_SECRET_ARN = var.customer_telegram_secret_arn
      FAREFLARE_EMAIL                        = local.email_enabled ? "ses" : "off"
      FAREFLARE_EMAIL_FROM                   = local.email_enabled ? local.email_from : ""
    }
  }
  depends_on = [aws_iam_role_policy.api, aws_cloudwatch_log_group.api]
}

resource "aws_apigatewayv2_integration" "api" {
  count                  = var.api_image_uri == "" ? 0 : 1
  api_id                 = aws_apigatewayv2_api.public.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api[0].invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "api" {
  for_each  = var.api_image_uri == "" ? toset([]) : toset(["$default", "POST /auth/register", "POST /auth/login", "POST /auth/recover"])
  api_id    = aws_apigatewayv2_api.public.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api[0].id}"
}

resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.public.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
  dynamic "route_settings" {
    for_each = var.api_image_uri == "" ? [] : ["POST /auth/register", "POST /auth/login", "POST /auth/recover"]
    content {
      route_key              = route_settings.value
      throttling_burst_limit = route_settings.value == "POST /auth/register" ? 2 : 3
      throttling_rate_limit  = route_settings.value == "POST /auth/register" ? 0.2 : 1
    }
  }
  depends_on = [aws_apigatewayv2_route.api]
}

resource "aws_lambda_permission" "api" {
  count         = var.api_image_uri == "" ? 0 : 1
  statement_id  = "AllowProductHTTPAPI"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.public.execution_arn}/*/*"
}

resource "aws_cloudwatch_metric_alarm" "api_errors" {
  count               = var.api_image_uri == "" ? 0 : 1
  alarm_name          = "${var.name}-api-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.api[0].function_name
  }
}

output "api_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "application_url" {
  value = local.public_url
}
