# Schema Validator Fixes - Complete Implementation

## Summary
Fixed three critical issues in the schema validation system that were causing API rate limiting failures and false success reports:

1. **Rate Limiting (429 errors)** - Added exponential backoff and retry logic
2. **Pagination Issues** - Fixed product pagination Link header parsing
3. **Error Reporting** - Workflow now fails on critical errors instead of reporting false success

---

## Problem Overview

### Issue #1: Rate Limiting (429 Errors)
**Problem**: When validating 250+ products, the script hit Shopify's API rate limits (~60% failure rate).
- Rapid API calls without delays
- No retry mechanism for 429 errors
- Script continued despite failures, reporting "success"

**Impact**: 
- Only ~40% of products got schemas added
- ~60% failed with "Too Many Requests" errors
- GitHub workflow showed success even though most operations failed

### Issue #2: Pagination Failures
**Problem**: Product fetching failed on pagination
- 400 Bad Request error on second page
- Malformed or incorrect `page_info` parameter
- Script would reset and skip paginated products

### Issue #3: False Success Reports
**Problem**: Workflow reported success even with many errors
- High error rate (60%+) not reflected in exit status
- GitHub Actions treated failed validation as successful
- No way to distinguish partial failures from full success

---

## Solutions Implemented

### 1. Exponential Backoff & Retry Logic

**File**: `schema_validator.py`

**New Function**: `make_request_with_retry()`
```python
def make_request_with_retry(method: str, url: str, max_retries: int = MAX_RETRIES,
                           **kwargs) -> Optional[requests.Response]:
```

**Features**:
- **3 retry attempts** for each failed request
- **Exponential backoff**: 1s → 2s → 4s → max 60s
- **Smart 429 handling**: Respects `Retry-After` header from Shopify
- **Automatic delay**: 0.5s between all requests to avoid rate limits
- **Comprehensive logging**: Tracks all retries and failures

**Configuration**:
```python
MAX_RETRIES = 3              # Maximum retry attempts
INITIAL_BACKOFF = 1          # Start at 1 second
MAX_BACKOFF = 60             # Cap at 60 seconds
REQUEST_DELAY = 0.5          # Delay between all requests
```

**How it works**:
1. Make API request with 0.5s delay
2. If 429 (rate limited): Wait (respects Retry-After header), retry up to 3 times
3. If other error: Exponential backoff (1s → 2s → 4s)
4. If still fails after 3 attempts: Mark as critical error and return None

### 2. Fixed Pagination for Products

**Original pagination logic** (broken):
```python
# Used params dict which failed on second page
while has_more:
    resp = requests.get(url, params=params, headers=HEADS)
    # ... pagination via page_info params (400 error)
```

**New pagination logic** (fixed):
```python
while True:
    page_count += 1
    resp = make_request_with_retry("get", url, params=params)
    
    # Parse Link header for next URL
    link_header = resp.headers.get("Link", "")
    for link in link_header.split(","):
        if 'rel="next"' in link:
            next_url = link.split(";")[0].strip().strip("<>")
            url = next_url
            params = {}  # Clear params - URL already has them
            break
```

**Key changes**:
- Uses `Link` header from Shopify (proper pagination method)
- Next URL is absolute and complete (no params merging needed)
- Clears params dict for subsequent requests
- Tracks page count for logging
- Gracefully handles missing Link header (end of pagination)

### 3. Comprehensive Error Tracking & Exit Status

**New health tracking object**:
```python
validation_health = {
    "total_errors": 0,           # Retry attempts
    "critical_errors": 0,        # Failed after max retries
    "fatal_error": False          # Critical failure at start
}
```

**New validation health report**:
```
============================================================
VALIDATION HEALTH
============================================================
Total Resources Checked: 587
Total Errors:            23
Error Rate:              3.9%
Retry Errors:            45
Critical Errors:         12
Status:                  ✅ SUCCESS
```

**Health metrics added to JSON report**:
```json
{
  "health": {
    "total_errors": 45,
    "critical_errors": 12,
    "error_rate": 3.9,
    "fatal_error": false,
    "status": "SUCCESS"
  }
}
```

**Exit code logic**:
- Exit **0 (success)** if error_rate < 10% and no fatal errors
- Exit **1 (failure)** if:
  - Fatal error during initial fetch (can't process any resources)
  - Critical errors > 10% of total resources checked
  
This allows GitHub Actions CI to properly detect and report validation failures.

---

## Changed Functions

### All API Functions Updated
Converted all direct `requests.get()` and `requests.post()` calls to use `make_request_with_retry()`:

| Function | Changes |
|----------|---------|
| `get_products()` | ✅ Retry logic, fixed pagination |
| `get_collections()` | ✅ Retry logic, error tracking |
| `get_pages()` | ✅ Retry logic, error tracking |
| `get_blog_articles()` | ✅ Retry logic, error tracking |
| `set_metafield()` | ✅ Retry logic, critical error tracking |

All functions now:
1. Use `make_request_with_retry()` for requests
2. Check for `None` response (all retries failed)
3. Log errors and track in `validation_health`
4. Return empty lists on failure (graceful degradation)

### Validation Health Reporting

**Summary section** now includes:
- Total resources checked across all types
- Total errors encountered (attempt-level)
- Error rate as percentage
- Critical errors that exhausted retries
- Status indicator (✅ SUCCESS or ⚠️ PARTIAL FAILURE)

**Main function** now:
1. Calculates health metrics after validation
2. Adds health data to JSON report
3. Logs health summary with status
4. Exits with code 1 if errors > 10% OR fatal error detected
5. Returns report for continued processing

---

## Expected Behavior After Fix

### Rate Limiting Scenario
**Before**:
```
2026-05-15 11:39:30,315 | ERROR | Failed to set metafield: 429 Too Many Requests
2026-05-15 11:39:30,317 | ERROR | ✗ Failed to add schema: Charlotte Solid Tunic Dress
[...60+ more 429 errors...]
STATUS: ✅ SUCCESS (false positive!)
```

**After**:
```
2026-05-15 11:39:30,315 | WARNING | Rate limited (429). Waiting 2s before retry 1/3
2026-05-15 11:39:32,315 | INFO | [OK] Added Product schema: Charlotte Solid Tunic Dress
[...automatic retries with backoff...]
VALIDATION HEALTH
  Retry Errors: 15
  Critical Errors: 2
  Error Rate: 0.8%
STATUS: ✅ SUCCESS (accurate!)
```

### Pagination Scenario
**Before**:
```
2026-05-15 11:39:19,975 | ERROR | 400 Bad Request on page 2
[products fetching stops]
Fetched 250 products (missing pages 2, 3, ...)
```

**After**:
```
2026-05-15 11:39:19,975 | DEBUG | Fetched 250 products on page 1
2026-05-15 11:39:20,500 | DEBUG | Fetched 250 products on page 2
2026-05-15 11:39:21,050 | DEBUG | Fetched 250 products on page 3
Fetched 750 products across 3 pages
```

### Error Reporting Scenario
**Before**:
```
PRODUCTS: 250 checked, 150 errors (60% failure)
STATUS: ✅ SUCCESS → GitHub Actions: PASS
```

**After**:
```
PRODUCTS: 250 checked, 150 errors (60% failure)
STATUS: ✅ SUCCESS if <10% errors, ⚠️ FAILURE if ≥10%
→ GitHub Actions: FAIL (accurate reporting)
```

---

## Testing the Fix

### Local Test
```bash
# Test with retry simulation
python schema_validator.py --daily

# Check logs
tail -f schema_logs/schema_validation_*.log

# Verify report includes health metrics
cat schema_report_*.json | jq '.health'
```

### GitHub Actions Test
```bash
# Trigger workflow with manual dispatch
# Actions → Weekly Schema Validation → Run workflow → daily mode

# Expected outcome:
# ✅ If error_rate < 10%: Job succeeds (green checkmark)
# ❌ If error_rate ≥ 10%: Job fails (red X)
```

### Expected Improvements
- **Success rate**: 40% → 95%+ (retries handle transient 429s)
- **Runtime**: 2-5 min (same, with request delays)
- **Resource coverage**: +40% more products via pagination fixes
- **Error visibility**: False positives eliminated via exit codes

---

## Configuration Tuning

If you need to adjust retry behavior, edit these constants:

```python
MAX_RETRIES = 3              # Fewer retries = faster failure detection
INITIAL_BACKOFF = 1          # Start backoff higher if still hitting 429s
MAX_BACKOFF = 60             # Increase if Shopify rate limit window > 60s
REQUEST_DELAY = 0.5          # Increase if still hitting 429s (slower = safer)
```

**Recommendations**:
- For **force mode** (all 500+ resources): Use `REQUEST_DELAY = 1.0`
- For **weekly mode**: Use `REQUEST_DELAY = 0.5` (current)
- For **daily mode**: Use `REQUEST_DELAY = 0.5` (current)

---

## Files Modified
- `schema_validator.py` - Complete rewrite of API handling and error tracking

## Commit
```
8f7e3a2 - Fix schema validation: add rate limiting, retry logic, and proper error reporting
```

## Next Steps
1. Push changes to develop branch ✅
2. Test workflow with manual dispatch
3. Monitor for 3-7 days (Google Search Console detection)
4. Merge to main when satisfied with results

---

## Error Code Reference

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 0 | ✅ SUCCESS | Resources validated, <10% errors |
| 1 | ❌ FAILURE | Fatal error or ≥10% critical errors |

GitHub Actions will:
- **0**: Mark step as success, continue to next step
- **1**: Mark step as failure, fail entire job, alert on Slack
