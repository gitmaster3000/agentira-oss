from backend.db import wait_for_db
from backend.services import bootstrap

if __name__ == "__main__":
    print("Waiting for database...")
    wait_for_db()  # tolerate Railway private-network startup delay
    print("Bootstrapping AgentIRA Database...")
    bootstrap()
    print("Database bootstrapped and defaults seeded successfully.")
