#!/bin/sh
# One image, two topologies:
#
#   with --id  → run a single node (docker-compose: one container per node)
#   no args    → run the whole cluster behind $PORT (Render/Fly/Railway, which
#                expose exactly one port)
#
# This is why the image works whether the host builds it as a plain web
# service or through render.yaml.
set -e

case " $* " in
  *" --id "*)
    exec python -m kvstore.node --host 0.0.0.0 --port "${NODE_PORT:-8000}" "$@"
    ;;
esac

exec python launch_cluster.py \
  --nodes "${HELIX_NODES:-3}" \
  --host 0.0.0.0 \
  --revive "${HELIX_REVIVE:-15}" \
  --base-port "${PORT:-8001}"
