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
CHAT_HISTORY_TABLE = dynamodb.Table(CHAT_HISTORY_TABLE_NAME)
CHAT_ARCHIVE_TABLE = dynamodb.Table(CHAT_ARCHIVE_TABLE_NAME)

NUM_ITEMS = 5
MAX_WORD = 1000

def lambda_handler(event, context):
    body = event['body']
    body_json = json.loads(body)
    try:
        for e in body_json['events']:
            if e['type'] == 'message' and e['message']['type'] == 'text':
                user_id = e['source']['userId']
                reply_token = e['replyToken']
                message = e['message']['text']
                if user_id is None or message is None or reply_token is None:
                    raise Exception('Empty request')
                
                print('reset')
                if message == 'reset':
                    handle_reset_conversation(user_id, reply_token)
                    return {'statusCode': 200 }
                
                print('prompt')
                if message == 'system:prompt':
                    handle_prompt_input(reply_token, user_id)
                    return {'statusCode': 200 }
                
                else:
                    print('user_data')
                    user_data = get_user_data(user_id)
                    print('prompt expected')
                    prompt_expected = is_prompt_expected(user_data)
                    print('finish expected')
                    if prompt_expected:
                        handle_prompt_save(reply_token, user_id, e)
                    else:
                        handle_response(user_id, message, reply_token, user_data)

        
    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 400, 'body': 'Error'}

    return {'statusCode': 200, 'body': 'OK'}



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




def handle_reset_conversation(user_id, reply_token):
    try:
        CHAT_HISTORY_TABLE.update_item(
            Item={
                'user_id': user_id,
                'conversation': ' ',
                'datetime': datetime.datetime.now().isoformat()
            }
        )
        send_reply_message(
            reply_token,
            [{
                'type': 'text',
                'text': '会話をリセットしました。'
            }]
        )
    except Exception as e:
        print('failed to archive conversation: {}'.format(e))
        send_reply_message(
            reply_token,
            [{
                'type': 'text',
                'text': '会話をリセットに失敗しました。'
            }]
        )



def is_prompt_expected(user_data):
    print(user_data)
    if 'Item' in user_data:
        return user_data['Item'].get('prompt_expected', False)
    else:
        return False



def handle_prompt_input(reply_token, user_id):
    request_prompt(reply_token)
    set_prompt_expected(user_id, True)


def handle_prompt_save(reply_token, user_id,e):
    save_prompt(user_id, e['message']['text'], reply_token)
    set_prompt_expected(user_id, False)


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
    prompt = prompt[:MAX_WORD]

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
                'text': '保存が成功しました。\\n'+prompt
            }]
        )
    except Exception as e:
        print(f"Error: {e}")
        send_reply_message(
            reply_token,
            [{
                'type': 'text',
                'text': '保存が失敗しました。'+prompt
            }]
        )




def handle_response(user_id, message, reply_token, user_data):
    try:
        prompt = user_data['Item'].get('prompt', False)
        query = populate_conversation(user_id, message, prompt)
        print(query)
        openai_response = openai_completions(query)
        response = format_openai_response(openai_response)
        cost_jpy = get_openai_cost_jpy(openai_response)
        print('cost:',cost_jpy)
        store_conversation(user_id, message, openai_response)
    except Exception as e:
        print(f"Error: {e}")
        cost_jpy = 0
        response = 'OpenAIが壊れてました😢'
        
    send_reply_message(
        reply_token,
        [{
            'type': 'text',
            'text': response
        }]
    )
    
    return {'statusCode': 200 }


def get_user_data(user_id):
    user_data = USER_DATA_TABLE.get_item(
        Key={
            'user_id': user_id
        }
    )
    return user_data


def get_prompt(user_data):
    print(user_data)
    if 'Item' in user_data:
        return user_data['Item'].get('prompt_expected', False)
    else:
        return False


def populate_conversation(user_id, message, prompt):
    print('generate_query - start')
    try:
        history = CHAT_ARCHIVE_TABLE.query(
            TableName=CHAT_ARCHIVE_TABLE_NAME,
            KeyConditionExpression="user_id = :user_id",
            ExpressionAttributeValues={":user_id": user_id},
            ScanIndexForward=False,
            Limit=NUM_ITEMS,
        ).get('Items')
        print(history)
        history_sorted = sorted(history, key=lambda x: datetime.datetime.fromisoformat(x['datetime']))
        query = [{'role':'system','content': prompt}] +[{'role':h['role'], 'content':h['conversation']} for h in history_sorted] + [{'role':'user','content': message}]
    except Exception as e:
        print(e)
        query = [
            {'role':'system','content': prompt},
            {'role':'user','content': message}
        ]
    print('generate_query - done: {}'.format(str(query)))
    return query


def openai_completions(prompt):
    print('openai_completions')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer {}'.format(OPENAI_API_KEY)
    }
    data = {
        "model": "gpt-3.5-turbo",
        "messages": prompt,
        "max_tokens": 1000,
    }
    try:
        openai_response = requests.post(OPENAI_COMPLETIONS_ENDPOINT, headers=headers, data=json.dumps(data))
        print(type(openai_response))
        print('OpenAI response: {}'.format(openai_response.json()))
        if openai_response.json()['choices'][0]['message']['content'] is None:
            raise Exception('OpenAI response is empty')
        print(type(openai_response))
        return openai_response
    except Exception as e:
        print(e)
        return 'OpenAIが壊れてました😢'


def format_openai_response(openai_response):
    message = openai_response.json()['choices'][0]['message']['content']
    return message

def get_openai_cost_jpy(openai_response):
    cost_jpy = openai_response.json()['usage']['total_tokens'] * 0.000002 * 135
    return cost_jpy

def store_conversation(user_id, message, openai_response):
    print('store_conversation')
    try:
        CHAT_ARCHIVE_TABLE.put_item(
            Item={
                'user_id': user_id,
                'role': 'user',
                'conversation': message,
                'token_count': openai_response.json()['usage']['prompt_tokens'],
                'datetime': datetime.datetime.now().isoformat(),
            }
        )
        CHAT_ARCHIVE_TABLE.put_item(
            Item={
                'user_id': user_id,
                'role': openai_response.json()['choices'][0]['message']['role'],
                'conversation': openai_response.json()['choices'][0]['message']['content'],
                'token_count': openai_response.json()['usage']['completion_tokens'],
                'datetime': datetime.datetime.now().isoformat(),
            }
        )
    except Exception as e:
        print(e)
        print('failed to store conversation')

