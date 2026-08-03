# Deploy PyKV to a single EC2 instance (all 3 nodes + dashboard on port 8001).
#
# Prereqs: AWS CLI installed and `aws configure` done; the repo pushed to GitHub.
# Usage:   .\deploy\deploy_ec2.ps1 -RepoUrl https://github.com/<you>/distributed-kv.git
#
# Cost: one t3.micro (~$0.0104/hr, free-tier eligible). Tear down with:
#   aws ec2 terminate-instances --instance-ids <id>

param(
    [Parameter(Mandatory = $true)][string]$RepoUrl,
    [string]$InstanceType = "t3.micro",
    [string]$Name = "pykv-demo"
)

$ErrorActionPreference = "Stop"

# Latest Amazon Linux 2023 AMI for the configured region
$ami = aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query "Parameter.Value" --output text
Write-Host "AMI: $ami"

# Security group: dashboard port 8001 only (no SSH; use EC2 Instance Connect / SSM if needed)
$vpc = aws ec2 describe-vpcs --filters Name=is-default,Values=true --query "Vpcs[0].VpcId" --output text
$sg = aws ec2 create-security-group --group-name "$Name-sg" --description "PyKV dashboard" --vpc-id $vpc --query GroupId --output text
aws ec2 authorize-security-group-ingress --group-id $sg --protocol tcp --port 8001 --cidr 0.0.0.0/0 | Out-Null
Write-Host "Security group: $sg (port 8001 open)"

# User data with the repo URL substituted
$userdata = (Get-Content "$PSScriptRoot\userdata.sh" -Raw) -replace "__REPO_URL__", $RepoUrl -replace "`r", ""
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($userdata))

$id = aws ec2 run-instances `
    --image-id $ami `
    --instance-type $InstanceType `
    --security-group-ids $sg `
    --user-data $b64 `
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$Name}]" `
    --query "Instances[0].InstanceId" --output text
Write-Host "Instance: $id — waiting for it to start..."

aws ec2 wait instance-running --instance-ids $id
$ip = aws ec2 describe-instances --instance-ids $id --query "Reservations[0].Instances[0].PublicIpAddress" --output text

Write-Host ""
Write-Host "==============================================="
Write-Host " Dashboard (allow ~2 min for first boot):"
Write-Host "   http://${ip}:8001"
Write-Host ""
Write-Host " Tear down when done:"
Write-Host "   aws ec2 terminate-instances --instance-ids $id"
Write-Host "==============================================="
