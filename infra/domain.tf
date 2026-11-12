variable "domain_name" {
  description = "Optional public DNS name in the supplied Route 53 hosted zone."
  type        = string
  default     = ""
}
variable "hosted_zone_id" {
  type    = string
  default = ""
}
variable "monitor_limit" {
  type    = number
  default = 20
  validation {
    condition     = var.monitor_limit >= 1 && var.monitor_limit <= 100 && floor(var.monitor_limit) == var.monitor_limit
    error_message = "Use an integer monitor limit from 1 to 100."
  }
}
locals {
  public_url = var.domain_name == "" ? aws_apigatewayv2_api.public.api_endpoint : "https://${var.domain_name}"
}
resource "aws_acm_certificate" "public" {
  count             = var.domain_name == "" ? 0 : 1
  domain_name       = var.domain_name
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
  tags = { Project = "fareflare" }
}
resource "aws_route53_record" "validation" {
  for_each = var.domain_name == "" ? {} : {
    for item in aws_acm_certificate.public[0].domain_validation_options : item.domain_name => {
      name = item.resource_record_name, type = item.resource_record_type, value = item.resource_record_value
    }
  }
  zone_id = var.hosted_zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 300
  records = [each.value.value]
}
resource "aws_acm_certificate_validation" "public" {
  count                   = var.domain_name == "" ? 0 : 1
  certificate_arn         = aws_acm_certificate.public[0].arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}
resource "aws_apigatewayv2_domain_name" "public" {
  count       = var.domain_name == "" ? 0 : 1
  domain_name = var.domain_name
  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.public[0].certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}
resource "aws_apigatewayv2_api_mapping" "public" {
  count       = var.domain_name == "" || var.api_image_uri == "" ? 0 : 1
  api_id      = aws_apigatewayv2_api.public.id
  domain_name = aws_apigatewayv2_domain_name.public[0].id
  stage       = aws_apigatewayv2_stage.api.id
}
# The domain points at CloudFront when it is on (see cdn.tf), otherwise straight at
# API Gateway. CloudFront also answers over IPv6.
resource "aws_route53_record" "public" {
  count   = var.domain_name == "" ? 0 : 1
  zone_id = var.hosted_zone_id
  name    = var.domain_name
  type    = "A"
  alias {
    name                   = local.cdn_enabled ? aws_cloudfront_distribution.public[0].domain_name : aws_apigatewayv2_domain_name.public[0].domain_name_configuration[0].target_domain_name
    zone_id                = local.cdn_enabled ? aws_cloudfront_distribution.public[0].hosted_zone_id : aws_apigatewayv2_domain_name.public[0].domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "public_ipv6" {
  count   = local.cdn_enabled ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = var.domain_name
  type    = "AAAA"
  alias {
    name                   = aws_cloudfront_distribution.public[0].domain_name
    zone_id                = aws_cloudfront_distribution.public[0].hosted_zone_id
    evaluate_target_health = false
  }
}
