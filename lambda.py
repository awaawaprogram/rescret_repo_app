import json
import os
import boto3
import openai_secret_manager
from datetime import datetime

# Load OpenAI API key
assert "openai" in openai_secret_manager.get_services()
secrets = openai_secret_manager.get_secret("openai")

openai_api_key = secrets["api_key"]
model_engine = "text-davinci-002"

# Create OpenAI API client
openai = boto3.client("lambda", region_name="us-west-2")

# Create DynamoDB client
dynamodb = boto3.client('dynamodb', region_name='ap-northeast-1')

def lambda_handler(event, context):
    # Parse incoming LINE message
    body = json.loads(event["body"])
    reply_token = body["events"][0]["replyToken"]
    message_text = body["events"][0]["message"]["text"]
    user_id = body["events"][0]["source"]["userId"]
    
    # Store message in DynamoDB
    timestamp = datetime.utcnow().isoformat()
    item = {
        'user_id': {'S': user_id},
        'timestamp': {'S': timestamp},
        'message_text': {'S': message_text},
    }
    dynamodb.put_item(TableName=os.environ['DYNAMODB_TABLE_NAME'], Item=item)
    
    # Generate response using OpenAI API
    response = openai.invoke(
        FunctionName="text-generate",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "model_engine": model_engine,
            "prompt": message_text,
            "max_tokens": 50,
            "temperature": 0.7,
            "n": 1
        }),
    )
    response_payload = json.loads(response["Payload"].read().decode("utf-8"))
    generated_text = response_payload["body"]["choices"][0]["text"]
    
    # Store response in DynamoDB
    timestamp = datetime.utcnow().isoformat()
    item = {
        'user_id': {'S': user_id},
        'timestamp': {'S': timestamp},
        'message_text': {'S': generated_text},
    }
    dynamodb.put_item(TableName=os.environ['DYNAMODB_TABLE_NAME'], Item=item)
    
    # Construct LINE message object
    message = {
        "type": "text",
        "text": generated_text,
    }
    data = {
        "replyToken": reply_token,
        "messages": [message],
    }
    
    # Send response back to LINE
    client = boto3.client("lambda", region_name="ap-northeast-1")
    client.invoke(
        FunctionName=os.environ["LINE_LAMBDA_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps(data).encode("utf-8"),
    )

    return {"statusCode": 200}