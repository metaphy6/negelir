package middleware

// deprecation.go -- Phase 9 section 9.11 versioning and deprecation sunset policy.
//
// DeprecationHeaders inspects the OpenAPI spec passed at construction time for
// x-deprecated-on / x-sunset-on extensions on each route operation. For every
// incoming request it checks the matched route pattern (Gin's c.FullPath()) and,
// when the route is deprecated:
//
//   - Before the sunset date: adds Sunset and Link headers, calls c.Next().
//   - On or after the sunset date: aborts with 410 Gone + Link header.
//
// Routes without x-deprecated-on are a pure no-op (zero overhead once the
// index is built empty).
//
// Successor URL derivation: strips the leading "/api/v1" or "/v1" segment and
// prepends "/v2". Template parameters (e.g. {id}) are left verbatim so the
// Link header remains a valid URI template per RFC 6570.
//
// Date parsing: both x-deprecated-on and x-sunset-on must be ISO-8601 date
// strings (YYYY-MM-DD). If x-sunset-on is absent, the sunset is calculated as
// deprecatedOn + windowDays (cfg.api_deprecation_window_days, default 90).

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"gopkg.in/yaml.v3"
)

// httpDateFormat is the RFC 7231 HTTP-date format required by RFC 8594 for
// the Sunset header. Example: "Thu, 01 Jan 2026 00:00:00 GMT"
const httpDateFormat = "Mon, 02 Jan 2006 15:04:05 GMT"

// deprecationEntry holds parsed sunset metadata for one route operation.
type deprecationEntry struct {
	sunsetAt     time.Time // absolute UTC midnight; on/after this -> 410
	successorURL string    // derived /v2/... path (OpenAPI template notation)
}

// DeprecationHeaders returns a Gin middleware that enforces RFC 8594 Sunset
// and RFC 5988 Link headers for deprecated routes. It is a pure no-op on
// routes not marked with x-deprecated-on in the spec.
//
// specYAML is the raw OpenAPI 3.x YAML (typically openapi.EmbeddedSpec).
// windowDays is cfg.APIDeprecationWindowDays (fallback when x-sunset-on is
// absent from a deprecated operation). Pass 90 when unsure.
func DeprecationHeaders(specYAML []byte, windowDays int) gin.HandlerFunc {
	index := buildDeprecationIndex(specYAML, windowDays)
	if len(index) == 0 {
		// No deprecated routes -- pure no-op closure.
		return func(c *gin.Context) { c.Next() }
	}
	return func(c *gin.Context) {
		entry, deprecated := index[c.FullPath()]
		if !deprecated {
			c.Next()
			return
		}
		linkHdr := fmt.Sprintf(`<%s>; rel="successor-version"`, entry.successorURL)
		if time.Now().UTC().Before(entry.sunsetAt) {
			// Before sunset: annotate and proceed.
			c.Header("Sunset", entry.sunsetAt.Format(httpDateFormat))
			c.Header("Link", linkHdr)
			c.Next()
			return
		}
		// On or past sunset: 410 Gone.
		c.Header("Link", linkHdr)
		c.AbortWithStatus(http.StatusGone)
	}
}

// getDateExt reads a YAML extension field that may have been decoded as a
// time.Time (gopkg.in/yaml.v3 parses unquoted ISO-8601 dates automatically)
// or as a plain string (when the value is quoted in YAML). Returns the
// YYYY-MM-DD string, or "" when the field is absent or of an unrecognised type.
func getDateExt(op map[string]any, key string) string {
	v, ok := op[key]
	if !ok {
		return ""
	}
	switch t := v.(type) {
	case string:
		return t
	case time.Time:
		return t.UTC().Format("2006-01-02")
	default:
		return ""
	}
}

// buildDeprecationIndex parses specYAML and returns a map from Gin route
// pattern (e.g. "/v1/matches/:id") to deprecationEntry. Routes without
// x-deprecated-on are excluded.
func buildDeprecationIndex(specYAML []byte, windowDays int) map[string]deprecationEntry {
	var doc map[string]any
	if err := yaml.Unmarshal(specYAML, &doc); err != nil {
		return nil
	}
	pathsAny, ok := doc["paths"]
	if !ok {
		return nil
	}
	paths, ok := pathsAny.(map[string]any)
	if !ok {
		return nil
	}

	httpMethodSet := map[string]bool{
		"get": true, "post": true, "put": true,
		"patch": true, "delete": true, "head": true, "options": true,
	}

	index := make(map[string]deprecationEntry)
	for routePattern, pathItemAny := range paths {
		pathItem, ok := pathItemAny.(map[string]any)
		if !ok {
			continue
		}
		for method, opAny := range pathItem {
			if !httpMethodSet[method] {
				continue
			}
			op, ok := opAny.(map[string]any)
			if !ok {
				continue
			}
			deprecatedOnStr := getDateExt(op, "x-deprecated-on")
			if deprecatedOnStr == "" {
				continue
			}
			deprecatedOn, err := time.Parse("2006-01-02", deprecatedOnStr)
			if err != nil {
				continue
			}
			var sunsetAt time.Time
			if sunsetOnStr := getDateExt(op, "x-sunset-on"); sunsetOnStr != "" {
				sunsetAt, err = time.Parse("2006-01-02", sunsetOnStr)
				if err != nil {
					sunsetAt = deprecatedOn.AddDate(0, 0, windowDays)
				}
			} else {
				sunsetAt = deprecatedOn.AddDate(0, 0, windowDays)
			}
			// Normalise to UTC midnight (start of the sunset day).
			sunsetAt = time.Date(sunsetAt.Year(), sunsetAt.Month(), sunsetAt.Day(),
				0, 0, 0, 0, time.UTC)

			// Convert OpenAPI path template ({param}) to Gin pattern (:param)
			// for map lookups against c.FullPath().
			ginPattern := openAPIPathToGin(routePattern)
			index[ginPattern] = deprecationEntry{
				sunsetAt:     sunsetAt,
				successorURL: deriveSuccessorURL(routePattern),
			}
		}
	}
	return index
}

// openAPIPathToGin converts an OpenAPI path template like /v1/matches/{id}
// to the Gin routing pattern /v1/matches/:id.
func openAPIPathToGin(p string) string {
	var b strings.Builder
	b.Grow(len(p))
	i := 0
	for i < len(p) {
		if p[i] == '{' {
			b.WriteByte(':')
			i++ // skip '{'
			for i < len(p) && p[i] != '}' {
				b.WriteByte(p[i])
				i++
			}
			if i < len(p) {
				i++ // skip '}'
			}
		} else {
			b.WriteByte(p[i])
			i++
		}
	}
	return b.String()
}

// deriveSuccessorURL produces the /v2/... successor URL from an OpenAPI path.
// Examples:
//
//	/api/v1/matches/{id}  ->  /v2/matches/{id}
//	/v1/matches/{id}      ->  /v2/matches/{id}
//	/other/path           ->  /v2/other/path  (fallback)
func deriveSuccessorURL(p string) string {
	if after, ok := strings.CutPrefix(p, "/api/v1"); ok {
		return "/v2" + after
	}
	if after, ok := strings.CutPrefix(p, "/v1"); ok {
		return "/v2" + after
	}
	return "/v2" + p
}
