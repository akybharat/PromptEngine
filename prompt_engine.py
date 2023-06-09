import openai
import redis
import json
import tiktoken
import requests
import config
import utils
import logging

from dotenv import load_dotenv
import os
import io
import openai
from pydub import AudioSegment
from pydub.playback import pla

# setting logging
logging.basicConfig(
    level=(logging.DEBUG if os.getenv("LOG_MODE") == "DEBUG" else logging.INFO)
)


class PromptEngine:
    def __init__(self, redis_instance):
        # Create Redis connection
        self.redis_prompt = redis_instance
        # Load environment variables from .env file
        load_dotenv()

        # Set OpenAI API key from environment variable
        openai.api_key = os.getenv("OPENAI_API_KEY")

        # Load configuration values
        self.max_response_tokens = config.MAX_RESPONSE_TOKENS_PROMT
        self.model_used = config.LLM_MODEL_USED
        self.cutoff_threshold = config.CUTOFF_THRESHOLD

        # Set token limit based on the model used
        self.token_limit = utils.setTokenLimit(self.model_used)

    def store_user_data(
        self,
        interview_id: str,
        username: str,
        position: str,
        skills: str,
        job_description: str = "",
        experience: str = "",
    ) -> bool:
        """
        Stores user data related to an interview session in the Redis database.

        Parameters:
        - interview_id (str): The unique identifier of the interview session.
        - username (str): The name of the candidate.
        - position (str): The role applied for by the candidate.
        - skills (str): The relevant skills of the candidate.
        - job_description (str, optional): The job description for the applied position. Default is an empty string.
        - experience (str, optional): The relevant experience of the candidate. Default is an empty string.

        Returns:
        - bool: True if the data is successfully stored in Redis, False otherwise.

        Raises:
        - Exception: If an error occurs while storing the data.
        """
        try:
            profile_data = f"""
            Candidate name is {username}. {username} has applied for role: {position}. Job description for the applied position is: {job_description}. His relevant skills are: {skills}. Candidate's relevant experience in the field is: {experience}.
            """
            curr_dict = {"role": "system", "content": config.INTERVIEW_PROMPT}
            self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

            curr_dict = {"role": "system", "content": profile_data}
            self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

            return True
        except Exception as e:
            logging.error(e)
            return False

    def chatAI(self, interview_id, state, candidate_input):
        """
        An interview conversation. Takes candidate input and generates a response from the AI assistant.

        Parameters:
        - interview_id (str): The unique identifier of the interview session.
        - state (str): The state of the interview session (ONGOING or END).
        - candidate_input (str): The input provided by the candidate.

        Returns:
        - system_message (str): The generated response from the AI assistant.
        """

        if state == "ONGOING":
            self.redis_prompt.lpush(interview_id + "_answers", candidate_input)
            curr_dict = {"role": "user", "content": candidate_input}
            self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

        elif state == "END":
            curr_dict = {
                "role": "user",
                "content": 'I am done with the interview. End the interview by giving some helpful remarks and saying, "ending your interview!!!--catapult.ai"',
            }
            self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

        json_strings = self.redis_prompt.lrange(interview_id, 0, -1)

        message_list = []
        for json_string in json_strings:
            dictionary = json.loads(json_string)
            message_list.append(dictionary)

        message_list = message_list[::-1]

        conv_history_tokens = utils.num_tokens_from_messages(message_list)

        if state != "END":
            while (
                conv_history_tokens + self.max_response_tokens
                >= self.token_limit * self.cutoff_threshold
            ):
                curr_dict = {
                    "role": "user",
                    "content": 'I am done with the interview. End the interview by saying only, "ending your interview!!!--catapult.ai"',
                }
                self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

        response = openai.ChatCompletion.create(
            model=self.model_used,
            messages=message_list,
            temperature=0.7,
            max_tokens=self.max_response_tokens,
        )
        system_message = response["choices"][0]["message"]["content"]

        curr_dict = {"role": "assistant", "content": system_message}
        self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))
        self.redis_prompt.lpush(interview_id + "_questions", system_message)

        return system_message, is_last

    def voiceToText(self, audio):
        """
        Transcribes the audio file to text using OpenAI's Audio API.

        Parameters:
        - audio (str): The path to the audio file.

        Returns:
        - text (str): The transcribed text from the audio.
        """
        audio_file = open(audio.file, "rb")
        transcript = openai.Audio.transcribe("whisper-1", audio_file)
        return transcript["text"]


# TO Do:
# Feedback function

