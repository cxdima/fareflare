# This file exists only on the development branch. Maintain the live stack from
# the original main worktree. It stops accidental unscoped plans/applies here.
variable "allow_stable_stack_from_development" {
  type    = bool
  default = false
}

resource "terraform_data" "stable_stack_guard" {
  lifecycle {
    precondition {
      condition     = var.allow_stable_stack_from_development
      error_message = "The stable stack is blocked in the development worktree. Use the original main checkout; infra-next is separate sandbox storage."
    }
  }
}
