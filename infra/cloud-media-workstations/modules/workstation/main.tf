data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "workstation" {
  count              = var.deploy_resources ? 1 : 0
  name               = "${var.project_slug}-media-workstation"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json

  tags = {
    Project = var.project_slug
  }
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count      = var.deploy_resources ? 1 : 0
  role       = aws_iam_role.workstation[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_cloudwatch_log_group" "workstation" {
  count             = var.deploy_resources ? 1 : 0
  name              = "/cloud-media-workstations/${var.project_slug}"
  retention_in_days = 30

  tags = {
    Project = var.project_slug
  }
}

resource "aws_s3_bucket" "project" {
  count  = var.deploy_resources ? 1 : 0
  bucket = var.project_bucket_name

  tags = {
    Project = var.project_slug
    Purpose = "canonical-media-backup"
  }
}

resource "aws_s3_bucket_public_access_block" "project" {
  count  = var.deploy_resources ? 1 : 0
  bucket = aws_s3_bucket.project[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "project" {
  count  = var.deploy_resources ? 1 : 0
  bucket = aws_s3_bucket.project[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "project" {
  count  = var.deploy_resources ? 1 : 0
  bucket = aws_s3_bucket.project[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "workstation_storage" {
  count = var.deploy_resources ? 1 : 0

  statement {
    sid    = "OwnProjectObjectAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${aws_s3_bucket.project[0].arn}/*"]
  }

  statement {
    sid       = "OwnProjectBucketRead"
    effect    = "Allow"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.project[0].arn]
  }

  statement {
    sid     = "AwsGridDriverRead"
    effect  = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::ec2-linux-nvidia-drivers",
      "arn:aws:s3:::ec2-linux-nvidia-drivers/*",
    ]
  }

  statement {
    sid     = "OwnProjectTailscaleSecret"
    effect  = "Allow"
    actions = ["ssm:GetParameter"]
    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${trimprefix(var.tailscale_auth_key_ssm_parameter, "/")}",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${trimprefix(var.sunshine_username_ssm_parameter, "/")}",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${trimprefix(var.sunshine_password_ssm_parameter, "/")}",
    ]
  }

  statement {
    sid       = "DecryptProjectTailscaleSecretViaSsm"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${var.region}.amazonaws.com"]
    }
  }

  statement {
    sid    = "OwnCloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["${aws_cloudwatch_log_group.workstation[0].arn}:*"]
  }
}

resource "aws_iam_role_policy" "workstation_storage" {
  count  = var.deploy_resources ? 1 : 0
  name   = "${var.project_slug}-workstation-storage"
  role   = aws_iam_role.workstation[0].id
  policy = data.aws_iam_policy_document.workstation_storage[0].json
}

data "aws_iam_policy_document" "bucket" {
  count = var.deploy_resources ? 1 : 0

  statement {
    sid    = "DenyCrossProjectWorkstation"
    effect = "Deny"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.project[0].arn,
      "${aws_s3_bucket.project[0].arn}/*",
    ]

    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values = [
        "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.denied_workstation_role_name}"
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "project" {
  count  = var.deploy_resources ? 1 : 0
  bucket = aws_s3_bucket.project[0].id
  policy = data.aws_iam_policy_document.bucket[0].json

  depends_on = [aws_s3_bucket_public_access_block.project]
}

resource "aws_iam_instance_profile" "workstation" {
  count = var.deploy_resources ? 1 : 0
  name  = "${var.project_slug}-media-workstation"
  role  = aws_iam_role.workstation[0].name
}

resource "aws_ebs_volume" "data" {
  count             = var.deploy_resources ? 1 : 0
  availability_zone = var.availability_zone
  size              = var.data_volume_gib
  type              = "gp3"
  encrypted         = true

  tags = {
    Name        = "${var.project_slug}-media-data"
    Project     = var.project_slug
    BackupClass = "media-data"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_budgets_budget" "project" {
  count        = var.deploy_resources && var.monthly_budget_usd != null ? 1 : 0
  name         = "${var.project_slug}-media-workstation-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$${var.project_slug}"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
}

resource "aws_instance" "workstation" {
  count                       = var.deploy_resources ? 1 : 0
  ami                         = var.ami_id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.workstation[0].id]
  iam_instance_profile        = aws_iam_instance_profile.workstation[0].name
  associate_public_ip_address = true

  instance_initiated_shutdown_behavior = "stop"
  disable_api_termination              = true
  monitoring                           = true

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gib
    encrypted             = true
    delete_on_termination = false
  }

  user_data = templatefile("${path.module}/templates/bootstrap.sh.tftpl", {
    project_slug         = var.project_slug
    mount_path           = var.mount_path
    idle_timeout_minutes = var.idle_timeout_minutes
    max_runtime_hours    = var.max_runtime_hours
  })

  tags = {
    Name      = "${var.project_slug}-media-workstation"
    Project   = var.project_slug
    Purpose   = "persistent-media-workstation"
    Lifecycle = "normally-stopped"
  }

  lifecycle {
    precondition {
      condition     = var.monthly_budget_usd != null
      error_message = "MONTHLY_BUDGET_USD_UNSET"
    }

    precondition {
      condition     = var.tailscale_auth_key_ssm_parameter_name == var.tailscale_auth_key_ssm_parameter
      error_message = "TAILSCALE_SSM_PARAMETER_ALIAS_MISMATCH"
    }
  }

  depends_on = [aws_budgets_budget.project]
}

resource "aws_volume_attachment" "data" {
  count       = var.deploy_resources ? 1 : 0
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data[0].id
  instance_id = aws_instance.workstation[0].id

  stop_instance_before_detaching = true
}

data "aws_iam_policy_document" "budget_action_assume" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "budget_action" {
  count              = var.deploy_resources && var.monthly_budget_usd != null ? 1 : 0
  name               = "${var.project_slug}-budget-stop-action"
  assume_role_policy = data.aws_iam_policy_document.budget_action_assume.json
}

data "aws_iam_policy_document" "budget_action" {
  count = var.deploy_resources && var.monthly_budget_usd != null ? 1 : 0

  statement {
    effect = "Allow"
    actions = [
      "ssm:StartAutomationExecution",
      "ssm:GetAutomationExecution",
      "ec2:StopInstances",
      "ec2:DescribeInstances",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "budget_action" {
  count  = var.deploy_resources && var.monthly_budget_usd != null ? 1 : 0
  name   = "${var.project_slug}-budget-stop-action"
  role   = aws_iam_role.budget_action[0].id
  policy = data.aws_iam_policy_document.budget_action[0].json
}

resource "aws_budgets_budget_action" "stop_instance" {
  count              = var.deploy_resources && var.monthly_budget_usd != null ? 1 : 0
  budget_name        = aws_budgets_budget.project[0].name
  action_type        = "RUN_SSM_DOCUMENTS"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action[0].arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = 100
  }

  definition {
    ssm_action_definition {
      action_sub_type = "STOP_EC2_INSTANCES"
      region          = var.region
      instance_ids    = [aws_instance.workstation[0].id]
    }
  }

  subscriber {
    address           = var.budget_email
    subscription_type = "EMAIL"
  }
}

resource "aws_ec2_instance_state" "normally_stopped" {
  count       = var.deploy_resources ? 1 : 0
  instance_id = aws_instance.workstation[0].id
  state       = "stopped"

  depends_on = [aws_budgets_budget_action.stop_instance]
}

data "aws_iam_policy_document" "dlm_assume" {
  statement {
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }

    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "dlm" {
  count              = var.deploy_resources ? 1 : 0
  name               = "${var.project_slug}-media-dlm"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json
}

data "aws_iam_policy_document" "dlm" {
  count = var.deploy_resources ? 1 : 0

  statement {
    effect = "Allow"
    actions = [
      "ec2:CreateSnapshot",
      "ec2:CreateSnapshots",
      "ec2:DeleteSnapshot",
      "ec2:DescribeInstances",
      "ec2:DescribeVolumes",
      "ec2:DescribeSnapshots",
      "ec2:CreateTags",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "dlm" {
  count  = var.deploy_resources ? 1 : 0
  name   = "${var.project_slug}-media-dlm"
  role   = aws_iam_role.dlm[0].id
  policy = data.aws_iam_policy_document.dlm[0].json
}

resource "aws_dlm_lifecycle_policy" "data" {
  count              = var.deploy_resources ? 1 : 0
  description        = "${var.project_slug} encrypted media data snapshots"
  execution_role_arn = aws_iam_role.dlm[0].arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]

    schedule {
      name = "daily-media-data"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"]
      }

      retain_rule {
        count = var.snapshot_retention_count
      }

      tags_to_add = {
        Project     = var.project_slug
        BackupClass = "media-data"
      }

      copy_tags = true
    }

    target_tags = {
      Project     = var.project_slug
      BackupClass = "media-data"
    }
  }
}
