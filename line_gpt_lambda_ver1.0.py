import base64
import hashlib
import hmac
import json
import requests
import boto3
import os
import time

LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_COMPLETIONS_ENDPOINT = os.getenv('OPENAI_COMPLETIONS_ENDPOINT')
LINE_REPLY_ENDPOINT = os.getenv('LINE_REPLY_ENDPOINT')

dynamo = boto3.client('dynamodb', region_name='ap-southeast-2')

TABLE_NAME='chat_history'

def validate_type(event):
    print('validate_type')
    type = json.loads(event['body'])['events'][0]['type']
    if type != 'message':
        raise Exception('Invalid LINE event type')


def validate_signature(event):
    return
    print('validate_signature')
    body = event['body'] # Request body string
    hash = hmac.new(LINE_CHANNEL_SECRET.encode('utf-8'),
        body.encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(hash)
    if signature != event['headers']['x-line-signature']:
        raise Exception('Invalid signature')
        

def populate_conversation(user_id, message):
    print('generate_query - start')
    try:
        history = dynamo.get_item(
            TableName=TABLE_NAME,
            Key={
                'user_id': {
                    'S': user_id,
                }
            }
        ).get('Item').get('conversation').get('S')
        query = history + '\nHuman: ' + message
    except Exception as e:
        print(e)
        query = '\nHuman: {}'.format(message)
    print('generate_query - done: {}'.format(query))
    return query

def openai_completions(prompt):
    print('openai_completions')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer {}'.format(OPENAI_API_KEY)
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 1000,
    }
    try:
        openai_response = requests.post(OPENAI_COMPLETIONS_ENDPOINT, headers=headers, data=json.dumps(data))
        print('OpenAI response: {}'.format(openai_response.json()))
        if openai_response.json()['choices'][0]['message']['content'].split("AI: ")[-1] is None:
            raise Exception('OpenAI response is empty')
        return openai_response
    except:
        return 'OpenAIが壊れてました😢'

def format_openai_response(openai_response):
        message = openai_response.json()['choices'][0]['message']['content'].split("AI: ")[-1]
        return message

def get_openai_cost_jpy(openai_response):
    cost_jpy = openai_response.json()['usage']['total_tokens'] * 0.000002 * 135
    return cost_jpy

def store_conversation(user_id, query, openai_response):
    print('store_conversation')
    try:
        dynamo.put_item(
        TableName=TABLE_NAME,
        Item={
            'user_id': {
                'S': user_id,
            },
            'conversation': {
                'S': query + openai_response.json()['choices'][0]['message']['content'],
            }
        }
    )
    except:
        print('failed to store conversation')

def line_reply(reply_token, response, cost_jpy):
    Authorization = 'Bearer {}'.format(LINE_CHANNEL_ACCESS_TOKEN)
    headers = {
        'Content-Type': 'application/json; charset=UTF-8',
        'Authorization': Authorization
    }
    data = {
        "replyToken": reply_token,
        "messages": [
                    {
                        "type":"text",
                        "text":response
                    },
                    {
                        "type": "template",
                        "altText": response,
                        "template": {
                            "type": "buttons",
                            "text": 'AI利用料は {} 円でした💰\n会話をリセットしますか？'.format(round(cost_jpy, 3)),
                            "actions": [
                                {
                                    "type": "message",
                                    "label": "リセットする",
                                    "text": "reset"
                                }
                            ]
                        }
                    }
                    ]
        }
    r = requests.post(LINE_REPLY_ENDPOINT, headers=headers, data=json.dumps(data))
    print('LINE response: {}'.format(r.json()))

def archive_conversation(user_id):
    try:
        history = dynamo.get_item(
            TableName=TABLE_NAME,
            Key={
                'user_id': {
                    'S': user_id,
                }
            }
        ).get('Item').get('conversation').get('S')

        dynamo.put_item(
            TableName=TABLE_NAME,
            Item={
                'user_id': {
                    'S': user_id + "-" + str(int(time.time())),
                },
                'conversation': {
                    'S': history,
                }
            }
        )
    except Exception as e:
        print('failed to archive conversation: {}'.format(e))

    dynamo.delete_item(
            TableName=TABLE_NAME,
            Key={
                'user_id': {
                    'S': user_id,
                }
            }
        )

def lambda_handler(event, context):
    print(event)

    try:
        validate_type(event)
        validate_signature(event)
        user_id = json.loads(event['body'])['events'][0]['source']['userId']
        message = json.loads(event['body'])['events'][0]['message']['text']
        reply_token = json.loads(event['body'])['events'][0]['replyToken']
        if user_id is None or message is None or reply_token is None:
            raise Exception('Empty request')

    except:
        return {
            'statusCode': 400
        }

    if message == 'reset':
        archive_conversation(user_id)
        return {
            'statusCode': 200
        }

    try:
        query = populate_conversation(user_id, message)
        openai_response = openai_completions(query)
        response = format_openai_response(openai_response)
        cost_jpy = get_openai_cost_jpy(openai_response)
        store_conversation(user_id, query, openai_response)
    except:
        cost_jpy = 0
        response = 'OpenAIが壊れてました😢'
    
    line_reply(reply_token, response, cost_jpy)

    return {
        'statusCode': 200,
    }