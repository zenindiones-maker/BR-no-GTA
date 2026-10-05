output "instance_id" {
  value = try(aws_instance.workstation[0].id, null)
}

output "instance_state_resource_id" {
  value = try(aws_ec2_instance_state.normally_stopped[0].id, null)
}

output "data_volume_id" {
  value = try(aws_ebs_volume.data[0].id, null)
}

output "project_bucket" {
  value = try(aws_s3_bucket.project[0].bucket, null)
}

output "workstation_role_name" {
  value = try(aws_iam_role.workstation[0].name, null)
}

output "budget_action_id" {
  value = try(aws_budgets_budget_action.stop_instance[0].action_id, null)
}

output "budget_name" {
  value = try(aws_budgets_budget.project[0].name, null)
}
