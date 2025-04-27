from fastapi import FastAPI, HTTPException, Depends, status
from pydantic import ValidationError
import json

from schemas import OnboardingData, AssessmentResult, GeminiAssessmentResponse
from core.clients import gemini_model, supabase_client
from auth.dependencies import get_current_user_id

app = FastAPI(title="Virtual Coach Backend")


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

# Add other endpoints here later (plans, admin, etc.) 