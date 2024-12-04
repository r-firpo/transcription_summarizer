import logging
import platform
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import List

import fastapi
import sentry_sdk
import uvicorn
from fastapi import FastAPI, APIRouter, Response, status, Request, Depends, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError, HTTPException
from pydantic import HttpUrl

from app.config import settings
from app.dtos.dtos import (
    BatchTranscriptionRequest, TranscriptionJob, JobStatusResponse,
    Transcript, Summary, VerificationResponse, JobStatus, JobPriority
)
from app.exceptions import (
    TranscriptionError, JobNotFoundError, SummaryError,
    VerificationError, LLMTimeoutError, get_root_cause_message, JobError, LLMError, LLMRateLimitError,
    InvalidJobStateError
)
from app.services.transcription_fetcher import TranscriptFetcher
from app.services.summarizer_service import SummarizerService
from app.services.llm import LLMService
from app.services.job_manager import JobManager

### Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(funcName)s:%(lineno)d - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def init_services(app: FastAPI):
    # Log system information
    logger.info("Preloading application - starting up once in main process.")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Operating System: {platform.system()} {platform.release()}")
    logger.info(f"FastAPI version: {fastapi.__version__}")
    logger.info(f"Using LLM Model: {settings.OPEN_AI_MODEL}")

    # Initialize Sentry
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=1.0,
        environment=settings.ENVIRONMENT,
        release="transcript-processor@1.0.0"
    )

    # Initialize services
    job_manager = JobManager()
    transcript_fetcher = TranscriptFetcher(job_manager)

    # Start background tasks
    await job_manager.start_cleanup_task()
    await transcript_fetcher.start_worker()

    yield

    # Cleanup
    await job_manager.stop_cleanup_task()
    await transcript_fetcher.stop_worker()


app = FastAPI(lifespan=init_services, title="Transcript Processor", version="1.0.0")
api_router = APIRouter()


# Exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.exception(f"Validation error: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors()}
    )


@app.exception_handler(TranscriptionError)
async def transcription_error_handler(request: Request, exc: TranscriptionError):
    logger.exception(f"Transcription error: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)}
    )


@app.exception_handler(SummaryError)
async def summary_error_handler(request: Request, exc: SummaryError):
    logger.exception(f"Summary error: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)}
    )


@app.exception_handler(LLMTimeoutError)
async def llm_timeout_handler(request: Request, exc: LLMTimeoutError):
    logger.exception(f"LLM timeout: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": "Processing timeout occurred"}
    )
@app.exception_handler(JobError)
async def job_error_handler(request: Request, exc: JobError):
    logger.exception(f"Job error: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)}
    )

@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    logger.exception(f"LLM error: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc)}
    )

@app.exception_handler(LLMRateLimitError)
async def rate_limit_handler(request: Request, exc: LLMRateLimitError):
    logger.exception(f"Rate limit exceeded: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "retry_after": "60"
        }
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {str(exc)} | Root cause: {get_root_cause_message(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred"}
    )


# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.info(
        f"Path: {request.url.path} Method: {request.method} Status: {response.status_code} Duration: {process_time:.2f}s")
    return response


# Routes
@api_router.get('/', status_code=200)
async def alive():
    return Response(content="I am alive", status_code=status.HTTP_200_OK)


@api_router.get('/health', status_code=200)
async def health():
    return Response(content="OK", status_code=status.HTTP_200_OK)


@api_router.post('/v1/transcribe', response_model=List[TranscriptionJob])
async def submit_transcription_jobs(
        request: BatchTranscriptionRequest,
        transcript_fetcher: TranscriptFetcher = Depends(TranscriptFetcher.get_instance)
):
    """Submit URLs for transcription"""
    return await transcript_fetcher.submit_urls(request.urls, request.priority)


@api_router.get('/v1/jobs', response_model=JobStatusResponse)
async def get_job_status(
        job_manager: JobManager = Depends(JobManager)
):
    """Get status of all jobs"""
    jobs = await job_manager.get_all_jobs()
    return JobStatusResponse(jobs=jobs)


@api_router.get('/v1/jobs/{job_id}', response_model=TranscriptionJob)
async def get_single_job_status(
        job_id: str,
        job_manager: JobManager = Depends(JobManager)
):
    """Get status of a specific job"""
    job = await job_manager.get_job(job_id)  # Make sure this is awaited
    if not job:
        raise JobNotFoundError(f"Job {job_id} not found")
    return job


@api_router.post('/v1/summarize/{job_id}', response_model=Summary)
async def summarize_transcript(
        job_id: str,
        job_manager: JobManager = Depends(JobManager),
        summarizer: SummarizerService = Depends(SummarizerService.get_instance)
):
    """Generate summary for a completed transcription"""
    job = await job_manager.get_job(job_id)  # Make sure this is awaited
    if not job:
        raise JobNotFoundError(f"Job {job_id} not found")

    if job.status != JobStatus.COMPLETED:
        raise InvalidJobStateError(
            f"Cannot summarize job in status {job.status}. Job must be in COMPLETED state."
        )

    try:
        return await summarizer.summarize(job.transcript)
    except Exception as e:
        logger.error(f"Failed to summarize transcript for job {job_id}: {str(e)}")
        raise SummaryError(f"Failed to generate summary: {str(e)}")


@api_router.post('/v1/verify', response_model=VerificationResponse)
async def verify_summary(
        summary: Summary = Body(...),
        llm_service: LLMService = Depends(LLMService.get_instance)
):
    """Verify summary content for inappropriate material"""
    try:
        result = await llm_service.verify_content(summary.summary_text)

        return VerificationResponse(
            transcript_id=summary.transcript_id,
            is_safe=result["is_safe"],
            reject_reason=result.get("reject_reason")
        )
    except LLMError as e:
        logger.error(f"LLM error during verification: {str(e)}")
        raise VerificationError(f"Failed to verify content: {str(e)}") from e
    except Exception as e:
        logger.error(f"Unexpected error during verification: {str(e)}")
        raise VerificationError(f"Unexpected error during verification: {str(e)}") from e


# Debug routes
@api_router.post('/v1/debug/force-cleanup', response_model=dict)
async def force_cleanup(
        job_manager: JobManager = Depends(JobManager)
):
    """Force cleanup of expired jobs"""
    try:
        cleanup_stats = await job_manager.force_cleanup()
        return cleanup_stats
    except Exception as e:
        logger.error(f"Error during forced cleanup: {str(e)}")
        raise


@api_router.post('/v1/debug/create-test-job', response_model=TranscriptionJob)
async def create_test_job(
        job_manager: JobManager = Depends(JobManager),
        priority: JobPriority = JobPriority.MEDIUM
):
    """Create a test job with a mock URL for testing purposes"""
    try:
        # Create a job with a dummy URL that bypasses validation
        test_url = HttpUrl('https://example.com/test-audio.mp3')
        job = TranscriptionJob.create_pending(
            job_id=str(uuid.uuid4()),
            url=test_url,
            priority=priority
        )

        # Store in job manager
        async with job_manager._jobs_lock:
            job_manager._jobs[job.job_id] = job
            await job_manager.queue_job(job)

        logger.info(f"Created test job {job.job_id}")
        return job

    except Exception as e:
        logger.error(f"Error creating test job: {str(e)}")
        raise


# Test sentry
@api_router.get("/sentry-debug")
async def trigger_error():
    division_by_zero = 1 / 0


app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=80)