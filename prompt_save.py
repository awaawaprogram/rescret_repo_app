import os
import json
import boto3
import requests
import datetime


LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_COMPLETIONS_ENDPOINT = os.getenv('OPENAI_COMPLETIONS_ENDPOINT')
LINE_REPLY_ENDPOINT = os.getenv('LINE_REPLY_ENDPOINT')

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
PLAN_580_JPY = os.getenv('PLAN_580_JPY')
PLAN_1080_JPY = os.getenv('PLAN_1080_JPY')

CHAT_HISTORY_TABLE_NAME = 'chat_history'
USER_DATA_TABLE_NAME = 'user_data'
CHAT_ARCHIVE_TABLE_NAME = 'chat_archive'
PROMPT_ARCHIVE_TABLE_NAME = 'prompt_archive'


AWS_REGION = os.getenv('AWS_DB_REGION')  # 環境変数からリージョンを取得
dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION)

PROMPT_ARCHIVE_TABLE = dynamodb.Table(PROMPT_ARCHIVE_TABLE_NAME)
USER_DATA_TABLE = dynamodb.Table(USER_DATA_TABLE_NAME)



def send_reply_message(reply_token, messages):
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN}'
    }

    data = {
        'replyToken': reply_token,
        'messages': messages
    }
    try:
        response = requests.post(LINE_REPLY_ENDPOINT, headers=headers, json=data)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Request Headers: {headers}")
        print(f"Request Data: {data}")
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")
        raise e

def handle_message(body, event):
    body_json = json.loads(body)
    if 'events' not in body_json:
        print('events is not in body_json')
        return
    print(len(body_json['events']))
    print(body_json['events'])

    for e in body_json['events']:
        if e['type'] == 'message' and e['message']['type'] == 'text':
            user_id = e['source']['userId']
            reply_token = e['replyToken']
            if e['message']['text'] == 'system:prompt':
                request_prompt(reply_token)
                set_prompt_expected(user_id, True)
            else:
                prompt_expected = is_prompt_expected(user_id)
                if prompt_expected:
                    save_prompt(user_id, e['message']['text'], reply_token)
                    set_prompt_expected(user_id, False)
                else:
                    send_reply_message(
                        reply_token,
                        [{
                            'type': 'text',
                            'text': e['message']['text']
                        }]
                    )


def is_prompt_expected(user_id):
    response = USER_DATA_TABLE.get_item(
        Key={
            'user_id': user_id
        }
    )

    if 'Item' in response:
        return response['Item'].get('prompt_expected', False)
    else:
        return False


def set_prompt_expected(user_id, prompt_expected):
    timestamp = datetime.datetime.now()
    USER_DATA_TABLE.update_item(
        Key={
            'user_id': user_id
        },
        UpdateExpression='SET prompt_expected = :prompt_expected, last_updated = :last_updated',
        ExpressionAttributeValues={
            ':prompt_expected': prompt_expected,
            ':last_updated': timestamp.isoformat()
        }
    )

def request_prompt(reply_token):
    send_reply_message(
        reply_token,
        [{
            'type': 'text',
            'text': 'プロンプトを入力してください。'
        }]
    )



def save_prompt(user_id, prompt, reply_token):
    timestamp = datetime.datetime.now()

    try:
        print("Attempting to put item in PROMPT_ARCHIVE_TABLE")
        PROMPT_ARCHIVE_TABLE.put_item(
            Item={
                'user_id': user_id,
                'datetime': timestamp.isoformat(),
                'prompt': prompt
            }
        )
        print("Item put in PROMPT_ARCHIVE_TABLE successfully")

        print("Attempting to update item in USER_DATA_TABLE")
        USER_DATA_TABLE.update_item(
            Key={
                'user_id': user_id
            },
            UpdateExpression='SET prompt = :prompt, last_updated = :last_updated',
            ExpressionAttributeValues={
                ':prompt': prompt,
                ':last_updated': timestamp.isoformat()
            }
        )
        print("Item updated in USER_DATA_TABLE successfully")

        send_reply_message(
            reply_token,
            [{
                'type': 'text',
                'text': '保存が成功しました。'
            }]
        )
    except Exception as e:
        print(f"Error: {e}")
        send_reply_message(
            reply_token,
            [{
                'type': 'text',
                'text': '保存が失敗しました。'
            }]
        )



def lambda_handler(event, context):
    body = event['body']
    try:
        handle_message(body, event)
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 400, 'body': 'Error'}

    return {'statusCode': 200, 'body': 'OK'}
