#!/bin/bash

# Array: Dockerfile -> imagen
declare -a builds=(
  "Dockerfile.lassets dese251/sviwan22:lassets2"
  "Dockerfile.hassets dese251/sviwan22:hassets2"
  "Dockerfile.runtime dese251/sviwan22:run2"
  "Dockerfile.lora2 dese251/sviwan22:lora2"
)

echo "Iniciando builds de Docker secuencialmente..."

for item in "${builds[@]}"; do
  DOCKERFILE=$(echo $item | awk '{print $1}')
  IMAGE=$(echo $item | awk '{print $2}')
  LOGFILE="build_$(echo $IMAGE | tr '/:' '__').log"

  echo "Lanzando $DOCKERFILE -> $IMAGE"

  # Ejecutar build de Docker, espera a que termine antes de continuar
  echo '==== $(date) ====' >> "$LOGFILE"
  echo "Building $IMAGE using $DOCKERFILE" >> "$LOGFILE"
  docker build --no-cache -f $DOCKERFILE -t $IMAGE . >> "$LOGFILE" 2>&1

  # Hacer push a Docker Hub
  echo "Haciendo push de la imagen $IMAGE a Docker Hub..." >> "$LOGFILE"
  docker push $IMAGE >> "$LOGFILE" 2>&1

  # Limpiar imágenes no usadas
  echo "Limpiando imágenes no usadas..." >> "$LOGFILE"
  docker image prune -f >> "$LOGFILE" 2>&1

  echo "Build y push terminados: $IMAGE" >> "$LOGFILE"
done

echo "Todos los builds fueron completados."
echo "Puedes cerrar la sesión sin problema."
echo ""
echo "Para ver logs:"
echo "ls build_*.log"
echo "tail -f build_*.log"