#!/bin/bash
set -euo pipefail

echo "🔍 Verifying migration..."

# Start services
docker-compose -f infra/docker-compose.yml up -d

# Wait for services to come up
sleep 20

# Test new API health endpoint
curl -f http://localhost:8000/api/v1/health || {
  echo "❌ API health check failed";
  exit 1;
}

# Test frontend root
curl -f http://localhost:3000 || {
  echo "❌ Frontend check failed";
  exit 1;
}

echo "✅ Migration verified!"
