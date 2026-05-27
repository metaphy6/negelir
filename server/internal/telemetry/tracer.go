// Package telemetry wires the §9.8 OTLP trace-export pipeline.
//
// Design contract:
//   - When TelemetryOTLPEndpoint is empty, Init is a deliberate no-op: no
//     goroutines, no connections, no stdout-JSON trace dump (too noisy).
//     The global TracerProvider remains the OTEL SDK default no-op provider, so
//     every span call in the OTelSpan middleware is a zero-cost allocation-free
//     operation.
//   - When endpoint is set, Init configures an OTLP gRPC BatchSpanProcessor and
//     sets it as the global TracerProvider alongside a W3C TraceContext propagator.
//     The returned shutdown function must be deferred in main() to flush pending
//     spans on graceful exit.
//
// PII discipline: span attributes must never include raw user_id, email, or IP.
// Use user_id_h (sha256 hash truncated to 12 hex chars) or anon_subject_key if
// user context is needed in a future extension.
package telemetry

import (
	"context"
	"fmt"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	sdkresource "go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

// ServiceName is the canonical OTEL service.name resource attribute for the
// Go API binary. Consumers (OTel Collector, Jaeger, Tempo) use this to scope
// traces to this service.
const ServiceName = "negelir-api"

// Init sets up the global OTEL TracerProvider and W3C text-map propagator.
//
// Parameters:
//   - ctx: used as the connection context for the OTLP gRPC dial; a Background
//     context is appropriate in main().
//   - endpoint: OTLP gRPC collector address ("host:port", no scheme). When
//     empty, Init returns immediately with a no-op shutdown function and nil error.
//   - serviceVersion: embedded in the "service.version" resource attribute.
//     Pass the chart.json server component version (e.g. "1.31.1").
//
// Returns a shutdown function — always non-nil — and an error. The caller must
// defer shutdown(ctx) to ensure buffered spans are flushed before the process
// exits.
func Init(ctx context.Context, endpoint, serviceVersion string) (func(context.Context) error, error) {
	if endpoint == "" {
		// Deliberate no-op: leave the global provider as the SDK default
		// no-op provider so the OTelSpan middleware costs nothing.
		return func(context.Context) error { return nil }, nil
	}

	exp, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithEndpoint(endpoint),
		otlptracegrpc.WithInsecure(), // TLS terminated at the collector sidecar.
	)
	if err != nil {
		return nil, fmt.Errorf("telemetry.Init: OTLP gRPC exporter: %w", err)
	}

	res, err := sdkresource.New(ctx,
		sdkresource.WithAttributes(
			semconv.ServiceName(ServiceName),
			semconv.ServiceVersion(serviceVersion),
		),
	)
	if err != nil {
		return nil, fmt.Errorf("telemetry.Init: resource: %w", err)
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exp),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.TraceContext{})

	return tp.Shutdown, nil
}
