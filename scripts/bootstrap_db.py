from backend.services import bootstrap

if __name__ == "__main__":
    print("Bootstrapping AgentIRA Database...")
    bootstrap()
    print("Database bootstrapped and defaults seeded successfully.")
