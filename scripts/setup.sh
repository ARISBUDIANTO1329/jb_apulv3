#!/bin/bash
set -e

echo "🚀 Setting up JB APUL v3..."

# Copy env if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ Created .env from .env.example"
    echo "⚠️  Please edit .env with your credentials!"
fi

# Build and start Docker containers
echo "🐳 Building Docker containers..."
docker-compose build

echo "▶️  Starting services..."
docker-compose up -d

echo "⏳ Waiting for database..."
sleep 5

echo "✅ Setup complete!"
echo ""
echo "Services:"
echo "  Frontend:  http://localhost:3000"
echo "  Backend:   http://localhost:8000"
echo "  API docs:  http://localhost:8000/docs"
echo ""
echo "Commands:"
echo "  docker-compose up -d      # Start all services"
echo "  docker-compose down        # Stop all services"
echo "  docker-compose logs -f     # View logs"
echo "  docker-compose exec backend python -c 'from app.models import *; print(\"Models OK\")'  # Test DB"
