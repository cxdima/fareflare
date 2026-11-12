# Where alarms go. Without an address the alarms still record state in CloudWatch,
# but nobody hears about them. AWS emails the address once to confirm the subscription.
variable "alarm_email" {
  description = "Email address for alarm notifications; empty sends none."
  type        = string
  default     = ""
  sensitive   = true
}

resource "aws_sns_topic" "alarms" {
  name = "${var.name}-alarms"
  tags = { Project = "fareflare" }
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alarm_actions = [aws_sns_topic.alarms.arn]
}

# Account email that bounces or is marked as spam puts the whole SES account at risk,
# including other domains that send from it. AWS reviews an account at 5% bounces or
# 0.1% complaints; these fire well before that.
resource "aws_cloudwatch_metric_alarm" "ses_bounces" {
  count               = local.email_enabled ? 1 : 0
  alarm_name          = "${var.name}-ses-bounce-rate"
  alarm_actions       = local.alarm_actions
  namespace           = "AWS/SES"
  metric_name         = "Reputation.BounceRate"
  statistic           = "Maximum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0.03
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "ses_complaints" {
  count               = local.email_enabled ? 1 : 0
  alarm_name          = "${var.name}-ses-complaint-rate"
  alarm_actions       = local.alarm_actions
  namespace           = "AWS/SES"
  metric_name         = "Reputation.ComplaintRate"
  statistic           = "Maximum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0.0005
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}

# The application logs this when its service-wide email budget runs out: either a
# real surge of sign-ups or someone trying to make Fareflare send mail.
resource "aws_cloudwatch_log_metric_filter" "email_budget" {
  count          = var.api_image_uri == "" ? 0 : 1
  name           = "${var.name}-email-budget-reached"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "\"Account email budget reached\""
  metric_transformation {
    name          = "EmailBudgetReached"
    namespace     = "Fareflare"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "email_budget" {
  count               = var.api_image_uri == "" ? 0 : 1
  alarm_name          = "${var.name}-email-budget-reached"
  alarm_actions       = local.alarm_actions
  namespace           = "Fareflare"
  metric_name         = "EmailBudgetReached"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}
