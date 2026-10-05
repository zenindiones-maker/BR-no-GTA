variable "deploy_resources" {
  type        = bool
  description = "Explicit switch for chargeable AWS resources."
  default     = false
}

variable "monthly_budget_usd" {
  type        = number
  description = "Human-approved monthly budget. Null fails closed before compute."
  default     = null
  nullable    = true
}

variable "budget_email" {
  type        = string
  description = "Human email for AWS Budget notifications."
  default     = ""
}

variable "snapshot_retention_count" {
  type    = number
  default = 14
}
