import asyncio
import logging
from typing import List, Optional
from urllib.parse import urlparse
import aiohttp
from fastapi import Depends
from pydantic import HttpUrl

from app.dtos.dtos import TranscriptionJob, JobStatus, Transcript, JobPriority
from app.exceptions import (
    TranscriptionError,
    InvalidURLError,
    FileTooLargeError,
    UnsupportedAudioFormatError,
    TranscriptionTimeoutError
)
from app.services.job_manager import JobManager
from app.utils.transcript_generator import TranscriptFixtures

logger = logging.getLogger(__name__)


class TranscriptFetcher:
    MAX_FILE_SIZE_MB = 100
    MAX_DURATION_MINUTES = 120
    SUPPORTED_SCHEMES = {'http', 'https'}
    SUPPORTED_FORMATS = {'.mp3', '.wav', '.m4a', '.mp4', '.webm'}

    @staticmethod
    def get_instance(job_manager: JobManager = Depends(JobManager)):
        return TranscriptFetcher(job_manager)

    def __init__(self, job_manager: JobManager):
        self.job_manager = job_manager
        self._worker_task: Optional[asyncio.Task] = None

    async def start_worker(self) -> None:
        """Start the background worker if not already running"""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_jobs())
            logger.info("Started transcript fetcher worker")

    async def stop_worker(self) -> None:
        """Stop the background worker"""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped transcript fetcher worker")

    async def submit_urls(self, urls: List[HttpUrl], priority: JobPriority) -> List[TranscriptionJob]:
        """Submit multiple URLs for transcription"""
        logger.info(f"Submitting {len(urls)} URLs for transcription with priority {priority}")
        jobs = []

        for url in urls:
            try:
                await self._validate_url(url)
                job = await self.job_manager.create_job(url, priority)
                await self.job_manager.queue_job(job)
                jobs.append(job)
                logger.debug(f"Successfully queued job {job.job_id} for URL {url}")
            except TranscriptionError as e:
                logger.error(f"Error processing URL {url}: {str(e)}")
                # Create failed job to track the error
                job = await self.job_manager.create_job(url, priority)
                job.mark_failed(str(e))
                jobs.append(job)

        if jobs:
            await self.start_worker()
        return jobs

    async def _validate_url(self, url: HttpUrl) -> None:
        """Validate URL and perform preliminary checks on the audio file"""
        parsed_url = urlparse(str(url))

        # Check URL scheme
        if parsed_url.scheme not in self.SUPPORTED_SCHEMES:
            raise InvalidURLError(f"Unsupported URL scheme: {parsed_url.scheme}")

        # Check file extension
        file_ext = parsed_url.path.lower()[parsed_url.path.rfind('.'):]
        if file_ext not in self.SUPPORTED_FORMATS:
            raise UnsupportedAudioFormatError(
                f"Unsupported audio format: {file_ext}. Supported formats: {', '.join(self.SUPPORTED_FORMATS)}"
            )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(str(url), timeout=10) as response:
                    if response.status != 200:
                        raise InvalidURLError(f"URL returned status code: {response.status}")

                    # Check content length if available
                    if 'content-length' in response.headers:
                        size_mb = int(response.headers['content-length']) / (1024 * 1024)
                        if size_mb > self.MAX_FILE_SIZE_MB:
                            raise FileTooLargeError(
                                f"File size ({size_mb:.1f}MB) exceeds maximum allowed size of {self.MAX_FILE_SIZE_MB}MB"
                            )

                    # Check content type
                    content_type = response.headers.get('content-type', '')
                    if not any(format_type in content_type for format_type in ['audio/', 'video/']):
                        logger.warning(f"Unexpected content type for URL {url}: {content_type}")

        except aiohttp.ClientError as e:
            raise InvalidURLError(f"Error accessing URL: {str(e)}")
        except asyncio.TimeoutError:
            raise TranscriptionTimeoutError("Timeout while validating URL")

    async def _process_jobs(self) -> None:
        """Background worker to process transcription jobs"""
        while True:
            try:
                job = await self.job_manager.get_next_job()
                if job:
                    logger.info(f"Processing job {job.job_id}")
                    try:
                        await self._process_single_job(job)
                    except Exception as e:
                        logger.exception(f"Error processing job {job.job_id}: {str(e)}")
                        job.mark_failed(str(e))
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.exception(f"Error in job processing loop: {str(e)}")
                await asyncio.sleep(1)

    async def _process_single_job(self, job: TranscriptionJob) -> Optional[Transcript]:
        """Process a single transcription job"""
        try:
            job.mark_processing()

            # TODO Defensively validate URL again in case it became invalid
            #await self._validate_url(job.url)

            # Use our fixtures to generate a realistic transcript
            await asyncio.sleep(2)  # Simulate processing time
            transcript = TranscriptFixtures.create_transcript(job.job_id)

            # Update job status with the completed transcript
            job.mark_completed(transcript)

            logger.info(f"Successfully completed job {job.job_id}")
            return transcript

        except TranscriptionError as e:
            logger.error(f"Transcription error for job {job.job_id}: {str(e)}")
            job.mark_failed(str(e))
            raise
        except Exception as e:
            logger.error(f"Unexpected error processing job {job.job_id}")
            error_msg = f"Unexpected error during transcription: {str(e)}"
            job.mark_failed(error_msg)
            raise TranscriptionError(error_msg) from e