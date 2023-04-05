import tiktoken
from tiktoken.core import Encoding
from prompt_toolkit import prompt
from prompt_toolkit.key_binding.bindings.named_commands import get_by_name
from prompt_toolkit.key_binding import KeyBindings

encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

# キーのバインディングを設定する
kb = KeyBindings()

@kb.add("c-m")  # Ctrl+M / Command+M
def _(event):
    b = event.current_buffer
    b.validate_and_handle()

# 複数行のテキストを受け取る
print("複数行のテキストを入力してください（Ctrl+MまたはCommand+Mで入力を終了します）：")
transcription = prompt("", key_bindings=kb, multiline=True)

tokens = encoding.encode(transcription)
tokens_count = len(tokens)
print(f"{tokens_count=}")
