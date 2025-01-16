# AWS Account Information for Acceptance Environment
aws_account = {
  id      = "123456789012"
  region  = "us-west-2"
  profile = "acpt"
}

# S3 Buckets Configuration
s3_buckets = [
  {
    name = "acpt-app-bucket"
    region = "us-west-2"
    versioning = true
    tags = {
      Environment = "acpt"
      Owner       = "team"
    }
  },
  {
    name = "acpt-logs-bucket"
    region = "us-west-2"
    versioning = false
    tags = {
      Environment = "acpt"
      Owner       = "team-acpt-logs"
    }
  }
]

# Database Configuration
db_config = {
  engine   = "postgres"
  version  = "13.3"
  instance = {
    type        = "db.t3.medium"
    identifier  = "acpt-db-instance"
    storage     = 100
    multi_az    = false
    backup_retention = 7
  }
}

# List of EC2 Instance Types for Scaling
ec2_instance_types = ["t2.micro", "t2.small", "t2.medium"]

# Number of Instances in Autoscaling Group
autoscaling_min_size = 2
autoscaling_max_size = 5

# Nested object for VPC Configuration
vpc_config = {
  cidr_block = "10.0.0.0/16"
  subnets = [
    {
      name = "acpt-public-subnet-1"
      cidr = "10.0.1.0/24"
      availability_zone = "us-west-2a"
    },
    {
      name = "acpt-private-subnet-1"
      cidr = "10.0.2.0/24"
      availability_zone = "us-west-2b"
    }
  ]
}

# Feature Flags
enable_feature_x = true
enable_feature_y = false


accountId = "1234567.aws.fan.com@224"

someId = "kjl"