from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import ValidationError
import json
from datetime import date, timedelta, datetime
from typing import Optional, List

from schemas import (
    OnboardingData, AssessmentResult, GeminiAssessmentResponse, 
    GeneratePlanRequest, GeneratePlanResponse, WeeklyPlanResponse, WorkoutPlan, WorkoutSegmentPlan,
    WeeklyPlanDetail, WorkoutDetail, WorkoutSegmentDetail, ExerciseDetail
)
from core.clients import gemini_model, supabase_client
from auth.dependencies import get_current_user_id

app = FastAPI(title="Virtual Coach Backend")

# --- Helper Functions --- 

def get_next_monday(start_date: Optional[date] = None) -> date:
    """Calculates the date of the upcoming Monday, or uses provided date if it is a Monday."""
    today = start_date if start_date else date.today()
    if start_date and start_date.weekday() != 0: # 0 is Monday
         raise HTTPException(status_code=400, detail="Provided week_start_date must be a Monday.")
    # If no date provided, find next Monday
    if not start_date:
        days_ahead = 0 - today.weekday() # Days until next Monday (0 if today is Monday)
        if days_ahead <= 0: # Target Monday has passed or is today
            days_ahead += 7
        today += timedelta(days=days_ahead)
    return today

async def get_user_levels(user_id: str) -> tuple[str | None, str | None]:
    """Fetches the user's assessed swim and run levels from the database."""
    try:
        response = supabase_client.table('fitness_assessments')\
                                .select('swim_level, run_level')\
                                .eq('user_id', user_id)\
                                .maybe_single()\
                                .execute()
        if response.data:
            return response.data.get('swim_level'), response.data.get('run_level')
        else:
            return None, None
    except Exception as e:
        print(f"Error fetching user levels for {user_id}: {e}")
        return None, None # Treat errors as levels not found

# --- API Endpoints --- 

@app.get("/")
async def read_root():
    return {"message": "Welcome to the Virtual Coach API"}


@app.post("/assessments", response_model=AssessmentResult)
async def create_assessment(
    assessment_data: OnboardingData,
    current_user_id: str = Depends(get_current_user_id)
):
    """Receives onboarding data, gets assessment from Gemini, saves result."""
    print(f"Received assessment request for user {current_user_id}")

    # 1. Construct Prompt for Gemini
    prompt = f"""
    Analyze the following user fitness data and assess their levels.
    User Data:
    - Running Experience: {assessment_data.runExperience}
    - Typical Run Duration: {assessment_data.runDuration}
    - Swimming Experience: {assessment_data.swimExperience}
    - Typical Swim Duration: {assessment_data.swimDuration}
    - Primary Goal: {assessment_data.primaryGoal}

    Based ONLY on this data, assess the user's current running level and swimming level.
    Choose ONLY from these levels for each: Beginner, Intermediate, Advanced.
    
    Respond ONLY with a valid JSON object containing the keys 'run_level' and 'swim_level'. 
    Example:
    {{"run_level": "Intermediate", "swim_level": "Beginner"}}
    """

    # 2. Call Gemini API
    try:
        print("Sending prompt to Gemini...")
        response = gemini_model.generate_content(prompt)
        
        # Attempt to parse the response as JSON
        print(f"Received response text: {response.text}")
        # Clean the response text in case of markdown code blocks
        cleaned_text = response.text.strip().replace('```json', '').replace('```', '').strip()
        gemini_result_json = json.loads(cleaned_text)
        
        # Validate the JSON structure
        gemini_assessment = GeminiAssessmentResponse(**gemini_result_json)
        
        print(f"Gemini assessment: Run={gemini_assessment.run_level}, Swim={gemini_assessment.swim_level}")

    except json.JSONDecodeError as e:
        print(f"Error decoding Gemini JSON response: {e}")
        print(f"Raw response was: {response.text}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to parse assessment from AI. Invalid JSON."
        )
    except ValidationError as e:
         print(f"Error validating Gemini response structure: {e}")
         print(f"Parsed JSON was: {gemini_result_json}")
         raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI assessment response has unexpected structure."
        )
    except Exception as e:
        # Catch other potential errors from Gemini API call
        print(f"Error calling Gemini API: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get assessment from AI."
        )

    # 3. Save results to Supabase
    try:
        print("Saving assessment to database...")
        assessment_insert_data = {
            'user_id': current_user_id,
            'assessment_data': assessment_data.model_dump(),
            'run_level': gemini_assessment.run_level,
            'swim_level': gemini_assessment.swim_level
        }
        insert_response = supabase_client.table('fitness_assessments').insert(assessment_insert_data).execute()
        
        if insert_response.data:
            print("Assessment saved.")
        else:
             # Log error details if available from the response
            print(f"Failed to insert assessment: {getattr(insert_response, 'error', 'Unknown error')}")
            raise HTTPException(status_code=500, detail="Failed to save assessment data.")

        # 4. Update profile onboarding status
        print("Updating profile onboarding status...")
        update_response = supabase_client.table('profiles')\
                         .update({'onboarding_completed': True})\
                         .eq('id', current_user_id)\
                         .execute()
                         
        if update_response.data:
             print("Profile updated.")
        else:
            # Log error but proceed, as assessment was saved.
            print(f"Warning: Failed to update profile onboarding status: {getattr(update_response, 'error', 'Unknown error')}")
            # Optionally raise an error if this update is critical
            # raise HTTPException(status_code=500, detail="Failed to update profile status.")
            
    except Exception as e:
        # Catch potential Supabase errors
        print(f"Database error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save assessment results to database."
        )

    # 5. Return result
    return AssessmentResult(
        run_level=gemini_assessment.run_level,
        swim_level=gemini_assessment.swim_level,
        message="Assessment completed successfully."
    )

@app.post("/plans/generate", response_model=GeneratePlanResponse)
async def generate_plan(
    request_data: GeneratePlanRequest,
    current_user_id: str = Depends(get_current_user_id)
):
    """Generates a weekly plan using Gemini based on user's assessed levels."""
    print(f"Received plan generation request for user {current_user_id}")

    # 1. Determine target week start date
    target_week_start = get_next_monday(request_data.week_start_date)
    print(f"Target week start date: {target_week_start}")

    # 2. Check if user has completed onboarding / get levels
    swim_level, run_level = await get_user_levels(current_user_id)
    if not swim_level or not run_level:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User fitness assessment not found or incomplete. Please complete onboarding."
        )
    print(f"User levels: Swim={swim_level}, Run={run_level}")

    # 3. Check if a plan already exists for this week (optional, could allow overwrite)
    try:
        existing_plan_response = supabase_client.table('plans')\
                                          .select('id')\
                                          .eq('user_id', current_user_id)\
                                          .eq('week_start_date', target_week_start.isoformat())\
                                          .maybe_single()\
                                          .execute()
        if existing_plan_response.data:
            print(f"Plan already exists for {target_week_start}. ID: {existing_plan_response.data['id']}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, 
                detail=f"A plan already exists for the week starting {target_week_start}."
            )
    except Exception as e:
        print(f"Database error checking for existing plan: {e}")
        raise HTTPException(status_code=500, detail="Error checking for existing plan.")

    # 4. Construct Prompt for Gemini Plan Generation
    # TODO: Refine this prompt significantly based on testing and desired plan structure.
    # Need to be VERY specific about JSON output format, including segment details.
    plan_prompt = f"""
    Generate a 7-day blended training plan for an athlete with the following levels:
    - Running Level: {run_level}
    - Swimming Level: {swim_level}
    The plan is for the week starting Monday, {target_week_start.strftime('%Y-%m-%d')}. 
    Include a mix of Running, Swimming, and Rest days.
    For each workout day (non-Rest), provide a title and detailed segments (like WarmUp, MainSet, CoolDown).
    Specify duration_minutes OR distance_meters for segments, and target_intensity (e.g., Easy, Tempo, Intervals, Threshold).
    If a segment involves a specific known drill (like 'Catch-up Drill' or 'High Knees'), include its name in 'exercise_name'.

    Respond ONLY with a valid JSON object containing a single key "workouts".
    The value of "workouts" should be a list of 7 JSON objects, one for each day (index 0 for Monday, 6 for Sunday).
    Each workout object must have:
      "day_index": (integer 0-6)
      "activity_type": (string "Swimming", "Running", or "Rest")
      "title": (string, optional, null if Rest)
      "segments": (list of segment objects, optional, null if Rest)
    Each segment object must have:
      "segment_order": (integer, starting from 1)
      "segment_type": (string, e.g., "WarmUp", "MainSet", "Drill", "CoolDown")
      "duration_minutes": (integer, optional)
      "distance_meters": (integer, optional)
      "target_intensity": (string, optional)
      "exercise_name": (string, optional, if a known drill)
      "reps": (integer, optional)
      "rest_duration_seconds": (integer, optional)
      "notes": (string, optional)

    Example Segment: {{"segment_order": 1, "segment_type": "WarmUp", "duration_minutes": 10, "target_intensity": "Easy", "notes": "Light jog"}}
    Example Rest Day: {{"day_index": 2, "activity_type": "Rest", "title": null, "segments": null}}
    Example Workout Day: {{"day_index": 0, "activity_type": "Running", "title": "Easy Run", "segments": [ ... list of segment objects ... ]}}
    Ensure the final output is ONLY the JSON object starting with {{ and ending with }}.
    """

    # 5. Call Gemini API for Plan
    try:
        print("Sending plan prompt to Gemini...")
        plan_response = gemini_model.generate_content(plan_prompt)
        print(f"Received plan response text: {plan_response.text}")
        plan_cleaned_text = plan_response.text.strip().replace('```json', '').replace('```', '').strip()
        plan_result_json = json.loads(plan_cleaned_text)

        # Validate structure using Pydantic model
        weekly_plan = WeeklyPlanResponse(**plan_result_json)
        print(f"Successfully parsed weekly plan from Gemini.")

    except json.JSONDecodeError as e:
        print(f"Error decoding Gemini JSON plan response: {e}")
        print(f"Raw response was: {plan_response.text}")
        raise HTTPException(status_code=500, detail="Failed to parse plan from AI. Invalid JSON.")
    except ValidationError as e:
         print(f"Error validating Gemini plan structure: {e}")
         print(f"Parsed JSON was: {plan_result_json}")
         raise HTTPException(status_code=500, detail="AI plan response has unexpected structure.")
    except Exception as e:
        print(f"Error calling Gemini API for plan: {e}")
        raise HTTPException(status_code=500, detail="Failed to get plan from AI.")

    # 6. Save the generated plan to Supabase (Transaction needed ideally)
    # TODO: Implement transactional saving if Supabase client supports it easily,
    # otherwise, handle potential partial saves with cleanup logic.
    new_plan_id = None
    try:
        print(f"Saving plan for week {target_week_start}...")
        # Insert Plan
        plan_insert_data = {
            'user_id': current_user_id,
            'week_start_date': target_week_start.isoformat()
        }
        plan_res = supabase_client.table('plans').insert(plan_insert_data).execute()
        if not plan_res.data:
            raise Exception(f"Failed to insert plan record: {getattr(plan_res, 'error', 'Unknown DB error')}")
        new_plan_id = plan_res.data[0]['id']
        print(f"Plan record created with ID: {new_plan_id}")

        # Insert Workouts and Segments
        for day_index, workout_plan in enumerate(weekly_plan.workouts):
            if workout_plan.day_index != day_index:
                 print(f"Warning: Mismatched day index from AI. Expected {day_index}, got {workout_plan.day_index}. Using {day_index}.")
            
            scheduled_date = target_week_start + timedelta(days=day_index)
            workout_insert_data = {
                'plan_id': new_plan_id,
                'user_id': current_user_id,
                'scheduled_date': scheduled_date.isoformat(),
                'activity_type': workout_plan.activity_type,
                'title': workout_plan.title,
                'status': 'Scheduled' # Default status
            }
            workout_res = supabase_client.table('workouts').insert(workout_insert_data).execute()
            if not workout_res.data:
                 raise Exception(f"Failed to insert workout for {scheduled_date}: {getattr(workout_res, 'error', 'Unknown DB error')}")
            new_workout_id = workout_res.data[0]['id']
            print(f"Workout record created for {scheduled_date} with ID: {new_workout_id}")

            # Insert Segments if they exist
            if workout_plan.segments and workout_plan.activity_type != 'Rest':
                segments_to_insert = []
                for segment_plan in workout_plan.segments:
                    # TODO: Optionally look up exercise_id from exercise_name if provided
                    # exercise_id = find_exercise_id_by_name(segment_plan.exercise_name) if segment_plan.exercise_name else None
                    segments_to_insert.append({
                        'workout_id': new_workout_id,
                        'user_id': current_user_id,
                        'segment_order': segment_plan.segment_order,
                        'segment_type': segment_plan.segment_type,
                        'duration_minutes': segment_plan.duration_minutes,
                        'distance_meters': segment_plan.distance_meters,
                        'target_intensity': segment_plan.target_intensity,
                        # 'exercise_id': exercise_id, # Add if lookup implemented
                        'reps': segment_plan.reps,
                        'rest_duration_seconds': segment_plan.rest_duration_seconds,
                        'notes': segment_plan.notes
                    })
                
                if segments_to_insert:
                    segment_res = supabase_client.table('workout_segments').insert(segments_to_insert).execute()
                    if not segment_res.data:
                         raise Exception(f"Failed to insert segments for workout {new_workout_id}: {getattr(segment_res, 'error', 'Unknown DB error')}")
                    print(f"Inserted {len(segment_res.data)} segments for workout {new_workout_id}")
            
        print(f"Successfully saved plan {new_plan_id} and all associated workouts/segments.")

    except Exception as e:
        # Basic Cleanup Attempt: If plan was created but workouts/segments failed, delete the plan.
        # More robust cleanup might be needed.
        if new_plan_id:
            print(f"Error saving workouts/segments for plan {new_plan_id}. Attempting to delete plan...")
            try:
                supabase_client.table('plans').delete().eq('id', new_plan_id).execute()
                print(f"Successfully deleted incomplete plan {new_plan_id}.")
            except Exception as cleanup_e:
                print(f"Error during cleanup deleting plan {new_plan_id}: {cleanup_e}")
        
        print(f"Database error during plan save: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save generated plan to database: {e}"
        )

    # 7. Return Success Response
    return GeneratePlanResponse(
        plan_id=str(new_plan_id), # Convert UUID to string
        week_start_date=target_week_start,
        message="Weekly plan generated successfully."
    )

@app.get("/plans/week/{week_start_date_str}", response_model=WeeklyPlanDetail)
async def get_weekly_plan(
    week_start_date_str: str,
    current_user_id: str = Depends(get_current_user_id)
):
    """Retrieves the detailed weekly plan for a given user and week start date."""
    print(f"Received request for plan for week {week_start_date_str} for user {current_user_id}")

    try:
        # Validate and parse the date string
        week_start_date = date.fromisoformat(week_start_date_str)
        if week_start_date.weekday() != 0: # 0 is Monday
             raise ValueError("Week start date must be a Monday.")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date format or not a Monday: {e}"
        )

    try:
        # 1. Fetch the plan for the user and week
        plan_res = supabase_client.table('plans')\
                             .select("id, user_id, week_start_date")\
                             .eq('user_id', current_user_id)\
                             .eq('week_start_date', week_start_date.isoformat())\
                             .maybe_single()\
                             .execute()

        if not plan_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail=f"Plan not found for the week starting {week_start_date_str}."
            )
        
        plan_data = plan_res.data
        plan_id = plan_data['id']
        print(f"Found plan with ID: {plan_id}")

        # 2. Fetch associated workouts
        workouts_res = supabase_client.table('workouts')\
                                 .select("*, workout_segments(*, exercises(*))")\
                                 .eq('plan_id', plan_id)\
                                 .order('scheduled_date', desc=False)\
                                 .order('segment_order', desc=False, foreign_table='workout_segments')\
                                 .execute()
        
        if not workouts_res.data:
            print(f"Warning: Plan {plan_id} found, but no workouts associated.")
            # Return the plan structure with an empty workouts list
            return WeeklyPlanDetail(
                plan_id=plan_id,
                user_id=plan_data['user_id'],
                week_start_date=plan_data['week_start_date'],
                workouts=[]
            )
        
        print(f"Found {len(workouts_res.data)} workouts for plan {plan_id}")
        
        # 3. Structure the response using Pydantic models
        detailed_workouts: List[WorkoutDetail] = []
        for workout_db in workouts_res.data:
            detailed_segments: List[WorkoutSegmentDetail] = []
            if workout_db.get('workout_segments'):
                for segment_db in workout_db['workout_segments']:
                    exercise_detail = None
                    if segment_db.get('exercises'): # exercises is the nested data
                        exercise_db = segment_db['exercises']
                        exercise_detail = ExerciseDetail(
                            id=exercise_db['id'],
                            name=exercise_db['name'],
                            youtube_url=exercise_db.get('youtube_url')
                        )
                    
                    detailed_segments.append(
                        WorkoutSegmentDetail(
                            id=segment_db['id'],
                            segment_order=segment_db['segment_order'],
                            segment_type=segment_db.get('segment_type'),
                            duration_minutes=segment_db.get('duration_minutes'),
                            distance_meters=segment_db.get('distance_meters'),
                            target_intensity=segment_db.get('target_intensity'),
                            reps=segment_db.get('reps'),
                            rest_duration_seconds=segment_db.get('rest_duration_seconds'),
                            notes=segment_db.get('notes'),
                            exercise=exercise_detail
                        )
                    )
            
            detailed_workouts.append(
                 WorkoutDetail(
                    id=workout_db['id'],
                    scheduled_date=workout_db['scheduled_date'],
                    activity_type=workout_db['activity_type'],
                    title=workout_db.get('title'),
                    status=workout_db['status'],
                    user_modified_activity=workout_db['user_modified_activity'],
                    user_modified_details=workout_db['user_modified_details'],
                    segments=detailed_segments
                 )
            )

        # 4. Assemble the final response object
        weekly_plan_detail = WeeklyPlanDetail(
            plan_id=plan_id,
            user_id=plan_data['user_id'],
            week_start_date=plan_data['week_start_date'],
            workouts=detailed_workouts
        )

        return weekly_plan_detail

    except HTTPException as http_exc:
        # Re-raise HTTP exceptions directly
        raise http_exc
    except Exception as e:
        print(f"Database error fetching plan details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve plan details."
        )

# Add other endpoints here later (admin, etc.) 