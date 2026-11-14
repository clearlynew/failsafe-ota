variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type    = string
  default = "failsafe-ota"
}

variable "device_count" {
  type    = number
  default = 20
}
