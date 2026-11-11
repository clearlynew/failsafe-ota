locals {
  devices = toset([for i in range(1, var.device_count + 1) : format("device-%03d", i)])
}

resource "aws_iot_thing_group" "fleet" {
  name = "fleet-a"
}

resource "aws_iot_thing" "device" {
  for_each = local.devices
  name     = each.key
}

resource "aws_iot_thing_group_membership" "device" {
  for_each         = local.devices
  thing_name       = aws_iot_thing.device[each.key].name
  thing_group_name = aws_iot_thing_group.fleet.name
}

# Device private keys never enter Terraform state: certificates are made from
# CSRs generated locally by scripts/gen_device_csrs.sh.
resource "aws_iot_certificate" "device" {
  for_each = local.devices
  csr      = file("${path.root}/../../build/devices/${each.key}/device.csr")
  active   = true
}

# Least privilege: each device may only use its own topics. The $${...} escape stops
# Terraform interpolating the IoT policy variable.
resource "aws_iot_policy" "device" {
  name = "${var.name_prefix}-device"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iot:Connect"
        Resource = "arn:aws:iot:${var.region}:${local.account_id}:client/$${iot:Connection.Thing.ThingName}"
      },
      {
        Effect   = "Allow"
        Action   = ["iot:Publish", "iot:Receive"]
        Resource = "arn:aws:iot:${var.region}:${local.account_id}:topic/$aws/things/$${iot:Connection.Thing.ThingName}/*"
      },
      {
        Effect   = "Allow"
        Action   = "iot:Subscribe"
        Resource = "arn:aws:iot:${var.region}:${local.account_id}:topicfilter/$aws/things/$${iot:Connection.Thing.ThingName}/*"
      }
    ]
  })
}

resource "aws_iot_policy_attachment" "device" {
  for_each = local.devices
  policy   = aws_iot_policy.device.name
  target   = aws_iot_certificate.device[each.key].arn
}

resource "aws_iot_thing_principal_attachment" "device" {
  for_each  = local.devices
  thing     = aws_iot_thing.device[each.key].name
  principal = aws_iot_certificate.device[each.key].arn
}

data "aws_iot_endpoint" "data" {
  endpoint_type = "iot:Data-ATS"
}
