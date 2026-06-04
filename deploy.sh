#!/bin/bash
set -e

REGION="eu-north-1"
FUNCTION_NAME="cult-play-auto"

echo "=== Deploying cult-play-auto to AWS Lambda ==="

rm -rf /tmp/cult-play-deploy
mkdir -p /tmp/cult-play-deploy
cp lambda_function.py /tmp/cult-play-deploy/
cp notify.py /tmp/cult-play-deploy/

echo "Installing dependencies..."
pip install requests -t /tmp/cult-play-deploy/ --quiet 2>/dev/null || pip3 install requests -t /tmp/cult-play-deploy/ --quiet

cd /tmp/cult-play-deploy
rm -f /tmp/cult-play-deploy.zip
zip -r /tmp/cult-play-deploy.zip . -q
cd -
echo "Package: /tmp/cult-play-deploy.zip ($(du -h /tmp/cult-play-deploy.zip | cut -f1))"

echo "Updating Lambda function..."
aws lambda update-function-code \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb:///tmp/cult-play-deploy.zip \
    --region "$REGION" \
    --query FunctionArn --output text

echo ""
echo "Deployed! To test: aws lambda invoke --function-name $FUNCTION_NAME --region $REGION /tmp/response.json && cat /tmp/response.json"