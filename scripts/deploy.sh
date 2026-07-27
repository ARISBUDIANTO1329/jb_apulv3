#!/bin/bash
# JB APUL v3 - Deploy to SSH
# Usage: ./scripts/deploy.sh

set -e

SSH_HOST="deploy@137.184.48.104"
REMOTE_DIR="/var/www/jb_apulv3_new"

echo "🚀 Deploying JB APUL v3 to $SSH_HOST..."

# 1. Create remote directory
echo "📁 Creating remote directory..."
ssh $SSH_HOST "sudo mkdir -p $REMOTE_DIR && sudo chown deploy:deploy $REMOTE_DIR"

# 2. Sync files (exclude node_modules, __pycache__, .git, storage)
echo "📦 Syncing files..."
rsync -avz --progress \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.git' \
  --exclude='storage' \
  --exclude='.next' \
  --exclude='*.pyc' \
  ./ $SSH_HOST:$REMOTE_DIR/

# 3. Create .env for production if not exists
echo "⚙️ Checking .env..."
ssh $SSH_HOST "if [ ! -f $REMOTE_DIR/.env ]; then
  cat > $REMOTE_DIR/.env << 'EOF'
# Database
POSTGRES_DB=jb_apulv3
POSTGRES_USER=jb_user
POSTGRES_PASSWORD=$(openssl rand -base64 32)

# Backend
SECRET_KEY=$(openssl rand -base64 64)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
YOUTUBE_API_KEY=

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8001
EOF
  echo '✅ .env created with random passwords'
else
  echo '✅ .env already exists'
fi"

# 4. Install Docker if not installed
echo "🐳 Checking Docker..."
ssh $SSH_HOST "if ! command -v docker &> /dev/null; then
  echo 'Installing Docker...'
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker \$USER
  echo '✅ Docker installed'
else
  echo '✅ Docker already installed'
fi"

# 5. Install Docker Compose if not installed
ssh $SSH_HOST "if ! command -v docker-compose &> /dev/null; then
  echo 'Installing Docker Compose...'
  sudo apt-get update && sudo apt-get install -y docker-compose
  echo '✅ Docker Compose installed'
else
  echo '✅ Docker Compose already installed'
fi"

# 6. Build and start containers
echo "🔨 Building and starting containers..."
ssh $SSH_HOST "cd $REMOTE_DIR && docker-compose down && docker-compose up -d --build"

# 7. Wait for services
echo "⏳ Waiting for services to start..."
sleep 10

# 8. Check status
echo "📊 Checking status..."
ssh $SSH_HOST "cd $REMOTE_DIR && docker-compose ps"

# 9. Check health
echo "🏥 Checking health..."
ssh $SSH_HOST "curl -s http://localhost:8001/api/health || echo 'Backend not ready yet'"

echo ""
echo "✅ Deploy selesai!"
echo "🌐 Akses di: http://137.184.48.104/"
echo ""
echo "📋 Next steps:"
echo "  1. SSH ke server: ssh $SSH_HOST"
echo "  2. Edit .env: nano $REMOTE_DIR/.env"
echo "  3. Tambah API keys (Google, YouTube)"
echo "  4. Restart: cd $REMOTE_DIR && docker-compose restart"
