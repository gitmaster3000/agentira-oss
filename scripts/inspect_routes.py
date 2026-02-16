
from backend.mcp_server import app
from starlette.routing import Route, Mount

def print_routes(routes, prefix=""):
    for route in routes:
        if isinstance(route, Route):
            print(f"{prefix}{route.path} [{', '.join(route.methods)}]")
        elif isinstance(route, Mount):
            print_routes(route.routes, prefix + route.path)

if __name__ == "__main__":
    print_routes(app.routes)
