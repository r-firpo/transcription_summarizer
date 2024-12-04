from enum import Enum
from typing import List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel, HttpUrl, Field
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, HttpUrl, Field
from enum import Enum

from app.exceptions import InvalidJobStateError


class JobStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConversationType(str, Enum):
    EDUCATIONAL = "EDUCATIONAL"
    FORMAL = "FORMAL"
    COMEDY = "COMEDY"
    PROFESSIONAL = "PROFESSIONAL"
    CASUAL = "CASUAL"
    INTERVIEW = "INTERVIEW"


class Speaker(BaseModel):
    id: str
    name: Optional[str] = None
    speaking_time: float = Field(description="Speaking time in seconds")


class Topic(BaseModel):
    name: str
    confidence_score: float = Field(ge=0.0, le=1.0)

class TranscriptionJob(BaseModel):
    job_id: str
    url: HttpUrl
    status: JobStatus
    priority: JobPriority
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    transcript: Optional['Transcript'] = None

    def __init__(self, **data):
        super().__init__(**data)
        self._validate_state()

    def _validate_state(self) -> None:
        """Validate the current state is consistent"""
        if self.status == JobStatus.COMPLETED and not self.transcript:
            raise ValueError("Completed jobs must have a transcript")

        if self.status == JobStatus.FAILED and not self.error_message:
            raise ValueError("Failed jobs must have an error message")

        if self.transcript and self.status != JobStatus.COMPLETED:
            raise ValueError("Transcript can only be present for completed jobs")

        if self.error_message and self.status != JobStatus.FAILED:
            raise ValueError("Error message can only be present for failed jobs")

    def mark_processing(self) -> None:
        """Mark job as processing"""
        if self.status != JobStatus.PENDING:
            raise InvalidJobStateError(
                f"Cannot mark job as processing from state {self.status}"
            )
        self.status = JobStatus.PROCESSING
        self.started_at = datetime.utcnow()
        self._validate_state()

    def mark_completed(self, transcript: 'Transcript') -> None:
        """Mark job as completed with its transcript"""
        if self.status != JobStatus.PROCESSING:
            raise InvalidJobStateError(
                f"Cannot mark job as completed from state {self.status}"
            )
        if not transcript:
            raise ValueError("Must provide transcript when completing job")

        self.status = JobStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.transcript = transcript
        self._validate_state()

    def mark_failed(self, error_message: str) -> None:
        """Mark job as failed with error message"""
        if self.status not in {JobStatus.PENDING, JobStatus.PROCESSING}:
            raise InvalidJobStateError(
                f"Cannot mark job as failed from state {self.status}"
            )
        if not error_message:
            raise ValueError("Must provide error message when failing job")

        self.status = JobStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error_message = error_message
        self.transcript = None  # Ensure no transcript is present
        self._validate_state()

    @classmethod
    def create_pending(cls, job_id: str, url: HttpUrl,
                       priority: JobPriority = JobPriority.MEDIUM) -> 'TranscriptionJob':
        """Create a new pending job"""
        return cls(
            job_id=job_id,
            url=url,
            status=JobStatus.PENDING,
            priority=priority,
            created_at=datetime.utcnow()
        )


class Transcript(BaseModel):
    job_id: str
    url: HttpUrl
    duration: float = Field(description="Duration in seconds")
    text: str
    speakers: List[Speaker]
    language: str = "en"
    error: Optional[str] = None


class Summary(BaseModel):
    transcript_id: str
    conversation_type: ConversationType
    summary_text: str
    topics: List[Topic]
    speakers: List[Speaker]
    duration: float
    key_points: List[str]


class BatchTranscriptionRequest(BaseModel):
    urls: List[HttpUrl]
    priority: JobPriority = JobPriority.MEDIUM


class RejectReason(str, Enum):
    PROFANITY = "PROFANITY"
    HATE_SPEECH = "HATE_SPEECH"
    PII = "PII"


class VerificationResponse(BaseModel):
    transcript_id: str
    is_safe: bool
    reject_reason: Optional[RejectReason] = None


class JobStatusResponse(BaseModel):
    jobs: List[TranscriptionJob]