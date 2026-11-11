output "iot_endpoint" {
  value = data.aws_iot_endpoint.data.endpoint_address
}

output "bucket_name" {
  value = aws_s3_bucket.firmware.bucket
}

output "kms_key_id" {
  value = aws_kms_key.release_signing.key_id
}

output "kms_alias" {
  value = aws_kms_alias.release_signing.name
}

output "presign_role_arn" {
  value = aws_iam_role.iot_presign.arn
}

output "thing_group" {
  value = aws_iot_thing_group.fleet.name
}

# Public certificate material only, but the provider marks it sensitive, so confirm it here.
output "device_certificates" {
  value     = { for k, c in aws_iot_certificate.device : k => c.certificate_pem }
  sensitive = true
}
