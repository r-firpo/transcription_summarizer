import json
import logging
import re
from typing import Dict, Any, Optional
from openai import OpenAI, APITimeoutError, OpenAIError, APIError, RateLimitError, APIConnectionError

from app.config import settings
from app.exceptions import (
    LLMError,
    LLMTimeoutError,
    LLMRateLimitError,
    LLMConnectionError,
    InvalidResponseError,
    TokenLimitError
)

logger = logging.getLogger(__name__)


class LLMService:
    MODEL = settings.OPEN_AI_MODEL
    MAX_TOKENS = 4096  # Adjust based on model limits
    DEFAULT_TEMPERATURE = 0.7

    # System prompts
    SUMMARY_PROMPT = """Create a comprehensive summary of the following transcript. 
        Focus on key points, main themes, and important takeaways. Be concise but thorough."""

    METADATA_PROMPT = """Analyze the following transcript and extract metadata in JSON format:
        {
            "conversation_type": "EDUCATIONAL" | "FORMAL" | "COMEDY" | "PROFESSIONAL" | "CASUAL" | "INTERVIEW",
            "topics": [
                {
                    "name": "topic name",
                    "confidence_score": 0.0 to 1.0
                }
            ],
            "key_points": ["point 1", "point 2", ...]
        }
        Base the conversation_type on the overall tone and content of the discussion."""

    VERIFICATION_PROMPT = """Analyze the following text for inappropriate content, including:
        - Hate speech
        - Profanity
        - Personal identifying information (PII)

        Respond with a JSON object containing:
        {
            "is_safe": boolean,
            "reject_reason": null or one of ["PROFANITY", "HATE_SPEECH", "PII"]
        }
        """

    @staticmethod
    def get_instance():
        client = OpenAI(api_key=settings.OPENAI_KEY)
        return LLMService(client)

    def __init__(self, open_ai_client: OpenAI):
        self.client = open_ai_client

    async def generate_completion(
            self,
            system_prompt: str,
            user_content: str,
            max_tokens: Optional[int] = None,
            temperature: Optional[float] = None,
            expect_json: bool = False
    ) -> str:
        """Core method to generate completions with error handling"""
        try:
            logger.debug(f"Generating completion with model {self.MODEL}")
            logger.debug(f"System prompt: {system_prompt[:100]}...")
            logger.debug(f"Input length: {len(user_content)} chars")

            response = self.client.chat.completions.create(
                model=self.MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                max_tokens=max_tokens or self.MAX_TOKENS,
                temperature=temperature or self.DEFAULT_TEMPERATURE
            )
            output = str()
            for choice in response.choices:
                logger.info(choice.message.content)
                output += " " + choice.message.content
            output = self._clean_and_parse_json_string(output)

            # Log usage statistics
            logger.info(
                f"Completion generated - "
                f"Input tokens: {response.usage.prompt_tokens}, "
                f"Output tokens: {response.usage.completion_tokens}, "
                f"Total tokens: {response.usage.total_tokens}"
            )

            if expect_json:
                try:
                    json.loads(output)  # Validate JSON
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON response from LLM: {output}")
                    raise InvalidResponseError(f"LLM did not return valid JSON: {str(e)}")

            return output

        except APITimeoutError as e:
            logger.error(f"LLM request timed out: {str(e)}")
            raise LLMTimeoutError("Request to language model timed out") from e

        except RateLimitError as e:
            logger.error(f"Rate limit exceeded: {str(e)}")
            raise LLMRateLimitError("Rate limit exceeded for language model") from e

        except APIConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            raise LLMConnectionError("Failed to connect to language model service") from e

        except APIError as e:
            if "maximum context length" in str(e).lower():
                logger.error(f"Token limit exceeded: {str(e)}")
                raise TokenLimitError("Input exceeds maximum token limit") from e
            logger.error(f"OpenAI API error: {str(e)}")
            raise LLMError(f"Language model error: {str(e)}") from e

        except OpenAIError as e:
            logger.error(f"Unexpected OpenAI error: {str(e)}")
            raise LLMError(f"Unexpected language model error: {str(e)}") from e

        except Exception as e:
            logger.exception("Unexpected error during LLM completion")
            raise LLMError(f"Unexpected error: {str(e)}") from e

    async def summarize(self, text: str, max_tokens: Optional[int] = None) -> str:
        """Generate a summary using the LLM"""
        logger.info("Generating transcript summary")
        return await self.generate_completion(
            system_prompt=self.SUMMARY_PROMPT,
            user_content=text,
            max_tokens=max_tokens,
            temperature=0.7  # Higher temperature for more creative summaries
        )

    async def extract_metadata(self, text: str) -> Dict[str, Any]:
        """Extract metadata about the conversation using the LLM"""
        logger.info("Extracting transcript metadata")
        response = await self.generate_completion(
            system_prompt=self.METADATA_PROMPT,
            user_content=text,
            temperature=0.3,  # Lower temperature for consistent metadata
            expect_json=True
        )

        return json.loads(response)

    async def verify_content(self, text: str) -> Dict[str, Any]:
        """Verify content for inappropriate material"""
        logger.info("Verifying content safety")
        response = await self.generate_completion(
            system_prompt=self.VERIFICATION_PROMPT,
            user_content=text,
            temperature=0.1,  # Very low temperature for consistent moderation
            expect_json=True
        )

        return json.loads(response)

    def _clean_and_parse_json_string(self, input_string) -> str:
        '''
        OpenAI gpt-40-mini seems to return strings prepended by backticks which are not valid json, this attempts
        to handle those cases so that the response can be loaded as valid json in json.loads()

        Example input_string (raw output of gpt-40-mini):
        ``json
                {
                    "conversation_type": "PROFESSIONAL",
                    "topics": [
                        {
                            "name": "Q3 Planning",
                            "confidence_score": 0.9
                        },
                        {
                            "name": "Sales Projections",
                            "confidence_score": 0.85
                        },
                        {
                            "name": "Customer Acquisition",
                            "confidence_score": 0.8
                        },
                        {
                            "name": "Marketing Campaign Results",
                            "confidence_score": 0.75
                        },
                        {
                            "name": "Conversion Rate Improvement",
                            "confidence_score": 0.7
                        }
                    ],
                    "key_points": [
                        "Q2 performance shows a 15% increase in customer acquisition.",
                        "Sales projections were prepared for the meeting.",
                        "Organic traffic increased by 12% in the first month of Q2.",
                        "Conversion rate improved from 2.8% to 3.5%.",
                        "New landing page design is driving better engagement."
                    ]
                }
                ```
        Returned string:
        {
                    "conversation_type": "PROFESSIONAL",
                    "topics": [
                        {
                            "name": "Q3 Planning",
                            "confidence_score": 0.9
                        },
                        {
                            "name": "Sales Projections",
                            "confidence_score": 0.85
                        },
                        {
                            "name": "Customer Acquisition",
                            "confidence_score": 0.8
                        },
                        {
                            "name": "Marketing Campaign Results",
                            "confidence_score": 0.75
                        },
                        {
                            "name": "Conversion Rate Improvement",
                            "confidence_score": 0.7
                        }
                    ],
                    "key_points": [
                        "Q2 performance shows a 15% increase in customer acquisition.",
                        "Sales projections were prepared for the meeting.",
                        "Organic traffic increased by 12% in the first month of Q2.",
                        "Conversion rate improved from 2.8% to 3.5%.",
                        "New landing page design is driving better engagement."
                    ]
                }

        '''
        # Remove leading/trailing whitespace
        cleaned_string = input_string.strip()

        # Remove 'json' prefix and triple backticks
        cleaned_string = re.sub(r'^(```)?json?\s*', '', cleaned_string, flags=re.IGNORECASE)
        cleaned_string = re.sub(r'```$', '', cleaned_string)
        return cleaned_string
