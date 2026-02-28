import re

with open("main.py", "r") as f:
    content = f.read()

# 1️⃣ get_current_user değiştir
content = re.sub(
    r"def get_current_user\([\s\S]*?except JWTError:\n\s+raise HTTPException\(status_code=401, detail=\"Invalid token\"\)\n",
    """from fastapi import Cookie

def get_current_user(
    access_token: str = Cookie(None),
    db: Session = Depends(get_db)
):
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(access_token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
""",
    content,
)

# 2️⃣ login endpoint değiştir
content = re.sub(
    r"@app.post\(\"/login\"\)[\s\S]*?return \{\"access_token\": token, \"token_type\": \"bearer\"\}",
    """from fastapi.responses import JSONResponse

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in")
    token = create_access_token({"sub": user.email})
    response = JSONResponse(content={"message": "Login successful"})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=60 * 60 * 24 * 30
    )
    return response
""",
    content,
)

# 3️⃣ logout ekle
if "/logout" not in content:
    content += """

from fastapi.responses import JSONResponse

@app.post("/logout")
def logout():
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("access_token")
    return response
"""

# 4️⃣ CORS düzelt
content = content.replace(
    'allow_origins=["https://www.tradeflowai.cloud"],',
    '''allow_origins=[
    "https://www.tradeflowai.cloud",
    "https://tradeflowai.cloud"
],'''
)

with open("main.py", "w") as f:
    f.write(content)

print("✅ Auth system upgraded to secure cookie version.")
