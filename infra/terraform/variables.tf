variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name_prefix" {
  type    = string
  default = "failsafe-ota"
}

# Keep this equal to the N you pass to scripts/gen_device_csrs.sh.
# Use 3 for now; raise to 20 for the fleet demo on Day 4.
variable "device_count" {
  type    = number
  default = 3
}
