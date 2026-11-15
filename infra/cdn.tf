# CloudFront in front of the API Gateway custom domain.
#
# Without it, every file of the website (scripts, fonts, artwork, the scroll-sequence
# frames) is a Lambda invocation behind API Gateway's account-wide throttle: one page
# load made ~190 requests, and visitors were answered 429 or 503. Static files are now
# cached at the edge (fingerprinted ones for a year, /assets for an hour); pages, the
# API, OAuth, MCP and Telegram pass straight through, uncached.
#
# Static files come from a private S3 bucket (fareflare.publish_web uploads them), so
# a cache miss costs an S3 read instead of a Lambda invocation that may start cold;
# every edge location misses once per file, and on a quiet site misses are common.
# Pages, the API, OAuth, MCP and Telegram reach the application through the custom
# domain's regional endpoint with the viewer's Host header, so the application and
# its TLS certificate see the same name.
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
  static_paths = [
    "/assets/*", "/media/*", "*.js", "*.css", "*.webmanifest", "*.ico", "/favicon.svg",
    "/apple-touch-icon.png",
  ]
}

data "aws_caller_identity" "current" {}

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

# Website files. Private: only this distribution can read them (origin access control),
# and listing is allowed to it alone so a missing file is a 404 rather than a 403.
resource "aws_s3_bucket" "web" {
  count  = local.cdn_enabled ? 1 : 0
  bucket = "${var.name}-web-${data.aws_caller_identity.current.account_id}"
  tags   = { Project = "fareflare" }
}

resource "aws_s3_bucket_public_access_block" "web" {
  count                   = local.cdn_enabled ? 1 : 0
  bucket                  = aws_s3_bucket.web[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web" {
  count  = local.cdn_enabled ? 1 : 0
  bucket = aws_s3_bucket.web[0].id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  count  = local.cdn_enabled ? 1 : 0
  bucket = aws_s3_bucket.web[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "web" {
  count                             = local.cdn_enabled ? 1 : 0
  name                              = "${var.name}-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "web" {
  count = local.cdn_enabled ? 1 : 0
  statement {
    sid       = "CloudFrontReadsFiles"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web[0].arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.public[0].arn]
    }
  }
  statement {
    sid       = "CloudFrontSeesMissingFilesAsNotFound"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.web[0].arn]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.public[0].arn]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  count      = local.cdn_enabled ? 1 : 0
  bucket     = aws_s3_bucket.web[0].id
  policy     = data.aws_iam_policy_document.web[0].json
  depends_on = [aws_s3_bucket_public_access_block.web]
}

# S3 answers without the application's headers, so the edge adds them.
resource "aws_cloudfront_response_headers_policy" "static" {
  count = local.cdn_enabled ? 1 : 0
  name  = "${var.name}-static-headers"
  security_headers_config {
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "no-referrer"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    # Applies only when a file is opened as a document (an SVG, say): nothing runs.
    content_security_policy {
      content_security_policy = "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; frame-ancestors 'none'"
      override                = true
    }
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
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web[0].bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web[0].id
  }

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
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = "web"
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["GET", "HEAD"]
      cached_methods             = ["GET", "HEAD"]
      compress                   = true
      cache_policy_id            = aws_cloudfront_cache_policy.static[0].id
      response_headers_policy_id = aws_cloudfront_response_headers_policy.static[0].id
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

output "web_bucket" {
  description = "Where python -m fareflare.publish_web uploads the website's files."
  value       = local.cdn_enabled ? aws_s3_bucket.web[0].id : null
}
