#!/bin/bash
set -e

. ./.env
# Проверка на наличие всех необходимых переменных
if [ -z "$DOCKER_USERNAME" ] || [ -z "$DOCKER_PASSWORD" ] || [ -z "$IMAGE_NAME" ]; then
  echo "ERROR: Missing environment variables."
  exit 1
fi

# Авторизация в Docker Hub
echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin

# Сборка Docker образа с версией и latest тегом
docker build -t "$IMAGE_NAME:$IMAGE_VERSION" -t "$IMAGE_NAME:latest" -f ./compose/Dockerfile .

# Пушим оба тега на Docker Hub
docker push "$IMAGE_NAME:$IMAGE_VERSION"
docker push "$IMAGE_NAME:latest"

# Выход из Docker
docker logout

echo "Docker image $IMAGE_NAME:$IMAGE_VERSION and $IMAGE_NAME:latest pushed successfully!"