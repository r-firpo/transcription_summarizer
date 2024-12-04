import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import asyncio
from threading import Lock
import json

from app.dtos.dtos import TranscriptionJob, JobStatus, JobPriority, HttpUrl
from app.exceptions import (
    JobError,
    JobNotFoundError,
    InvalidJobStateError,
    InvalidPriorityError,
    JobQueueError
)

logger = logging.getLogger(__name__)


class JobManager:
    _instance = None
    _lock = Lock()

    # Constants for job management
    MAX_QUEUE_SIZE = 1000
    JOB_TIMEOUT_MINUTES = 30
    CLEANUP_INTERVAL_HOURS = 1

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(JobManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if not self._initialized:
            self._jobs: Dict[str, TranscriptionJob] = {}
            self._priority_queues: Dict[JobPriority, asyncio.PriorityQueue] = {
                JobPriority.HIGH: asyncio.PriorityQueue(maxsize=self.MAX_QUEUE_SIZE),
                JobPriority.MEDIUM: asyncio.PriorityQueue(maxsize=self.MAX_QUEUE_SIZE),
                JobPriority.LOW: asyncio.PriorityQueue(maxsize=self.MAX_QUEUE_SIZE)
            }
            self._cleanup_task: Optional[asyncio.Task] = None
            self._jobs_lock = asyncio.Lock()
            self._initialized = True
            logger.info("Initialized JobManager singleton")

    async def start_cleanup_task(self):
        """Start the periodic cleanup task"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            logger.info("Started job cleanup task")

    async def stop_cleanup_task(self):
        """Stop the cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped job cleanup task")

    async def force_cleanup(self) -> dict:
        """Force cleanup of expired jobs and return cleanup statistics"""
        async with self._jobs_lock:
            initial_count = len(self._jobs)
            current_time = datetime.utcnow()
            jobs_to_remove = []
            timeout_threshold = timedelta(minutes=self.JOB_TIMEOUT_MINUTES)

            stale_completed = 0
            stale_failed = 0
            timed_out = 0

            for job_id, job in self._jobs.items():
                try:
                    # Clean up old completed/failed jobs
                    if job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                        if job.completed_at and (current_time - job.completed_at) > timedelta(
                                hours=self.CLEANUP_INTERVAL_HOURS):
                            jobs_to_remove.append(job_id)
                            if job.status == JobStatus.COMPLETED:
                                stale_completed += 1
                            else:
                                stale_failed += 1

                    # Handle stuck jobs
                    elif job.status == JobStatus.PROCESSING:
                        if job.started_at and (current_time - job.started_at) > timeout_threshold:
                            job.mark_failed("Job timed out during forced cleanup")
                            timed_out += 1

                except Exception as e:
                    logger.exception(f"Error processing job {job_id} during cleanup: {str(e)}")
                    continue

            # Remove cleaned up jobs
            for job_id in jobs_to_remove:
                del self._jobs[job_id]

            final_count = len(self._jobs)
            cleanup_stats = {
                "initial_job_count": initial_count,
                "final_job_count": final_count,
                "stale_completed_removed": stale_completed,
                "stale_failed_removed": stale_failed,
                "processing_timed_out": timed_out
            }

            logger.info(f"Forced cleanup completed: {cleanup_stats}")
            return cleanup_stats

    async def create_job(self, url: HttpUrl, priority: JobPriority = JobPriority.MEDIUM) -> TranscriptionJob:
        """Create a new transcription job"""
        try:
            job_id = str(uuid.uuid4()) #TODO UUID generation should probably be part of job cretoin
            job = TranscriptionJob.create_pending(job_id, url, priority)

            async with self._jobs_lock:
                self._jobs[job_id] = job
                logger.info(f"Created job {job_id} with priority {priority}")
                return job

        except Exception as e:
            logger.error(f"Error creating job: {str(e)}")
            raise JobError(f"Failed to create job: {str(e)}")

    async def queue_job(self, job: TranscriptionJob) -> None:
        """Queue a job for processing"""
        try:
            # Create tuple for priority queue: (priority_value, timestamp, job_id)
            priority_value = {
                JobPriority.HIGH: 1,
                JobPriority.MEDIUM: 2,
                JobPriority.LOW: 3
            }[job.priority]

            queue_item = (
                priority_value,
                job.created_at.timestamp(),
                job.job_id
            )

            try:
                await self._priority_queues[job.priority].put(queue_item)
                logger.debug(f"Queued job {job.job_id} with priority {job.priority}")
            except KeyError:
                logger.error(f"Invalid priority level: {job.priority}")
                raise InvalidPriorityError(f"Invalid priority level: {job.priority}")

        except Exception as e:
            logger.error(f"Error queuing job {job.job_id}: {str(e)}")
            raise JobError(f"Failed to queue job: {str(e)}")

    async def get_next_job(self) -> Optional[TranscriptionJob]:
        """Get the next job to process based on priority"""
        async with self._jobs_lock:
            for priority in JobPriority:
                queue = self._priority_queues[priority]
                if not queue.empty():
                    try:
                        _, _, job_id = await queue.get()
                        job = self._jobs.get(job_id)
                        if job and job.status == JobStatus.PENDING:
                            logger.debug(f"Retrieved job {job_id} from {priority} queue")
                            return job
                    except Exception as e:
                        logger.exception(f"Error retrieving job from queue: {str(e)}")
                        continue
            return None

    async def get_job(self, job_id: str) -> TranscriptionJob:
        """Get a specific job by ID"""
        async with self._jobs_lock:
            job = self._jobs.get(job_id)
            if not job:
                raise JobNotFoundError(f"Job {job_id} not found")
            return job

    async def get_all_jobs(self, status: Optional[JobStatus] = None) -> List[TranscriptionJob]:
        """Get all jobs, optionally filtered by status"""
        async with self._jobs_lock:
            try:
                jobs = list(self._jobs.values())
                if status:
                    jobs = [job for job in jobs if job.status == status]
                return jobs
            except Exception as e:
                logger.error(f"Error retrieving jobs: {str(e)}")
                raise JobError(f"Failed to retrieve jobs: {str(e)}")

    async def mark_job_failed_system_error(self, job_id: str, error_message: str) -> TranscriptionJob:
        """Handle system-level failures for a job"""
        #TODO not being used
        async with self._jobs_lock:
            try:
                job = self._jobs.get(job_id)
                if not job:
                    raise JobNotFoundError(f"Job {job_id} not found")

                job.mark_failed(f"System error: {error_message}")
                return job
            except Exception as e:
                logger.error(f"Error marking job as failed: {str(e)}")
                raise JobError(f"Failed to update job: {str(e)}")

    async def export_jobs_report(self, file_path: str) -> None:
        """Export jobs data to a JSON file"""
        #TODO not used
        async with self._jobs_lock:
            try:
                jobs_data = [job.dict() for job in self._jobs.values()]
                with open(file_path, 'w') as f:
                    json.dump(jobs_data, f, default=str, indent=2)
                logger.info(f"Exported jobs report to {file_path}")
            except Exception as e:
                logger.error(f"Error exporting jobs report: {str(e)}")
                raise JobError(f"Failed to export jobs report: {str(e)}")

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up old jobs"""
        while True:
            try:
                await self.force_cleanup()
                await asyncio.sleep(self.CLEANUP_INTERVAL_HOURS * 3600)
            except Exception as e:
                logger.exception(f"Error in cleanup task: {str(e)}")
                await asyncio.sleep(60)  # Wait before retrying on error

