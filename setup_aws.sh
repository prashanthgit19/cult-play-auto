#!/bin/bash
set -e

REGION="ap-south-1"
FUNCTION_NAME="cult-play-auto"
RULE_NAME="cult-play-daily-9pm-ist"
ROLE_NAME="cult-play-auto-lambda-role"
SCHEDULE="cron(25 15 * * ? *)"

echo "=== Cult.fit Play Auto-Booking: AWS Setup ==="
echo ""

if ! command -v aws &>/dev/null; then
    echo "ERROR: AWS CLI not installed."
    echo "Install it with: brew install awscli"
    echo "Then run: aws configure"
    exit 1
fi

if ! aws sts get-caller-identity &>/dev/null; then
    echo "ERROR: AWS CLI not configured."
    echo "Run: aws configure"
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null)
echo "Account: $ACCOUNT_ID"
echo "Region: $REGION"
echo ""

echo "--- Step 1: Create IAM Role ---"
ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text 2>/dev/null || echo "")
if [ -n "$ROLE_ARN" ]; then
    echo "Role already exists: $ROLE_ARN"
else
    TRUST_POLICY='{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }'
    ROLE_ARN=$(aws iam create-role \
        --role-name "$ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --query Role.Arn --output text)
    echo "Created role: $ROLE_ARN"

    aws iam attach-role-policy \
        --role-name "$ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    echo "Attached Lambda execution policy"

    echo "Waiting 10s for role propagation..."
    sleep 10
fi

echo ""
echo "--- Step 2: Build deployment package ---"
rm -rf /tmp/cult-play-deploy
mkdir -p /tmp/cult-play-deploy
cp lambda_function.py /tmp/cult-play-deploy/
cp notify.py /tmp/cult-play-deploy/

pip install requests -t /tmp/cult-play-deploy/ --quiet 2>/dev/null || pip3 install requests -t /tmp/cult-play-deploy/ --quiet

cd /tmp/cult-play-deploy
zip -r /tmp/cult-play-deploy.zip . -q
cd -
echo "Package created: /tmp/cult-play-deploy.zip"
ls -lh /tmp/cult-play-deploy.zip

echo ""
echo "--- Step 3: Create/update Lambda function ---"
EXISTING=$(aws lambda get-function --function-name "$FUNCTION_NAME" --query Configuration.FunctionArn --output text 2>/dev/null || echo "")
if [ -n "$EXISTING" ]; then
    echo "Updating existing function: $EXISTING"
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file fileb:///tmp/cult-play-deploy.zip \
        --region "$REGION" \
        --query FunctionArn --output text
    echo "Waiting for update to complete..."
    sleep 5
    aws lambda update-function-configuration \
        --function-name "$FUNCTION_NAME" \
        --timeout 60 \
        --region "$REGION" || true
else
    echo "Creating new function..."
    aws lambda create-function \
        --function-name "$FUNCTION_NAME" \
        --runtime python3.12 \
        --role "$ROLE_ARN" \
        --handler lambda_function.lambda_handler \
        --zip-file fileb:///tmp/cult-play-deploy.zip \
        --timeout 60 \
        --region "$REGION" \
        --query FunctionArn --output text
    echo "Function created."
fi

echo ""
echo "--- Step 4: Set environment variables ---"
read -p "Enter your CULT_AT_COOKIE (CFAPP:...): " AT_COOKIE
read -p "Enter GMAIL_ADDRESS: " GMAIL_ADDR
read -sp "Enter GMAIL_APP_PASSWORD: " GMAIL_PASS
echo ""
read -p "Enter NOTIFY_EMAIL (default: $GMAIL_ADDR): " NOTIFY
NOTIFY=${NOTIFY:-$GMAIL_ADDR}

ENV_JSON=$(cat <<EOF
{"CULT_AT_COOKIE":"$AT_COOKIE","CULT_CENTER_IDS":"1107","CULT_PREFERRED_TIMES":"19:00:00,20:00:00","CULT_WORKOUT_IDS":"350","CULT_MAX_RETRIES":"3","CULT_RETRY_DELAY":"5","GMAIL_ADDRESS":"$GMAIL_ADDR","GMAIL_APP_PASSWORD":"$GMAIL_PASS","NOTIFY_EMAIL":"$NOTIFY"}
EOF
)

aws lambda update-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --region "$REGION" \
    --environment "{\"Variables\":$ENV_JSON}" --output text

echo "Environment variables set."

echo ""
echo "--- Step 5: Create EventBridge scheduled rule ---"
aws events put-rule \
    --name "$RULE_NAME" \
    --schedule-expression "$SCHEDULE" \
    --region "$REGION" \
    --state ENABLED \
    --query RuleArn --output text 2>/dev/null || echo "Rule may already exist"
echo "Rule created: $SCHEDULE (fires at 3:25 PM UTC = 8:55 PM IST)"

LAMBDA_ARN="arn:aws:lambda:$REGION:$ACCOUNT_ID:function:$FUNCTION_NAME"
aws lambda add-permission \
    --function-name "$FUNCTION_NAME" \
    --statement-id EventBridgeInvoke \
    --action lambda:InvokeFunction \
    --principal events.amazonaws.com \
    --source-arn "arn:aws:events:$REGION:$ACCOUNT_ID:rule/$RULE_NAME" \
    --region "$REGION" 2>/dev/null || echo "Permission may already exist"

aws events put-targets \
    --rule "$RULE_NAME" \
    --targets "[{\"Id\":\"1\",\"Arn\":\"$LAMBDA_ARN\"}]" \
    --region "$REGION" --output text 2>/dev/null || echo "Target may already exist"

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Lambda function: $FUNCTION_NAME"
echo "EventBridge rule: $RULE_NAME (8:55 PM IST daily)"
echo ""
echo "Useful commands:"
echo "  Test run:   aws lambda invoke --function-name $FUNCTION_NAME --region $REGION /tmp/response.json && cat /tmp/response.json"
echo "  View logs:  aws logs tail /aws/lambda/$FUNCTION_NAME --region $REGION"
echo "  Update env:  aws lambda update-function-configuration --function-name $FUNCTION_NAME --region $REGION --environment Variables='{...}'"
echo "  Update code: ./deploy.sh"