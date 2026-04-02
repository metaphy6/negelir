FROM golang:1.23-alpine AS builder

WORKDIR /app

RUN apk add --no-cache gcc musl-dev

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/server ./cmd/main.go

FROM alpine:3.19

RUN apk add --no-cache ca-certificates tzdata && mkdir -p /data

COPY --from=builder /bin/server /bin/server

EXPOSE 8080
CMD ["/bin/server"]
