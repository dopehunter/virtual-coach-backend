from pydantic import BaseModel, Field
from typing import Literal, Optional, List
from datetime import date # Import date

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

# --- Plan Generation Schemas --- 

class WorkoutSegmentPlan(BaseModel):
    segment_order: int
    segment_type: Optional[str] = None # e.g., 'WarmUp', 'MainSet', 'CoolDown'
    duration_minutes: Optional[int] = None
    distance_meters: Optional[int] = None
    target_intensity: Optional[str] = None
    exercise_name: Optional[str] = None # Name of drill/exercise, if applicable
    reps: Optional[int] = None
    rest_duration_seconds: Optional[int] = None
    notes: Optional[str] = None

class WorkoutPlan(BaseModel):
    # Note: date will be derived from the day index + week_start_date
    day_index: int # 0=Monday, 1=Tuesday, ..., 6=Sunday
    activity_type: Literal['Swimming', 'Running', 'Rest']
    title: Optional[str] = None
    segments: Optional[List[WorkoutSegmentPlan]] = None # Only relevant if not 'Rest'

class WeeklyPlanResponse(BaseModel):
    # Expected structure from Gemini after parsing
    workouts: List[WorkoutPlan]

class GeneratePlanRequest(BaseModel):
    week_start_date: Optional[date] = None # Optional: Defaults to next Monday

class GeneratePlanResponse(BaseModel):
    plan_id: str # UUID as string
    week_start_date: date
    message: str 