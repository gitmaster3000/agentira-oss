
from backend import services

def setup_agent_profile():
    print("Setting up antigravity profile...")
    try:
        # Create profile antigravity with admin role for now so I can create tasks
        services.create_profile(
            name="antigravity",
            display_name="Antigravity Agent",
            role="admin",
            password="agent-password-123"
        )
        print("Profile created.")
    except Exception as e:
        print(f"Profile creation failed (might already exist): {e}")

    try:
        # Add to project
        # Project ID: de0cba8f11fc
        services.add_project_member("de0cba8f11fc", "antigravity", actor="system")
        print("Added to project.")
    except Exception as e:
        print(f"Project member addition failed: {e}")

if __name__ == "__main__":
    setup_agent_profile()
