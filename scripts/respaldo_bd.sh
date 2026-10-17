#!/usr/bin/env bash
# Respaldo de la base de datos de NEXUS SPORTOPS (Supabase / cualquier PostgreSQL).
#
# Uso:
#   1) Guarda la URL de la base UNA vez (solo tú puedes leer el archivo):
#        echo 'RESPALDO_DATABASE_URL=postgresql://usuario:clave@host:6543/postgres' > ~/.nexus_respaldo.env
#        chmod 600 ~/.nexus_respaldo.env
#   2) Ejecuta:  ./scripts/respaldo_bd.sh
#
# Deja archivos nexus_AAAA-MM-DD_HHMM.dump en ~/Respaldos/nexus (o en RESPALDO_DIR)
# y conserva solo los últimos RESPALDO_CONSERVAR (30 por defecto).
# Necesita Docker (usa la imagen oficial de PostgreSQL, no hay que instalar nada más).
#
# Restaurar en una base vacía:
#   docker run --rm -i postgres:17 pg_restore --no-owner --no-acl --clean --if-exists -d "URL_DESTINO" < archivo.dump
set -euo pipefail

ARCHIVO_ENV="${RESPALDO_ENV:-$HOME/.nexus_respaldo.env}"
if [[ -z "${RESPALDO_DATABASE_URL:-}" && -f "$ARCHIVO_ENV" ]]; then
    # shellcheck disable=SC1090
    source "$ARCHIVO_ENV"
fi
if [[ -z "${RESPALDO_DATABASE_URL:-}" ]]; then
    echo "Falta RESPALDO_DATABASE_URL (en el entorno o en $ARCHIVO_ENV)." >&2
    exit 1
fi

# pg_dump no funciona bien con el pooler en modo transacción (puerto 6543)
# de Supabase: se usa el modo sesión (puerto 5432) del mismo servidor.
URL="${RESPALDO_DATABASE_URL/pooler.supabase.com:6543/pooler.supabase.com:5432}"

DIR="${RESPALDO_DIR:-$HOME/Respaldos/nexus}"
CONSERVAR="${RESPALDO_CONSERVAR:-30}"
IMAGEN="${RESPALDO_IMAGEN:-postgres:17}"
mkdir -p "$DIR"
DESTINO="$DIR/nexus_$(date +%Y-%m-%d_%H%M).dump"
TEMPORAL="$DESTINO.parcial"
# Si algo falla, no dejar archivos a medias
trap 'rm -f "$TEMPORAL"' EXIT

# Solo el esquema "public" (tus datos). Supabase tiene esquemas internos
# (auth, storage...) que no son de la app y no se pueden restaurar en otro lado.
docker run --rm "$IMAGEN" pg_dump "$URL" --schema=public --format=custom \
    --no-owner --no-acl --compress=9 > "$TEMPORAL"

# Verifica que el archivo se pueda leer antes de darlo por bueno
TABLAS=$(docker run --rm -i "$IMAGEN" pg_restore --list < "$TEMPORAL" | grep -c "TABLE DATA" || true)
if [[ "$TABLAS" -lt 10 ]]; then
    echo "El respaldo parece incompleto ($TABLAS tablas). Se descarta." >&2
    rm -f "$TEMPORAL"
    exit 1
fi
mv "$TEMPORAL" "$DESTINO"

# Borra los respaldos más antiguos
ls -1t "$DIR"/nexus_*.dump 2>/dev/null | tail -n +"$((CONSERVAR + 1))" | xargs -r rm -f

echo "Respaldo OK: $DESTINO ($(du -h "$DESTINO" | cut -f1), $TABLAS tablas)"
