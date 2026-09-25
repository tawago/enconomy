import os

import uvicorn

from pop.main import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host=os.environ.get("POP_HOST", "0.0.0.0"), port=int(os.environ.get("POP_PORT", "8000")))
