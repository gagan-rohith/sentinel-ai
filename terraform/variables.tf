variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names and tags."
  type        = string
  default     = "demo"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.environment))
    error_message = "environment must be lowercase letters, digits and dashes."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "allowed_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the load balancer. Narrow this for real use."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS. When empty, the load balancer listens on HTTP only."
  type        = string
  default     = ""
}

variable "api_image_tag" {
  description = "Tag of the API image in the ECR repository."
  type        = string
  default     = "0.1.0"
}

variable "worker_image_tag" {
  description = "Tag of the worker image in the ECR repository."
  type        = string
  default     = "0.1.0"
}

variable "api_cpu" {
  description = "Fargate CPU units for the API task (1024 = 1 vCPU)."
  type        = number
  default     = 1024
}

variable "api_memory" {
  description = "Fargate memory for the API task in MiB. The embedding model needs about 1 GiB."
  type        = number
  default     = 2048
}

variable "elasticsearch_url" {
  description = <<-EOT
    URL of the Elasticsearch 8 cluster, for example an Elastic Cloud deployment. Amazon
    OpenSearch is not a drop-in replacement: the Elasticsearch 8 client refuses to talk
    to it, so this stack does not create one.
  EOT
  type        = string
}

variable "llm_model" {
  description = "Claude model used when ANTHROPIC_API_KEY is set in the app secret."
  type        = string
  default     = "claude-sonnet-5-5"
}

variable "log_retention_days" {
  description = "CloudWatch log retention."
  type        = number
  default     = 14
}
