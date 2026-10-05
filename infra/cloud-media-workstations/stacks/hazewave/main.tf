module "workstation" {
  source = "../../modules/workstation"

  project_slug                          = "hazewave"
  region                                = "sa-east-1"
  deploy_resources                      = var.deploy_resources
  monthly_budget_usd                    = var.monthly_budget_usd
  budget_email                          = var.budget_email
  instance_type                         = "g6f.2xlarge"
  ami_id                                = data.aws_ami.ubuntu_2404.id
  vpc_id                                = data.aws_vpc.default.id
  subnet_id                             = data.aws_subnet.selected.id
  availability_zone                     = data.aws_subnet.selected.availability_zone
  root_volume_gib                       = 80
  data_volume_gib                       = 250
  mount_path                            = "/srv/hazewave"
  project_bucket_name                   = "cloud-media-hazewave-${data.aws_caller_identity.current.account_id}"
  tailscale_auth_key_ssm_parameter      = "/cloud-media-workstations/hazewave/tailscale-auth-key"
  tailscale_auth_key_ssm_parameter_name = "/cloud-media-workstations/hazewave/tailscale-auth-key"
  sunshine_username_ssm_parameter       = "/cloud-media-workstations/hazewave/sunshine-username"
  sunshine_password_ssm_parameter       = "/cloud-media-workstations/hazewave/sunshine-password"
  denied_workstation_role_name          = "br-no-gta-media-workstation"

  snapshot_retention_count = var.snapshot_retention_count
}
