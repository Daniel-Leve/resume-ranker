param([Parameter(Mandatory=$true)][string]$BucketName, [switch]$Apply)
$ErrorActionPreference='Stop'; $region='ap-south-1'; $stack='ai-resume-screening-phase1'
$awsCli='C:\Program Files\Amazon\AWSCLIV2\aws.exe'
if (-not (Test-Path -LiteralPath $awsCli)) { $awsCli=(Get-Command aws -ErrorAction Stop).Source }
# Codex's process inherited a dead localhost proxy. Removing it here affects this deployment process only.
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
$configured=(& $awsCli configure get region 2>$null); if ($configured -and $configured -ne $region) { throw "Configured region is $configured. This project requires $region." }
& $awsCli sts get-caller-identity --region $region | Out-Host
& $awsCli cloudformation validate-template --template-body file://phase1.yaml --region $region | Out-Host
if (-not $Apply) { Write-Host 'Template validated. No AWS resources were created. Re-run with -Apply only after cost review.'; exit 0 }
& $awsCli cloudformation deploy --stack-name $stack --template-file phase1.yaml --parameter-overrides BucketName=$BucketName --capabilities CAPABILITY_NAMED_IAM --region $region --no-fail-on-empty-changeset
