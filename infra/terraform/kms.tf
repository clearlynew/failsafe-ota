resource "aws_kms_key" "release_signing" {
  description              = "failsafe-ota release manifest signing"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 7
}

resource "aws_kms_alias" "release_signing" {
  name          = "alias/${var.name_prefix}-release-signing"
  target_key_id = aws_kms_key.release_signing.key_id
}
