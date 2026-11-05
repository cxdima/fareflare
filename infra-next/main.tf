# Additive resources in the current AWS account. The family tracker is untouched.
# Separate key in the existing private, versioned production state bucket.
terraform {
  required_version = ">= 1.10.0"
  backend "s3" {
    bucket       = "gfpricetracker-terraform-state"
    key          = "gfpt-next-production/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "name" {
  type    = string
  default = "gfpt-next-production"
  validation {
    condition     = can(regex("^gfpt-next-[a-z0-9-]{3,50}$", var.name))
    error_message = "New resources must use a gfpt-next- prefix."
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "expected_account_id" {
  description = "Refuse to apply into a different account when local AWS profiles change."
  type        = string
  default     = "851725466918"
  validation {
    condition     = can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Set the intended 12-digit AWS account ID."
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.expected_account_id]
}

resource "aws_dynamodb_table" "documents" {
  name                        = var.name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "id"
  deletion_protection_enabled = true
  lifecycle {
    prevent_destroy = true
  }

  attribute {
    name = "id"
    type = "S"
  }
  attribute {
    name = "partition"
    type = "S"
  }
  attribute {
    name = "due"
    type = "N"
  }
  global_secondary_index {
    name            = "partition-due"
    hash_key        = "partition"
    range_key       = "due"
    projection_type = "ALL"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  point_in_time_recovery {
    enabled = true
  }
  server_side_encryption {
    enabled = true
  }
  tags = {
    Project     = "gfpt-next"
    Environment = "production"
  }
}

output "table_name" {
  value = aws_dynamodb_table.documents.name
}
