
import sys
import os

# Add backend to path
sys.path.append('c:/agentira')

from backend.services import create_service_account, list_profiles
import json

agents = [
    "customer-engagement",
    "docus",
    "frontend",
    "junior-coder",
    "mastercoder",
    "product-owner"
]

# Note: Architect already has fbe6e549...

results = {}

existing_profiles = {p['name']: p for p in list_profiles(role="bot")}

for agent_id in agents:
    if agent_id in existing_profiles:
        print(f"Profile {agent_id} already exists. Skip creation (but we need the key).")
        # Since we can't easily get the key back if we don't store it, 
        # for this script we might just recreate or use get_service_account if we have ID.
        # But get_service_account needs profile_id (UUID).
        prof = existing_profiles[agent_id]
        # We need to get the API key. get_service_account(prof['id'])
        from backend.services import get_service_account
        prof_detail = get_service_account(prof['id'])
        api_key = prof_detail['api_key']
    else:
        print(f"Creating profile for {agent_id}...")
        prof = create_service_account(name=agent_id, display_name=agent_id.capitalize())
        api_key = prof['api_key']
    
    results[agent_id] = api_key
    
    # Provision mcporter.json
    workspace = f"C:/openclaw team/{agent_id}"
    os.makedirs(workspace, exist_ok=True)
    mc_path = os.path.join(workspace, "mcporter.json")
    
    config = {
        "mcpServers": {
            "agentira": {
                "url": "http://127.0.0.1:8000/mcp",
                "headers": {
                    "Authorization": f"Bearer {api_key}"
                }
            }
        }
    }
    
    with open(mc_path, "w") as f:
        json.dump(config, f, indent=4)
        
    print(f"Provisioned {mc_path}")

print("\nAll provisioning complete.")
print(json.dumps(results, indent=2))
