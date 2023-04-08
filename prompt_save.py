import os
import json
import boto3
import requests


LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_COMPLETIONS_ENDPOINT = os.getenv('OPENAI_COMPLETIONS_ENDPOINT')
LINE_REPLY_ENDPOINT = os.getenv('LINE_REPLY_ENDPOINT')

STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
PLAN_580_JPY = os.getenv('PLAN_580_JPY')
PLAN_1080_JPY = os.getenv('PLAN_1080_JPY')

CHAT_HISTORY_TABLE = 'chat_history'
USER_DATA_TABLE = 'user_data'
CHAT_ARCHIVE_TABLE = 'chat_archive'
PROMPT_ARCHIVE_TABLE = 'prompt_archive'


dynamodb = boto3.resource('dynamodb')

PROMPT_ARCHIVE_TABLE = dynamodb.Table(PROMPT_ARCHIVE_TABLE)
USER_DATA_TABLE = dynamodb.Table(USER_DATA_TABLE)


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
            if e['message']['text'] == '文章を入力':
                print('send input form')
                send_input_form(user_id, reply_token)
            elif e['message']['text'].startswith('文章を送信: '):
                prompt = e['message']['text'][9:]
                save_prompt(user_id, prompt, reply_token)


def send_input_form(user_id, reply_token):
    try:
        saved_prompt = get_saved_prompt(user_id)
    except:
        saved_prompt = ''

    if not saved_prompt:
        saved_prompt = 'ここに入力してください'

    send_reply_message(
        reply_token,
        [
            {
                "type": "text",
                "text": "文章を入力してください。"
            },
            {
                "type": "text",
                "text": saved_prompt,
                "quickReply": {
                    "items": [
                        {
                            "type": "action",
                            "action": {
                                "type": "message",
                                "label": "文章を送信",
                                "text": "文章を送信"
                            }
                        }
                    ]
                }
            }
        ]
    )


    send_reply_message(
        reply_token,
        [{
            'type': 'flex',
            'altText': '入力フォーム',
            'contents': flex_message
        }]
    )



def get_saved_prompt(user_id):
    response = USER_DATA_TABLE.get_item(
        Key={
            'user_id': user_id
        }
    )

    if 'Item' in response:
        return response['Item'].get('prompt', '')
    else:
        return ''


def handle_postback(body, event):
    body_json = json.loads(body)
    if 'events' not in body_json:
        return

    for e in body_json['events']:
        if e['type'] == 'postback' and e['postback']['data'] == 'action=submit_prompt':
            user_id = e['source']['userId']
            reply_token = e['replyToken']
            prompt = e['postback']['params']['text']
            save_prompt(user_id, prompt, reply_token)



def save_prompt(user_id, prompt, reply_token):
    timestamp = datetime.datetime.now()

    PROMPT_ARCHIVE_TABLE.put_item(
        Item={
            'user_id': user_id,
            'datetime': timestamp.isoformat(),
            'prompt': prompt
        }
    )

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

    send_reply_message(
        reply_token,
        [{
            'type': 'text',
            'text': '文章が保存されました'
        }]
    )



def lambda_handler(event, context):
    body = event['body']
    try:
        handle_message(body, event)
        handle_postback(body, event)
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 400, 'body': 'Error'}
    
    return {'statusCode': 200, 'body': 'OK'}
