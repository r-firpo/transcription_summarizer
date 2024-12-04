class InvalidJSONResponseError(Exception):
    """Raised when a server returns an invalid JSON response."""
    status_code = 502


class AdGenerationError(Exception):
    """Custom exception for ad generation errors."""
    status_code = 500


class LLMError(Exception):
    """Base exception for LLM-related errors"""
    status_code = 500

class LLMTimeoutError(LLMError):
    """Raised when LLM request times out"""
    status_code = 504

class LLMRateLimitError(LLMError):
    """Raised when LLM rate limit is exceeded"""
    status_code = 429

class LLMConnectionError(LLMError):
    """Raised when connection to LLM service fails"""
    status_code = 503

class InvalidResponseError(LLMError):
    """Raised when LLM returns invalid response format"""
    status_code = 502

class TokenLimitError(LLMError):
    """Raised when input exceeds token limit"""
    status_code = 400

class VerifyServiceError(Exception):
    """Custom exception for Verify service errors."""
    status_code = 500


class BriefServiceError(Exception):
    """Base exception for BriefService errors."""
    pass


class InvalidURLError(BriefServiceError):
    """Raised when an invalid URL is provided."""
    status_code = 400


class ScraperConnectionError(BriefServiceError):
    """Raised when there's a problem connecting to the scraper service."""
    status_code = 503


class ScraperResponseError(BriefServiceError):
    """Base exception for errors in the scraper service response."""
    pass


class ScraperClientError(ScraperResponseError):
    """Raised when the scraper service returns a 4xx status code."""
    status_code = 400


class ScraperServerError(ScraperResponseError):
    """Raised when the scraper service returns a 5xx status code."""
    status_code = 502


class BriefParsingError(BriefServiceError):
    """Raised when there's an error parsing the brief info from the scraper response."""
    status_code = 500


class MissingBriefFieldError(BriefParsingError):
    """Raised when a required field is missing from the brief info."""
    status_code = 422

    def __init__(self, field_name):
        self.field_name = field_name
        super().__init__(f"Missing required field in brief info: {field_name}")


class InvalidBriefFieldError(BriefParsingError):
    """Raised when a required field is invalid from the brief info."""
    status_code = 422

    def __init__(self, field_name):
        self.field_name = field_name
        super().__init__(f"Invalid required field in brief info: {field_name}")


def get_root_cause_message(e):
    # Traverse down the chain of causes to find the root cause
    root_cause = e
    while root_cause.__cause__ is not None:
        root_cause = root_cause.__cause__

    # Return a formatted message from the root cause
    return str(root_cause)

class TranscriptionError(Exception):
    """Base exception for transcription-related errors"""
    status_code = 500

class InvalidURLError(TranscriptionError):
    """Raised when an invalid URL is provided"""
    status_code = 400

class FileTooLargeError(TranscriptionError):
    """Raised when the audio file exceeds size limits"""
    status_code = 400

class UnsupportedAudioFormatError(TranscriptionError):
    """Raised when the audio format is not supported"""
    status_code = 400

class TranscriptionTimeoutError(TranscriptionError):
    """Raised when transcription takes too long"""
    status_code = 504

class SummaryError(Exception):
    """Base exception for summary-related errors"""
    status_code = 500

class ContentTooLongError(SummaryError):
    """Raised when content exceeds maximum token limit"""
    status_code = 400

class InvalidMetadataError(SummaryError):
    """Raised when metadata cannot be properly extracted"""
    status_code = 500

class VerificationError(Exception):
    """Base exception for content verification errors"""
    status_code = 500

class JobNotFoundError(Exception):
    """Raised when a job ID cannot be found"""
    status_code = 404

class InvalidJobStateError(Exception):
    """Raised when an operation is attempted on a job in the wrong state"""
    status_code = 400

class JobError(Exception):
    """Base exception for job-related errors"""
    status_code = 500

class JobNotFoundError(JobError):
    """Raised when a job ID cannot be found"""
    status_code = 404

class InvalidJobStateError(JobError):
    """Raised when an operation is attempted on a job in the wrong state"""
    status_code = 400

class InvalidPriorityError(JobError):
    """Raised when an invalid priority level is specified"""
    status_code = 400

class JobQueueError(JobError):
    """Raised when there are issues with the job queue"""
    status_code = 503


def get_error_details(error: Exception) -> dict:
    """Get detailed error information for logging and response"""
    return {
        "error_type": error.__class__.__name__,
        "message": str(error),
        "status_code": getattr(error, "status_code", 500)
    }
