FROM golang:1.25-alpine AS builder

WORKDIR /app

RUN apk add --no-cache gcc musl-dev

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/server ./cmd/api && \
    CGO_ENABLED=0 GOOS=linux go build -o /bin/mocksrv ./cmd/mocksrv

FROM alpine:3.19

RUN apk add --no-cache ca-certificates tzdata && mkdir -p /data

COPY --from=builder /bin/server /bin/server
COPY --from=builder /bin/mocksrv /bin/mocksrv

EXPOSE 8080
CMD ["/bin/server"]
