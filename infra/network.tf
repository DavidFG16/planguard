# =============================================================================
# Networking of the fictional company "Acme Health".
#
#   shared  10.10.0.0/16  Tools VPC (CI runners, VPN, BI dashboard).
#                         PUBLIC subnets that reach the internet through an
#                         Internet Gateway. There is NO NAT gateway, by design.
#   dev     10.20.0.0/16  Private subnets, no internet route.
#   prod    10.30.0.0/16  Private subnets, no internet route.
#
# Everything in this file is free: VPCs, subnets, route tables, internet
# gateways and security groups cost nothing until something runs inside them.
# =============================================================================

# ---------------------------------------------------------------- shared VPC

resource "aws_vpc" "shared" {
  cidr_block           = "10.10.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "acme-shared"
    Environment = "shared"
  }
}

locals {
  shared_public_subnets = {
    a = { cidr = "10.10.1.0/24", az = local.azs[0] }
    b = { cidr = "10.10.2.0/24", az = local.azs[1] }
  }
}

resource "aws_subnet" "shared_public" {
  for_each = local.shared_public_subnets

  vpc_id                  = aws_vpc.shared.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = false # tools request public IPs explicitly, never by default

  tags = {
    Name        = "acme-shared-public-${each.key}"
    Environment = "shared"
    Tier        = "public"
    Workloads   = "ci-runner,vpn,bi-dashboard"
  }
}

resource "aws_internet_gateway" "shared" {
  vpc_id = aws_vpc.shared.id

  tags = {
    Name        = "acme-shared-igw"
    Environment = "shared"
  }
}

resource "aws_route_table" "shared_public" {
  vpc_id = aws_vpc.shared.id

  tags = {
    Name        = "acme-shared-public-rt"
    Environment = "shared"
  }
}

# The default route is its own resource (not inline in the route table), so a
# change of target shows up in a plan as a clear in-place update.
# EVERY tool in the shared VPC reaches the internet through this route.
resource "aws_route" "shared_public_default" {
  route_table_id         = aws_route_table.shared_public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.shared.id
}

resource "aws_route_table_association" "shared_public" {
  for_each = aws_subnet.shared_public

  subnet_id      = each.value.id
  route_table_id = aws_route_table.shared_public.id
}

# Security groups of the tools that live in the shared subnets. They are empty
# placeholders (free), but they tell a reviewer WHAT depends on this network.
locals {
  shared_tools = {
    "ci-runner"    = "CI runners that build and deploy every app"
    "vpn"          = "Client VPN that engineers use to reach private resources"
    "bi-dashboard" = "BI dashboard used by the analytics team"
  }
}

resource "aws_security_group" "shared_tools" {
  for_each = local.shared_tools

  name        = "acme-shared-${each.key}"
  description = each.value
  vpc_id      = aws_vpc.shared.id

  tags = {
    Name        = "acme-shared-${each.key}"
    Environment = "shared"
    Workload    = each.key
  }
}

# ----------------------------------------------------------- dev / prod VPCs

locals {
  env_networks = {
    dev = {
      environment = "development"
      cidr        = "10.20.0.0/16"
      subnets     = { a = "10.20.1.0/24", b = "10.20.2.0/24" }
    }
    prod = {
      environment = "production"
      cidr        = "10.30.0.0/16"
      subnets     = { a = "10.30.1.0/24", b = "10.30.2.0/23" }
    }
  }

  # Flattens env_networks into one entry per subnet: "dev-a", "dev-b", "prod-a", "prod-b".
  env_private_subnets = merge([
    for env, net in local.env_networks : {
      for key, cidr in net.subnets : "${env}-${key}" => {
        env  = env
        cidr = cidr
        az   = local.azs[key == "a" ? 0 : 1]
      }
    }
  ]...)
}

resource "aws_vpc" "env" {
  for_each = local.env_networks

  cidr_block           = each.value.cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "acme-${each.key}"
    Environment = each.value.environment
  }
}

resource "aws_subnet" "private" {
  for_each = local.env_private_subnets

  vpc_id            = aws_vpc.env[each.value.env].id
  cidr_block        = each.value.cidr
  availability_zone = each.value.az

  tags = {
    Name        = "acme-${each.key}-private"
    Environment = local.env_networks[each.value.env].environment
    Tier        = "private"
  }
}

# Private route tables only have the implicit "local" route: no internet access.
resource "aws_route_table" "private" {
  for_each = local.env_networks

  vpc_id = aws_vpc.env[each.key].id

  tags = {
    Name        = "acme-${each.key}-private-rt"
    Environment = each.value.environment
  }
}

resource "aws_route_table_association" "private" {
  for_each = local.env_private_subnets

  subnet_id      = aws_subnet.private[each.key].id
  route_table_id = aws_route_table.private[each.value.env].id
}
