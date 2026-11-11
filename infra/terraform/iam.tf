# Role that IoT Jobs assumes to turn S3 objects into presigned URLs.
data "aws_iam_policy_document" "iot_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["iot.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "iot_presign" {
  name               = "${var.name_prefix}-iot-presign"
  assume_role_policy = data.aws_iam_policy_document.iot_assume.json
}

data "aws_iam_policy_document" "presign_s3" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.firmware.arn}/releases/*"]
  }
}

resource "aws_iam_role_policy" "iot_presign" {
  name   = "read-releases"
  role   = aws_iam_role.iot_presign.id
  policy = data.aws_iam_policy_document.presign_s3.json
}
