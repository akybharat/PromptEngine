import openai
from promptengine_catapult import config
from io import BytesIO
import tiktoken

model_used = config.LLM_MODEL_USED


def voiceToText(audio):
    audio_file = BytesIO(audio.file.read())  # Read the file data from UploadFile object
    transcript = openai.Audio.transcribe("whisper-1", audio_file)
    return transcript["text"]


def setTokenLimit(model_used):
    if model_used == "gpt-4-32k":
        token_limit = 32768
    elif model_used == "gpt-4":
        token_limit = 8182
    else:
        token_limit = 4096
    return token_limit


def num_tokens_from_messages(messages, model=model_used):
    encoding = tiktoken.encoding_for_model(model)
    num_tokens = 0
    for message in messages:
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
    return num_tokens
