from database import User, SessionLocal

db = SessionLocal()
email = input("Email: ")
user = db.query(User).filter(User.email == email).first()

if user:
    print(f"Email: {user.email}")
    print(f"Plan: {user.plan}")
    print(f"Subscription Status: {user.subscription_status}")
    print(f"Analyses Used: {user.analyses_used}")
    print(f"Analyses Limit: {user.analyses_limit}")
else:
    print("User not found")
