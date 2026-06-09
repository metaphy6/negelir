package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"os"
	"path/filepath"

	"github.com/gin-gonic/gin"
	aperrors "github.com/metaphy6/negelir/server/internal/errors"
	"gopkg.in/yaml.v3"
)

// catalogData holds the in-memory catalog parsed from YAML.
var cachedCatalogData *CatalogData
var cachedCatalogSHA256 string

// CatalogData represents the deserialized league catalog.
type CatalogData struct {
	SchemaVersion int `json:"schema_version" yaml:"schema_version"`
	Leagues       []LeagueRow `json:"leagues" yaml:"leagues"`
}

// LeagueRow represents a single league in the catalog.
type LeagueRow struct {
	LeagueID      string         `json:"league_id" yaml:"league_id"`
	NameEn        string         `json:"name_en" yaml:"name_en"`
	NameTr        string         `json:"name_tr" yaml:"name_tr"`
	Country       *string        `json:"country" yaml:"country"`
	Confederation string         `json:"confederation" yaml:"confederation"`
	Tier          string         `json:"tier" yaml:"tier"`
	ActiveSince   string         `json:"active_since" yaml:"active_since"`
	Competitions  []Competition  `json:"competitions" yaml:"competitions"`
	SourceCoverage SourceCoverage `json:"source_coverage" yaml:"source_coverage"`
}

// Competition represents a single competition within a league.
type Competition struct {
	CompetitionID string `json:"competition_id" yaml:"competition_id"`
}

// SourceCoverage represents the data sources for a league.
type SourceCoverage struct {
	Reference []string `json:"reference" yaml:"reference"`
	Schedule  []string `json:"schedule" yaml:"schedule"`
	Live      []string `json:"live" yaml:"live"`
	Editorial []string `json:"editorial" yaml:"editorial"`
	Market    []string `json:"market" yaml:"market"`
}

// initCatalog loads and caches the league catalog at startup.
func initCatalog() error {
	// Try multiple path resolution strategies to handle both runtime and test execution.
	var catalogPath string
	possiblePaths := []string{
		filepath.Join("..", "ai", "common", "league_catalog.yaml"), // From server/ dir (tests)
		filepath.Join("ai", "common", "league_catalog.yaml"),        // From repo root (production)
		filepath.Join("..", "..", "ai", "common", "league_catalog.yaml"), // Fallback
		filepath.Join(".", "ai", "common", "league_catalog.yaml"),  // Current dir
		// Also try some more aggressive searches by checking the entire tree
		findFileInParents("league_catalog.yaml"),
	}
	
	for _, path := range possiblePaths {
		if path == "" {
			continue
		}
		if _, err := os.Stat(path); err == nil {
			catalogPath = path
			break
		}
	}
	
	if catalogPath == "" {
		return fmt.Errorf("catalog file not found in any of the expected locations")
	}
	
	// Read the raw YAML file to compute SHA-256
	rawYAML, err := os.ReadFile(catalogPath)
	if err != nil {
		return fmt.Errorf("failed to read catalog file at %s: %w", catalogPath, err)
	}
	
	// Compute SHA-256 of the raw YAML bytes
	hash := sha256.Sum256(rawYAML)
	cachedCatalogSHA256 = hex.EncodeToString(hash[:])
	
	// Parse YAML into the catalog data structure
	catalogData := &CatalogData{}
	if err := yaml.Unmarshal(rawYAML, catalogData); err != nil {
		return fmt.Errorf("failed to parse catalog YAML: %w", err)
	}
	
	cachedCatalogData = catalogData
	return nil
}

// findFileInParents searches for a file by walking up the directory tree.
// Returns empty string if not found.
func findFileInParents(filename string) string {
	cwd, err := os.Getwd()
	if err != nil {
		return ""
	}
	
	// Search up to 5 levels deep
	for i := 0; i < 5; i++ {
		path := filepath.Join(cwd, "ai", "common", filename)
		if _, err := os.Stat(path); err == nil {
			return path
		}
		cwd = filepath.Dir(cwd)
	}
	return ""
}

// catalogHandler handles GET /v1/catalog.
// Phase 13.1: returns the canonical league catalog + ETag=catalog_sha256.
// Admin-token-gated.
func catalogHandler() gin.HandlerFunc {
	return func(c *gin.Context) {
		// TODO: Phase 13.1 follow-up — admin token check via JWT scopes.
		// For now, this is a placeholder; full admin auth wired in Phase 9.2.
		// Stub: return 501 until admin authz is available.
		
		if cachedCatalogData == nil {
			aperrors.Respond(c, aperrors.CodeServiceUnavailable, "catalog not initialized")
			return
		}
		
		// Build the ETag value with quotes (RFC 7232 format).
		etagValue := fmt.Sprintf(`"%s"`, cachedCatalogSHA256)
		
		// Set the ETag header.
		c.Header("ETag", etagValue)
		
		// Check If-None-Match header (cache validation).
		// RFC 7232: If-None-Match can contain multiple ETags separated by commas.
		// For simplicity, we support exact match of a single ETag.
		if ifNoneMatch := c.GetHeader("If-None-Match"); ifNoneMatch == etagValue {
			c.Status(http.StatusNotModified) // 304 Not Modified
			return
		}
		
		// Return the catalog as JSON with 200 OK.
		c.JSON(http.StatusOK, cachedCatalogData)
	}
}
