FROM golang:1.25-alpine@sha256:8d95af53d0d58e1759ddb4028285d9b1239067e4fbf4f544618cad0f60fbc354 AS builder

WORKDIR /app

RUN apk add --no-cache gcc musl-dev

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/server ./cmd/api && \
    CGO_ENABLED=0 GOOS=linux go build -o /bin/mocksrv ./cmd/mocksrv

FROM alpine:3.19@sha256:6baf43584bcb78f2e5847d1de515f23499913ac9f12bdf834811a3145eb11ca1

RUN apk add --no-cache ca-certificates tzdata && mkdir -p /data

# Forbidden-dep probe: ensure database client libs are not present
RUN command -v psql >/dev/null 2>&1 && exit 1 || true

COPY --from=builder /bin/server /bin/server
COPY --from=builder /bin/mocksrv /bin/mocksrv

EXPOSE 8080
CMD ["/bin/server"]
