variable "project_slug" {
  type = string
}

variable "region" {
  type    = string
  default = "sa-east-1"
}

variable "instance_type" {
  type = string
}

variable "ami_id" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "availability_zone" {
  type = string
}

variable "root_volume_gib" {
  type = number
}

variable "data_volume_gib" {
  type = number
}

variable "mount_path" {
  type = string
}

variable "project_bucket_name" {
  type = string
}

variable "tailscale_auth_key_ssm_parameter" {
  type        = string
  description = "Project-scoped SecureString parameter name containing an ephemeral Tailscale auth key."
}

variable "tailscale_auth_key_ssm_parameter_name" {
  type        = string
  description = "Explicit alias for the project-scoped Tailscale SecureString parameter; must equal tailscale_auth_key_ssm_parameter."
}

variable "sunshine_username_ssm_parameter" {
  type        = string
  description = "Project-scoped SSM parameter containing the Sunshine administrative username."
}

variable "sunshine_password_ssm_parameter" {
  type        = string
  description = "Project-scoped SecureString parameter containing the Sunshine administrative password."
}

variable "denied_workstation_role_name" {
  type = string
}

variable "monthly_budget_usd" {
  type     = number
  nullable = true
}

variable "budget_email" {
  type = string
}

variable "deploy_resources" {
  type    = bool
  default = false
}

variable "snapshot_retention_count" {
  type    = number
  default = 14
}

variable "idle_timeout_minutes" {
  type    = number
  default = 30
}

variable "max_runtime_hours" {
  type    = number
  default = 8
}
