resource "aws_s3_bucket" "firmware" {
  bucket        = "${var.name_prefix}-firmware-${local.account_id}-${var.region}"
  force_destroy = true # lets `terraform destroy` delete a bucket that still holds releases
}

resource "aws_s3_bucket_public_access_block" "firmware" {
  bucket                  = aws_s3_bucket.firmware.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "firmware" {
  bucket = aws_s3_bucket.firmware.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "firmware" {
  bucket = aws_s3_bucket.firmware.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}
