resource "aws_security_group" "workstation" {
  count       = var.deploy_resources ? 1 : 0
  name        = "${var.project_slug}-workstation-private"
  description = "No public inbound access; Sunshine rides an authenticated private overlay"
  vpc_id      = var.vpc_id

  revoke_rules_on_delete = true

  tags = {
    Project = var.project_slug
    Purpose = "cloud-media-workstation"
  }
}

resource "aws_vpc_security_group_egress_rule" "all_ipv4" {
  count             = var.deploy_resources ? 1 : 0
  security_group_id = aws_security_group.workstation[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Outbound only for SSM, package repositories, Tailscale and provider APIs"
}
