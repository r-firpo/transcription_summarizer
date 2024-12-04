import json
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import Depends

from app.dtos.dtos import (
    Transcript, Summary, ConversationType,
    Topic, Speaker
)
from app.exceptions import (
    SummaryError,
    InvalidMetadataError,
    ContentTooLongError,
    get_root_cause_message
)
from app.services.llm import LLMService, LLMError, TokenLimitError

logger = logging.getLogger(__name__)


class SummarizerService:
    # Constants for summary generation
    MIN_TRANSCRIPT_LENGTH = 50  # characters
    MAX_SUMMARY_TOKENS = 1000

    # Load example summaries using absolute path
    EXAMPLE_DATA = json.load(
        open(
            Path(__file__).parent.parent / 'resources' / 'example_summaries.json'
        )
    )['examples']

    EXAMPLE_PROMPT = "\n".join([
        "Here are some example transcript summaries:",
        *[f"Transcript: {ex['transcript']}\nSummary: {ex['summary']}\n"
          for ex in EXAMPLE_DATA[:2]]  # Use first two examples
    ])

    def __init__(self, llm_service: LLMService):
        self.llm = llm_service

    @staticmethod
    def get_instance(llm_service: LLMService = Depends(LLMService.get_instance)):
        return SummarizerService(llm_service)

    def _validate_transcript(self, transcript: Transcript) -> None:
        """Validate transcript before processing"""
        if not transcript.text:
            raise SummaryError("Empty transcript text")

        if len(transcript.text) < self.MIN_TRANSCRIPT_LENGTH:
            raise SummaryError(
                f"Transcript too short. Minimum length: {self.MIN_TRANSCRIPT_LENGTH} characters"
            )

    async def _extract_conversation_metadata(self, transcript: Transcript) -> dict:
        """Extract conversation type and topics"""
        try:
            metadata = await self.llm.extract_metadata(transcript.text)

            # Validate required fields
            required_fields = {'conversation_type', 'topics', 'key_points'}
            missing_fields = required_fields - set(metadata.keys())
            if missing_fields:
                raise InvalidMetadataError(f"Missing required fields: {missing_fields}")

            # Validate conversation type
            try:
                ConversationType(metadata['conversation_type'])
            except ValueError as e:
                raise InvalidMetadataError(f"Invalid conversation type: {metadata['conversation_type']}")

            # Validate topics structure
            for topic in metadata['topics']:
                if not isinstance(topic, dict) or 'name' not in topic or 'confidence_score' not in topic:
                    raise InvalidMetadataError("Invalid topic structure in metadata")
                if not (0 <= topic['confidence_score'] <= 1):
                    raise InvalidMetadataError("Topic confidence score must be between 0 and 1")

            return metadata

        except LLMError as e:
            logger.error(f"LLM error during metadata extraction: {get_root_cause_message(e)}")
            raise SummaryError("Failed to extract conversation metadata") from e
        except Exception as e:
            logger.error(f"Unexpected error during metadata extraction: {get_root_cause_message(e)}")
            raise SummaryError("Unexpected error during metadata extraction") from e

    async def summarize(self, transcript: Transcript) -> Summary:
        """Generate a summary with metadata for a transcript"""
        logger.info(f"Generating summary for transcript {transcript.job_id}")

        try:
            # Validate input
            self._validate_transcript(transcript)

            # Generate main summary with example-based prompting
            try:
                summary_text = await self.llm.summarize(
                    f"{self.EXAMPLE_PROMPT}\nTranscript: {transcript.text}",
                    max_tokens=self.MAX_SUMMARY_TOKENS
                )
            except TokenLimitError as e:
                raise ContentTooLongError("Transcript too long for summarization") from e

            # Extract metadata
            metadata = await self._extract_conversation_metadata(transcript)

            # Create topics list
            topics = [
                Topic(
                    name=t['name'],
                    confidence_score=t['confidence_score']
                ) for t in metadata['topics']
            ]

            # Create summary object
            summary = Summary(
                transcript_id=transcript.job_id,
                conversation_type=ConversationType(metadata['conversation_type']),
                summary_text=summary_text,
                topics=topics,
                speakers=transcript.speakers,
                duration=transcript.duration,
                key_points=metadata['key_points']
            )

            logger.info(f"Successfully generated summary for transcript {transcript.job_id}")
            return summary

        except SummaryError:
            # Re-raise SummaryError and its subclasses
            raise
        except Exception as e:
            logger.error(f"Unexpected error summarizing transcript {transcript.job_id}")
            raise SummaryError(f"Failed to generate summary: {str(e)}") from e

    async def batch_summarize(self, transcripts: List[Transcript],
                              continue_on_error: bool = True) -> List[Summary]:
        """Summarize multiple transcripts"""
        #TODO this isn't being used
        logger.info(f"Starting batch summarization of {len(transcripts)} transcripts")
        summaries = []
        errors = []

        for transcript in transcripts:
            try:
                summary = await self.summarize(transcript)
                summaries.append(summary)
            except Exception as e:
                error_msg = f"Error summarizing transcript {transcript.job_id}: {get_root_cause_message(e)}"
                logger.error(error_msg)
                errors.append(error_msg)
                if not continue_on_error:
                    logger.error("Stopping batch processing due to error")
                    raise SummaryError(f"Batch processing failed: {error_msg}") from e

        if errors:
            logger.warning(f"Batch processing completed with {len(errors)} errors")

        logger.info(f"Completed batch summarization. Successful: {len(summaries)}, Failed: {len(errors)}")
        return summaries