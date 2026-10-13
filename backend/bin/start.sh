# Make sure pwd ends with backend
if [ "$(basename "$PWD")" != "backend" ]; then
  echo "Error: Please run this script from the backend directory"
  exit 1
fi

# Make sure .venv exists
if [ ! -d ".venv" ]; then
  echo "Error: .venv directory not found"
  exit 1
fi

# Activate the virtual environment
source .venv/bin/activate

# Start the application
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
