# Pinned, not `:latest`. A floating tag lets a rebuild cross a major version silently, and
# this is the one service where that is more than a reproducibility complaint: the rate
# limiter is a hand-rolled Lua script on `redis.asyncio` (see docs/TECHNICAL_DECISIONS.md --
# `limits[redis]` pins redis<8 against this project's client >=8, so there is no library to
# fall back to). A server major arriving unannounced would change EVAL/sorted-set behaviour
# underneath it. Dependabot watches this directory (`docker` ecosystem, weekly, grouped as
# `base-images`), so the pin gets maintained rather than left to rot -- under `:latest` there
# was nothing for it to bump.
FROM redis:8.10.0

RUN mkdir -p /usr/local/etc/redis
COPY redis.conf /usr/local/etc/redis/redis.conf

# The redis-server process was already non-root: the official entrypoint re-execs through
# `gosu redis` when argv[0] is `redis-server` and the uid is 0, which is exactly this CMD.
# Static config scanners cannot see that, so they report the image as running as root.
# Declaring the user is supported by design -- upstream's own comment on that branch reads
# "allow the container to be started with `--user`" -- and lands in the same place, so this
# answers the scanner instead of suppressing it.
#
# It is only safe while nothing is written to disk. Setting USER skips the entrypoint's
# `find . \! -user redis -exec chown redis '{}' +`, so if redis.conf ever enables persistence
# (`save`, `appendonly yes`) or a volume is mounted at /data, redis would be unable to write
# to a path it no longer owns -- surfacing as a dump error at runtime, not a failure at boot.
# redis.conf currently sets `save ""` and `appendonly no`, and the compose service mounts no
# volume; that is what makes this line correct today. Re-enabling persistence means dropping
# this line or pre-chowning the volume to uid 999.
#
# Must follow the mkdir/COPY above, which write to /usr/local/etc as root.
USER redis

# Informational only, and deliberately matching `port 6379` in redis.conf. The compose
# mapping is `${REDIS_PORT:-6379}` on *both* sides, so setting REDIS_PORT to anything else
# moves the container-side port while redis.conf keeps listening on 6379 and the service
# becomes unreachable. If REDIS_PORT ever has to move, redis.conf's `port` moves with it.
EXPOSE 6379

CMD ["redis-server", "/usr/local/etc/redis/redis.conf"]
