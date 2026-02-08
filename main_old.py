from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import google.generativeai as genai
from dotenv import load_dotenv
from PIL import Image
import io

load_dotenv()

app = FastAPI(title="Trading Chart Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Google Gemini yapılandırması - DOĞRU MODEL
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

class AnalysisResponse(BaseModel):
    analysis: str
    trend: str
    confidence: str

@app.get("/")
async def root():
    return {"message": "Trading Chart Analysis API is running"}

@app.post("/analyze-image", response_model=AnalysisResponse)
async def analyze_image(file: UploadFile = File(...)):
    try:
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        image_data = await file.read()
        image = Image.open(io.BytesIO(image_data))
        
        prompt = """Analyze this trading chart screenshot.
        Identify trend direction, support/resistance zones,
        possible breakout areas, RSI or indicator signals if visible,
        and provide a short trading idea with risk warning.
        
        Format your response as follows:
        1. First line: State ONLY one word - either "bullish", "bearish", or "sideways"
        2. Second line: State ONLY one word - either "low", "medium", or "high" (confidence level)
        3. Rest: Provide your detailed analysis
        """
        
        # Google Gemini API çağrısı
        response = model.generate_content([prompt, image])
        
        ai_response = response.text.strip()
        lines = ai_response.split('\n')
        
        trend = lines[0].strip().lower() if len(lines) > 0 else "sideways"
        confidence = lines[1].strip().lower() if len(lines) > 1 else "medium"
        analysis = '\n'.join(lines[2:]).strip() if len(lines) > 2 else ai_response
        
        if trend not in ["bullish", "bearish", "sideways"]:
            trend = "sideways"
        if confidence not in ["low", "medium", "high"]:
            confidence = "medium"
        
        return AnalysisResponse(
            analysis=analysis,
            trend=trend,
            confidence=confidence
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
