from setuptools import find_packages, setup


INSTALL_REQUIRES = [
    "alembic>=1.13.2",
    "asyncpg>=0.29.0",
    "fastapi>=0.122.0",
    "google-cloud-storage>=3.3.0",
    "httpx>=0.27.0,<0.28.0",
    "librosa>=0.10.2",
    "numpy>=1.26.4",
    "pydantic-settings>=2.3.4",
    "python-json-logger>=2.0.7",
    "python-multipart>=0.0.9",
    "soundfile>=0.12.1",
    "sqlalchemy>=2.0.30",
    "uvicorn[standard]>=0.30.1",
    "websockets>=13.0",
]


setup(
    name="pvc-backend",
    version="0.1.0",
    description="FastAPI backend for PVC",
    python_requires=">=3.11",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=INSTALL_REQUIRES,
    extras_require={
        "dev": [
            "aiosqlite>=0.20.0",
            "pytest>=8.2.2",
            "pytest-asyncio>=0.23.7",
        ]
    },
)
