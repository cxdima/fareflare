# www.<domain> answers with a permanent redirect to the domain itself, path and query
# kept. Without it, someone who types "www." gets a DNS error. A separate, tiny
# distribution with its own certificate: the main certificate and distribution are
# untouched, and the redirect is answered at the edge without reaching any origin.

variable "redirect_www" {
  description = "Redirect www.<domain_name> to domain_name."
  type        = bool
  default     = true
}

locals {
  www_enabled = var.redirect_www && var.domain_name != "" && var.hosted_zone_id != ""
  www_name    = "www.${var.domain_name}"
}

resource "aws_acm_certificate" "www" {
  count             = local.www_enabled ? 1 : 0
  domain_name       = local.www_name
  validation_method = "DNS"
  lifecycle { create_before_destroy = true }
  tags = { Project = "fareflare" }
}

resource "aws_route53_record" "www_validation" {
  for_each = local.www_enabled ? {
    for item in aws_acm_certificate.www[0].domain_validation_options : item.domain_name => {
      name = item.resource_record_name, type = item.resource_record_type, value = item.resource_record_value
    }
  } : {}
  zone_id = var.hosted_zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 300
  records = [each.value.value]
}

resource "aws_acm_certificate_validation" "www" {
  count                   = local.www_enabled ? 1 : 0
  certificate_arn         = aws_acm_certificate.www[0].arn
  validation_record_fqdns = [for record in aws_route53_record.www_validation : record.fqdn]
}

resource "aws_cloudfront_function" "www" {
  count   = local.www_enabled ? 1 : 0
  name    = "${var.name}-www-redirect"
  runtime = "cloudfront-js-2.0"
  comment = "Redirect ${local.www_name} to ${var.domain_name}"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      var query = Object.keys(request.querystring).map(function (name) {
        var item = request.querystring[name];
        var values = item.multiValue ? item.multiValue : [item];
        return values.map(function (entry) {
          return entry.value === '' ? name : name + '=' + entry.value;
        }).join('&');
      }).join('&');
      return {
        statusCode: 301,
        statusDescription: 'Moved Permanently',
        headers: {
          location: { value: 'https://${var.domain_name}' + request.uri + (query ? '?' + query : '') },
          'strict-transport-security': { value: 'max-age=31536000; includeSubDomains' },
          'cache-control': { value: 'public, max-age=86400' }
        }
      };
    }
  EOT
}

resource "aws_cloudfront_distribution" "www" {
  count           = local.www_enabled ? 1 : 0
  enabled         = true
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = "PriceClass_100"
  aliases         = [local.www_name]
  comment         = "${var.name} www redirect"

  # Never reached: the viewer-request function answers every request.
  origin {
    origin_id   = "domain"
    domain_name = var.domain_name
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id = "domain"
    # http://www goes straight to https://<domain> in one hop.
    viewer_protocol_policy = "allow-all"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.disabled.id
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.www[0].arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.www[0].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = { Project = "fareflare" }
}

resource "aws_route53_record" "www" {
  for_each = local.www_enabled ? toset(["A", "AAAA"]) : toset([])
  zone_id  = var.hosted_zone_id
  name     = local.www_name
  type     = each.value
  alias {
    name                   = aws_cloudfront_distribution.www[0].domain_name
    zone_id                = aws_cloudfront_distribution.www[0].hosted_zone_id
    evaluate_target_health = false
  }
}
