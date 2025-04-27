from pydantic import BaseModel, Field
from typing import Literal, Optional

# Model for the data coming from the frontend onboarding form
class OnboardingData(BaseModel):
    runExperience: str 
    runDuration: str
    swimExperience: str
    swimDuration: str
    primaryGoal: str

# Model for the expected JSON structure from the Gemini assessment
class GeminiAssessmentResponse(BaseModel):
    swim_level: Literal['Beginner', 'Intermediate', 'Advanced']
    run_level: Literal['Beginner', 'Intermediate', 'Advanced']

# Model for the response sent back to the frontend
class AssessmentResult(BaseModel):
    swim_level: str
    run_level: str
    message: Optional[str] = None 