package middleware

import (
	"crypto/rand"
	"net/http"

	"github.com/gin-gonic/gin"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/propagation"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	oteltrace "go.opentelemetry.io/otel/trace"
)

// otelInstrumentationName must match telemetry.ServiceName; kept as a
// package-level constant so the middleware does not import the telemetry
// package (avoiding a cycle).
const otelInstrumentationName = "negelir-api"

// OTelSpan is a Gin middleware that wraps each request in an OTEL server span.
//
// When no real TracerProvider is configured (TelemetryOTLPEndpoint is empty),
// the global provider is the SDK default no-op provider, so this middleware
// adds negligible overhead — all span operations are allocation-free no-ops.
//
// Span name: "<METHOD> <matched-route>" (e.g. "GET /v1/matches/:id").
// The matched route is resolved after c.Next() so it reflects the OpenAPI
// pattern, never a substituted ID (cardinality safe).
//
// Span attributes (subset of structured-log fields, no PII):
//   - http.route      — matched OpenAPI route pattern
//   - http.request.method — HTTP verb
//   - http.response.status_code — integer status code
//
// PII policy: raw user_id, email, and IP MUST NOT appear as span attributes.
// If user context is needed in future, use user_id_h (12-hex hash) or
// anon_subject_key — never the raw values.
//
// Trace-ID alignment: the middleware seeds the OTEL span context from the
// trace_id stored in the Gin context by the TraceParent middleware (which has
// already parsed or minted the W3C trace_id). This ensures the OTEL span's
// trace_id matches the trace_id field in the structured access log.
// When an upstream Traceparent header is present the propagator extracts it
// directly, which also preserves the trace_id alignment.
//
// Placement: OTelSpan MUST be registered after middleware.TraceParent() so
// the Gin context already contains ContextKeyTraceID.
func OTelSpan() gin.HandlerFunc {
	return func(c *gin.Context) {
		propagator := otel.GetTextMapPropagator()
		tracer := otel.Tracer(otelInstrumentationName)

		// Extract remote span context from the incoming request headers.
		// When the TracerProvider is no-op, Extract is a no-op.
		ctx := propagator.Extract(c.Request.Context(), propagation.HeaderCarrier(c.Request.Header))

		// If the propagator did not yield a valid remote span context (no
		// upstream Traceparent header), seed the context from the trace_id
		// already minted by the TraceParent middleware. This guarantees the
		// OTEL span's trace_id matches the structured log's trace_id.
		if !oteltrace.SpanContextFromContext(ctx).IsValid() {
			if traceIDHex := c.GetString(ContextKeyTraceID); traceIDHex != "" {
				if tid, err := oteltrace.TraceIDFromHex(traceIDHex); err == nil {
					var sid [8]byte
					if _, randErr := rand.Read(sid[:]); randErr == nil {
						sc := oteltrace.NewSpanContext(oteltrace.SpanContextConfig{
							TraceID:    tid,
							SpanID:     oteltrace.SpanID(sid),
							TraceFlags: oteltrace.FlagsSampled,
							Remote:     true,
						})
						ctx = oteltrace.ContextWithRemoteSpanContext(ctx, sc)
					}
				}
			}
		}

		ctx, span := tracer.Start(ctx, c.Request.Method,
			oteltrace.WithSpanKind(oteltrace.SpanKindServer),
		)

		// Propagate the span context so nested handlers can create child spans.
		c.Request = c.Request.WithContext(ctx)

		c.Next()

		// Set span name and attributes after routing so c.FullPath() returns
		// the matched OpenAPI pattern (e.g. /v1/matches/:id), not the raw URL.
		route := c.FullPath()
		if route == "" {
			route = "unknown"
		}
		status := c.Writer.Status()

		span.SetName(c.Request.Method + " " + route)
		span.SetAttributes(
			semconv.HTTPRoute(route),
			semconv.HTTPRequestMethodKey.String(c.Request.Method),
			semconv.HTTPResponseStatusCode(status),
		)
		if status >= http.StatusInternalServerError {
			span.SetStatus(codes.Error, http.StatusText(status))
		} else {
			span.SetStatus(codes.Ok, "")
		}
		span.End()
	}
}
