# Account email (password resets and address confirmation) through Amazon SES,
# sent from the public domain and signed with DKIM.
#
# A new SES account starts in the sandbox, where it can only send to addresses
# verified in SES. Request production access in the SES console (Account
# dashboard > Request production access) before relying on password resets.
variable "email_enabled" {
  description = "Send account email through Amazon SES. Needs domain_name and hosted_zone_id."
  type        = bool
  default     = false
}

variable "email_from" {
  description = "Sender for account email; empty uses \"<product_name> <no-reply@<domain_name>>\"."
  type        = string
  default     = ""
}

locals {
  email_enabled = var.email_enabled && var.domain_name != "" && var.hosted_zone_id != ""
  email_from    = var.email_from != "" ? var.email_from : "${var.product_name} <no-reply@${var.domain_name}>"
  mail_from     = "mail.${var.domain_name}"
}

resource "aws_sesv2_email_identity" "domain" {
  count          = local.email_enabled ? 1 : 0
  email_identity = var.domain_name
  tags           = { Project = "fareflare" }
}

resource "aws_route53_record" "ses_dkim" {
  count   = local.email_enabled ? 3 : 0
  zone_id = var.hosted_zone_id
  name    = "${aws_sesv2_email_identity.domain[0].dkim_signing_attributes[0].tokens[count.index]}._domainkey.${var.domain_name}"
  type    = "CNAME"
  ttl     = 1800
  records = ["${aws_sesv2_email_identity.domain[0].dkim_signing_attributes[0].tokens[count.index]}.dkim.amazonses.com"]
}

# A custom MAIL FROM subdomain aligns SPF with the sending domain.
resource "aws_sesv2_email_identity_mail_from_attributes" "domain" {
  count                  = local.email_enabled ? 1 : 0
  email_identity         = aws_sesv2_email_identity.domain[0].email_identity
  mail_from_domain       = local.mail_from
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}

resource "aws_route53_record" "ses_mail_from_mx" {
  count   = local.email_enabled ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = local.mail_from
  type    = "MX"
  ttl     = 1800
  records = ["10 feedback-smtp.${var.region}.amazonses.com"]
}

resource "aws_route53_record" "ses_mail_from_spf" {
  count   = local.email_enabled ? 1 : 0
  zone_id = var.hosted_zone_id
  name    = local.mail_from
  type    = "TXT"
  ttl     = 1800
  records = ["v=spf1 include:amazonses.com ~all"]
}
