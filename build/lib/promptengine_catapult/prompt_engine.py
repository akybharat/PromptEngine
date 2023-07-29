import os

#os.chdir(os.path.dirname(os.path.abspath(__file__)))
import openai
import redis
import json
import tiktoken
import requests
#import config
from promptengine_catapult import config
from promptengine_catapult.utils import *
import logging

from dotenv import load_dotenv
import io
import openai
from pydub import AudioSegment
from pydub.playback import play
import pandas as pd


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
        self.token_limit = setTokenLimit(self.model_used)

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
        is_last = False
        if state == "ONGOING":
            self.redis_prompt.lpush(interview_id + "_answers", candidate_input)
            curr_dict = {"role": "user", "content": candidate_input}
            self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

        elif state == "END":
            if candidate_input:
                self.redis_prompt.lpush(interview_id + "_answers", candidate_input)
                curr_dict = {"role": "user", "content": candidate_input}
                self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

            curr_dict = {
                "role": "user",
                "content": 'I am done with the interview. End the interview by giving some helpful remarks and saying, "ending your interview!!!--catapult.ai"',
            }
            self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))
            is_last = True

        json_strings = self.redis_prompt.lrange(interview_id, 0, -1)

        message_list = []
        for json_string in json_strings:
            dictionary = json.loads(json_string)
            message_list.append(dictionary)

        message_list = message_list[::-1]

        conv_history_tokens = num_tokens_from_messages(message_list)

        if state != "END":
            if (
                conv_history_tokens + self.max_response_tokens
                >= self.token_limit * self.cutoff_threshold
            ):
                curr_dict = {
                    "role": "user",
                    "content": 'I am done with the interview. End the interview by saying only, "ending your interview!!!--catapult.ai"',
                }
                self.redis_prompt.lpush(interview_id, json.dumps(curr_dict))

                json_strings = self.redis_prompt.lrange(interview_id, 0, -1)
                message_list = []
                for json_string in json_strings:
                    dictionary = json.loads(json_string)
                    message_list.append(dictionary)
                message_list = message_list[::-1]

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
        logging.debug("voice to text conversion successful")
        return transcript["text"]
    
    def feedback(self, interview_id):
        messages = []
        system_msg=config.FEEDBACK_PROMPT
        json_strings = self.redis_prompt.lrange(interview_id, 0, - 1)

        message_list = []
        for json_string in json_strings:
            dictionary = json.loads(json_string)
            message_list.append(dictionary)

        message_list=message_list[::-1]

        system_msg+=message_list[1]['content']
        messages.append({"role": "system", "content": system_msg})

        questions = self.redis_prompt.lrange(interview_id+'_questions', 0, - 1)
        answers = self.redis_prompt.lrange(interview_id+'_answers', 0, - 1)
        questions=questions[::-1]
        answers=answers[::-1]

        min_convo=min(len(answers), len(questions))
        questions_answered=questions[:min_convo]
        
        df=pd.DataFrame({'Questions':questions_answered,
                        'Answers':answers[:min_convo]})
        
        result1=df.to_dict('index')
        
        messages.append({"role": "user", "content": str(result1)})

        response = openai.ChatCompletion.create(
            model=model_used,
            messages=messages)
        system_message = response["choices"][0]["message"]["content"]
        messages.append({"role": "assistant", "content": system_message})
        

        
        self.redis_prompt.set(interview_id+'_feedback', system_message)

        rating= system_message.split('\n')
        rating_line = rating[0]
        feedback_line = rating[1]

        # Extract the rating value and feedback text
        Overall_Rating = rating_line.split(': ')[1]
        Overall_Feedback = feedback_line.split(': ')[1]
        
        return {
            'system_message': system_message,
            'Overall Rating': Overall_Rating,
            'Overall Feedback' : Overall_Feedback
        }


# TO Do:
# redis timeout
