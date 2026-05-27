// Package headers contains pre-canonicalized HTTP header name constants for
// the Phase 9 API hot path.
//
// Using compile-time string constants instead of inline string literals
// (a) prevents typos, (b) removes any runtime canonicalization cost, and
// (c) satisfies the §9.17.2 header-allocation discipline: no fmt.Sprintf
// or runtime string construction is permitted in the response-write hot path.
//
// All constants are already in canonical MIME header form
// (Title-Case-With-Dashes), matching the output of
// textproto.CanonicalMIMEHeaderKey so that net/http never has to allocate
// a canonicalized copy.
package headers

const (
	// Standard response headers.
	ContentType   = "Content-Type"
	ContentLength = "Content-Length"
	CacheControl  = "Cache-Control"
	ETag          = "ETag"
	Vary          = "Vary"
	Location      = "Location"
	RetryAfter    = "Retry-After"

	// Standard request headers (read path).
	Authorization = "Authorization"
	IfNoneMatch   = "If-None-Match"
	IfMatch       = "If-Match"
	Accept        = "Accept"

	// Negelir custom headers.
	RequestID           = "X-Request-Id"
	XCache              = "X-Cache"
	XRateLimit          = "X-Ratelimit-Limit"
	XRateLimitRemaining = "X-Ratelimit-Remaining"
	XRateLimitReset     = "X-Ratelimit-Reset"
	XCorrelationID      = "X-Correlation-Id"
	XAPIVersion         = "X-Api-Version"

	// Security / auth headers.
	WWWAuthenticate = "Www-Authenticate"

	// Content-Type values (pre-canonicalized; use as second arg to Set/Add).
	MIMEApplicationJSON        = "application/json; charset=utf-8"
	MIMEApplicationProblemJSON = "application/problem+json; charset=utf-8"
	MIMETextPlain              = "text/plain; charset=utf-8"
	MIMETextCSV                = "text/csv; charset=utf-8"
)
