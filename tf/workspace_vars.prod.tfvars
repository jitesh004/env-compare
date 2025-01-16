# AWS Account Information for Production Environment
aws_account = {
  id      = "987654321098"
  region  = "us-west-2"
  profile = "prod"
}

# S3 Buckets Configuration
s3_buckets = [
  {
    name = "prod-app-bucket"
    region = "us-west-2"
    versioning = true
    tags = {
      Environment = "prod"
      Owner       = "team"
    }
  },
  {
    name = "prod-logs-bucket"
    region = "us-east-1"
    versioning = true
    tags = {
      Environment = "prod"
      Owner       = "team-prod-logs"
    }
  }
]

# Database Configuration
db_config = {
  engine   = "mysql"
  version  = "8.0"
  instance = {
    type        = "db.r5.large"
    identifier  = "prod-db-instance"
    storage     = 500
    multi_az    = true
    backup_retention = 14
  }
}

# List of EC2 Instance Types for Scaling
ec2_instance_types = ["m5.large", "m5.xlarge", "m5.2xlarge"]

# Number of Instances in Autoscaling Group
autoscaling_min_size = 4
autoscaling_max_size = 10

# Nested object for VPC Configuration
vpc_config = {
  cidr_block = "192.168.0.0/16"
  subnets = [
    {
      name = "prod-public-subnet-1"
      cidr = "192.168.1.0/24"
      availability_zone = "us-east-1a"
    },
    {
      name = "prod-private-subnet-1"
      cidr = "192.168.2.0/24"
      availability_zone = "us-east-1b"
    }
  ]
}

# Feature Flags
enable_feature_x = true
enable_feature_y = true

accountId = "6746632.aws.fan.com@234"

prodId = "poj"