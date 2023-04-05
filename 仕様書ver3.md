【概要】
本仕様書では、LINE Messaging APIとOpenAIを使用して、AWS Lambda上で動作するチャットボットの作成手順を解説します。本チャットボットは、ステートフルな会話をDynamoDBに保存し、自然な返答を生成するChatGPTを使用します。

【前提条件】
- AWSアカウントを所有していること
- LINEアカウントを所有していること
- OpenAI APIキーを取得していること

【手順】

1. OpenAI APIキーを取得する
- 下記URLから取得可能
https://platform.openai.com/account/api-keys

2. LINE Botを作成する
- LINE Developersにアクセスし、「新しいProviderを作成」する
- 「Messaging API Channel」を作成する
  - 必要事項を入力し、Channel access tokenを取得する

3. AWS Lambda Functionを作成する
- 新しいLambda Functionを作成する
- Pythonを選択し、関数名を任意に決定する
- Enable function URLを設定し、Lambdaの環境変数にLINE_CHANNEL_ACCESS_TOKEN、LINE_CHANNEL_SECRET、LINE_REPLY_ENDPOINT、OPENAI_API_KEY、OPENAI_COMPLETIONS_ENDPOINTを設定する

4. Requestsモジュールを使うためのLayerを追加する
- Layerを追加し、適切なRoleを作成する
- 関数にLayerを追加する

5. LINE側のWebhook URLを設定する
- AWSで取得したFunction URLを、LINEのWebhook URLにセットする

6. LINE Botの挙動を設定する
- オウム返しの場合は、pingpong.pyをLambdaにアップロードする
- OpenAIを使用する場合は、stateless_openai_chat.pyとlambda_function.pyをLambdaにアップロードする
- LINEのWebhook URLを設定し、ChatGPT風の返答に必要な初期値を与える
- DynamoDBにテーブルを作成し、Lambda関数からアクセスできるように設定する

【結論】
上記の手順を順に実施することで、LINE Messaging APIとOpenAIを使用したステートフルな会話をDynamoDBに保存するチャットボットをAWS Lambda上で実装することができます。