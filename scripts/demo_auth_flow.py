
"""
Demo Script: Service Account Lifecycle
Run this to see the Human -> Bot -> Agent flow in action.
"""
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from backend import services
from backend.db import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

def run_demo():
    print("--- 🚀 Starting Service Account Demo ---")

    # 1. Setup In-Memory DB
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    
    with patch("backend.services.SessionLocal", Session):
        db = Session()
        services._seed_defaults(db)
        
        # 2. Human Admin Setup
        print("\n[Human] Creating Admin account...")
        admin = services.signup("admin", "Admin User", "password")
        print(f"✅ Admin created: {admin['name']} (ID: {admin['id']})")
        
        # 3. Human Creates Bot
        print("\n[Human] Going to Settings -> Create Bot 'code_assistant'...")
        bot_profile = services.create_service_account("code_assistant", "Code Assistant")
        api_key = bot_profile["api_key"]
        print(f"✅ Bot Profile Created!")
        print(f"   Name: {bot_profile['name']}")
        print(f"   Role: {bot_profile['role']}")
        print(f"   🔑 API KEY: {api_key} (Copied to clipboard)")
        
        # 4. Agent Starts Up (Simulated)
        print("\n[Agent] 🤖 Booting up with API KEY...")
        try:
            me = services.validate_api_key(api_key)
            print(f"✅ Agent Authenticated! I am: {me['name']}")
        except Exception as e:
            print(f"❌ Auth Failed: {e}")
            return

        # 5. Agent Configures Self
        print("\n[Agent] 🎨 Setting my personality...")
        updated = services.update_profile(
            me["id"], 
            display_name="Super Coder 3000", 
            avatar_url="http://example.com/bot.png"
        )
        print(f"✅ Identity Updated!")
        print(f"   Display Name: {updated['display_name']}")
        print(f"   Avatar: {updated['avatar_url']}")
        
        print("\n--- ✨ Demo Complete: Success! ---")

if __name__ == "__main__":
    run_demo()
