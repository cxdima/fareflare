# CloudFront in front of the API Gateway custom domain.
#
# Without it, every file of the website (scripts, fonts, artwork, the scroll-sequence
# frames) is a Lambda invocation behind API Gateway's account-wide throttle: one page
# load made ~190 requests, and visitors were answered 429 or 503. Static files are now
# cached at the edge (fingerprinted ones for a year, /assets for an hour); pages, the
# API, OAuth, MCP and Telegram pass straight through, uncached.
#
# CloudFront reaches the origin through the custom domain's regional endpoint with the
# viewer's Host header, so the application and its TLS certificate see the same name.
# A secret header marks requests that came through CloudFront: only those may name the
# visitor's address (CloudFront-Viewer-Address) for per-address rate limits.

variable "cdn_enabled" {
  description = "Serve the domain through CloudFront. Needs domain_name and edge_secret."
  type        = bool
  default     = false
}

variable "edge_secret" {
  description = "Random value CloudFront sends to the origin; at least 32 characters."
  type        = string
  default     = ""
  sensitive   = true
  validation {
    condition     = var.edge_secret == "" || length(var.edge_secret) >= 32
    error_message = "Use an edge secret of at least 32 characters."
  }
}

locals {
  cdn_enabled = var.cdn_enabled && var.domain_name != "" && var.api_image_uri != ""
  # Paths whose answers are the same for everyone and say so in Cache-Control.
  static_paths = ["/assets/*", "/media/*", "*.js", "*.css", "*.webmanifest", "*.ico"]
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer_and_edge" {
  name = "Managed-AllViewerAndCloudFrontHeaders-2022-06"
}

# Cached by path alone: no cookie, header or query string can make a new cache entry,
# so nobody can bypass the cache by adding ?anything to a file's address.
resource "aws_cloudfront_cache_policy" "static" {
  count       = local.cdn_enabled ? 1 : 0
  name        = "${var.name}-static"
  min_ttl     = 0
  default_ttl = 3600
  max_ttl     = 31536000
  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_origin_request_policy" "static" {
  count = local.cdn_enabled ? 1 : 0
  name  = "${var.name}-static-host"
  cookies_config {
    cookie_behavior = "none"
  }
  headers_config {
    header_behavior = "whitelist"
    headers {
      items = ["Host"]
    }
  }
  query_strings_config {
    query_string_behavior = "none"
  }
}

resource "aws_cloudfront_distribution" "public" {
  count           = local.cdn_enabled ? 1 : 0
  enabled         = true
  is_ipv6_enabled = true
  http_version    = "http2and3"
  price_class     = "PriceClass_100"
  aliases         = [var.domain_name]
  comment         = "${var.name} website, API and MCP"

  origin {
    origin_id   = "api"
    domain_name = aws_apigatewayv2_domain_name.public[0].domain_name_configuration[0].target_domain_name
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 30
    }
    custom_header {
      name  = "X-Fareflare-Edge"
      value = var.edge_secret
    }
  }

  default_cache_behavior {
    target_origin_id         = "api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_and_edge.id
  }

  dynamic "ordered_cache_behavior" {
    for_each = local.static_paths
    content {
      path_pattern             = ordered_cache_behavior.value
      target_origin_id         = "api"
      viewer_protocol_policy   = "redirect-to-https"
      allowed_methods          = ["GET", "HEAD"]
      cached_methods           = ["GET", "HEAD"]
      compress                 = true
      cache_policy_id          = aws_cloudfront_cache_policy.static[0].id
      origin_request_policy_id = aws_cloudfront_origin_request_policy.static[0].id
    }
  }

  # A failed answer must never be served from the cache. (CloudFront does not cache a
  # 429 in the first place, and does not accept it here.)
  dynamic "custom_error_response" {
    for_each = [500, 502, 503, 504]
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.public[0].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = { Project = "fareflare" }
}

output "cdn_distribution_id" {
  value = local.cdn_enabled ? aws_cloudfront_distribution.public[0].id : null
}
