import random
from datetime import datetime, timezone
from typing import List
from pydantic import HttpUrl

from app.dtos.dtos import Transcript, Speaker


class TranscriptFixtures:
    # Sample audio URLs (these would be valid in a real environment)
    SAMPLE_URLS = [
        HttpUrl('https://example.com/audio/podcast-episode-123.mp3'),
        HttpUrl('https://example.com/audio/interview-456.wav'),
        HttpUrl('https://example.com/audio/meeting-789.m4a'),
        HttpUrl('https://example.com/audio/comedy-show-012.mp3'),
        HttpUrl('https://example.com/audio/lecture-345.wav')
    ]

    # Predefined transcript templates with realistic content
    TRANSCRIPT_TEMPLATES = [
        # Comedy Podcast
        {
            "text": """
            Host: Welcome to Comedy Hour, episode 245! I'm your host Dave Johnson.
            Guest1: And I'm Sarah Martinez, ready to share some laughs!
            Host: Today we're talking about the most ridiculous things that happened to us at the DMV.
            Guest2: Oh boy, do I have some stories about that!
            Host: Before we dive in, quick reminder to like and subscribe, folks!
            Guest1: My DMV story starts with me waiting in line for what felt like three years...
            Guest2: Only three? Lucky you! [Laughter]
            Host: The DMV is where time goes to die, everyone knows that! [More laughter]
            Guest1: So there I was, finally at the counter, and I realized I brought my cat's vaccination records instead of my ID...
            Host: Wait, what? How did you even...
            Guest2: Classic Sarah! This is why we love having you on the show!
            """,
            "duration": 1800,  # 30 minutes
            "speaker_templates": [
                {"name": "Dave Johnson", "role": "host", "percentage": 0.4},
                {"name": "Sarah Martinez", "role": "guest", "percentage": 0.35},
                {"name": "Mike Wilson", "role": "guest", "percentage": 0.25}
            ]
        },
        # Professional Meeting
        {
            "text": """
            Chairperson: Good morning everyone, let's begin our Q3 planning meeting.
            Manager1: I've prepared the sales projections as requested.
            Analyst: Based on our Q2 performance, we're seeing a 15% increase in customer acquisition.
            Manager2: That aligns with our marketing campaign results.
            Chairperson: Excellent. Can you walk us through the numbers?
            Manager1: Of course. In the first month of Q2, we saw a 12% increase in organic traffic...
            Analyst: And our conversion rate improved from 2.8% to 3.5%.
            Manager2: The new landing page design seems to be driving better engagement.
            Chairperson: These are encouraging results. Let's discuss how we can build on this momentum...
            """,
            "duration": 3600,  # 60 minutes
            "speaker_templates": [
                {"name": "Jennifer Chen", "role": "chairperson", "percentage": 0.35},
                {"name": "Robert Clark", "role": "manager", "percentage": 0.25},
                {"name": "Emily Wong", "role": "analyst", "percentage": 0.25},
                {"name": "Michael Brown", "role": "manager", "percentage": 0.15}
            ]
        },
        # Educational Lecture
        {
            "text": """
            Professor: Welcome to Advanced Mathematics 301. Today we're covering eigenvalues and eigenvectors.
            Student1: Could you explain how this relates to linear transformations?
            Professor: Excellent question. Think of eigenvectors as special vectors that don't change direction when transformed...
            Student2: So they only scale up or down?
            Professor: Precisely! And the eigenvalue is that scaling factor. Let's look at a concrete example...
            Student3: Could you write that equation again?
            Professor: Of course. Observe that when we apply this matrix to our eigenvector...
            Student1: Oh, now I see how it connects to our previous lesson!
            Professor: Exactly! This is why eigenvalues are so crucial in various applications...
            """,
            "duration": 2700,  # 45 minutes
            "speaker_templates": [
                {"name": "Dr. Smith", "role": "professor", "percentage": 0.70},
                {"name": "Alex Turner", "role": "student", "percentage": 0.15},
                {"name": "Maria Garcia", "role": "student", "percentage": 0.10},
                {"name": "James Lee", "role": "student", "percentage": 0.05}
            ]
        }
    ]

    @classmethod
    def create_transcript(cls, job_id: str) -> Transcript:
        """Create a realistic transcript fixture"""
        # Select random template and URL
        template = random.choice(cls.TRANSCRIPT_TEMPLATES)
        url = random.choice(cls.SAMPLE_URLS)

        # Calculate speaker times based on duration and percentages
        total_duration = template["duration"]
        speakers = []

        for speaker_template in template["speaker_templates"]:
            speaking_time = total_duration * speaker_template["percentage"]
            speakers.append(
                Speaker(
                    id=f"speaker_{len(speakers) + 1}",
                    name=speaker_template["name"],
                    speaking_time=speaking_time
                )
            )

        return Transcript(
            job_id=job_id,
            url=url,
            duration=total_duration,
            text=template["text"].strip(),
            speakers=speakers,
            language="en"
        )

    @classmethod
    def create_multiple_transcripts(cls, job_ids: List[str]) -> List[Transcript]:
        """Create multiple transcript fixtures"""
        return [cls.create_transcript(job_id) for job_id in job_ids]