import base64
import hashlib
import hmac
import json
import requests
import boto3
import os
import time
from datetime import datetime


LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_COMPLETIONS_ENDPOINT = os.getenv('OPENAI_COMPLETIONS_ENDPOINT')
LINE_REPLY_ENDPOINT = os.getenv('LINE_REPLY_ENDPOINT')

CHAT_HISTORY_TABLE = 'chat_history'
USER_DATA_TABLE = 'user_data'
CHAT_ARCHIVE_TABLE = 'chat_archive'
PROMPT_ARCHIVE_TABLE = 'prompt_archive'

dynamodb = boto3.client('dynamodb', region_name='ap-southeast-2')
table_name = PROMPT_ARCHIVE_TABLE
prompt_table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    # LINEから送信された情報を取得
    body = json.loads(event['body'])
    user_id = body['events'][0]['source']['userId']
    text = body['events'][0]['message']['text']

    # DynamoDBに保存するデータを作成
    now = datetime.now()
    datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
    item = {
        'user_id': user_id,
        'datetime': datetime_str,
        'prompt': text
    }
    
    # DynamoDBにデータを保存
    prompt_table.put_item(Item=item)
    
    # DynamoDBから最新のデータを取得
    response = prompt_table.query(
        KeyConditionExpression='user_id = :uid',
        ExpressionAttributeValues={
            ':uid': user_id
        },
        Limit=1,
        ScanIndexForward=False
    )
    
    # フォームに表示するテキストを取得
    prompt = ""
    if len(response['Items']) > 0:
        prompt = response['Items'][0]['prompt']

    # 丸いボタンを含むFlex Messageを作成
    flex_message = {
        "type": "flex",
        "altText": "Prompt Form",
        "contents": {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": "https://example.com/images/boticon.png",
                "size": "full",
                "aspectRatio": "1:1",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": "Please enter your prompt:",
                        "weight": "bold",
                        "size": "lg",
                        "margin": "none",
                        "align": "center"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "md",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "text",
                                "text": "Prompt",
                                "size": "md",
                                "color": "#999999"
                            },
                            {
                                "type": "text",
                                "text": prompt,
                                "size": "lg",
                                "wrap": True,
                                "action": {
                                    "type": "message",
                                    "label": "Prompt",
                                    "text": "{{text}}"
                                }
                            },
                            {
                                "type": "separator"
                            }
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "md",
                        "spacing": "sm",
                        "contents": [
                            {
                                "type": "button",
                                "action": {
                                "type": "message",
                                "label": "Save",
                                "text": "{{text}}"
                            },
                            "color": "#00bfff",
                            "style": "primary"
                            }
                        ]
                    }
                ]
            }
        }
    }

    # Flex Messageを含むレスポンスを作成
    response_data = {
        'replyToken': body['events'][0]['replyToken'],
        'messages': [flex_message]
    }

    # LINEにレスポンスを返す
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + 'LINE_CHANNEL_ACCESS_TOKEN'
    }
    response = requests.post('https://api.line.me/v2/bot/message/reply', headers=headers, data=json.dumps(response_data))
    return {
        'statusCode': response.status_code,
        'body': response.text
    }
