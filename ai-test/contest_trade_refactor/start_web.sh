#!/bin/bash
# Start Python backend (FastAPI/SSE) and Next.js frontend

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "Starting Python backend on http://localhost:8000 ..."
cd "$ROOT"
.venv/bin/python web_app.py &
BACKEND_PID=$!

echo "Starting Next.js frontend on http://localhost:3000 ..."
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
