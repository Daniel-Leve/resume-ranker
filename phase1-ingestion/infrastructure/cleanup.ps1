param([Parameter(Mandatory=$true)][string]$BucketName)
$ErrorActionPreference='Stop'; $region='ap-south-1'; $stack='ai-resume-screening-phase1'
$awsCli='C:\Program Files\Amazon\AWSCLIV2\aws.exe'
if (-not (Test-Path -LiteralPath $awsCli)) { $awsCli=(Get-Command aws -ErrorAction Stop).Source }
Remove-Item Env:HTTP_PROXY,Env:HTTPS_PROXY,Env:ALL_PROXY -ErrorAction SilentlyContinue
$answer=Read-Host "Type DELETE $BucketName to permanently remove all objects and stacks"
if ($answer -ne "DELETE $BucketName") { throw 'Cleanup cancelled.' }
& $awsCli cloudformation delete-stack --stack-name $stack --region $region
& $awsCli cloudformation wait stack-delete-complete --stack-name $stack --region $region
& $awsCli s3 rm "s3://$BucketName" --recursive --region $region
& $awsCli s3api delete-bucket --bucket $BucketName --region $region
