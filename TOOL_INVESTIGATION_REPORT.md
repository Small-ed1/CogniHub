# ContextHarbor Tool-Calling Issues Investigation Report

## Executive Summary

**Root Cause Identified**: DuckDuckGo web search is completely broken due to anti-bot protection, returning HTTP 302 redirects instead of search results. This causes the LLM to respond with "I don't have enough information" because the primary information retrieval tool returns empty results.

## Detailed Analysis

### 1. **System Architecture Overview**

The ContextHarbor tool-calling system is well-architected with:
- ✅ **Strict JSON schema validation** (Pydantic models)
- ✅ **Comprehensive error handling** and timeout protection  
- ✅ **Detailed logging** with SHA256 hashing
- ✅ **Security controls** (allowlisting, confirmation gating)
- ✅ **Performance optimization** (output truncation, async I/O)

**Available Tools:**
1. `web_search` - DuckDuckGo web search (NETWORK side-effect)
2. `doc_search` - RAG document search (READ_ONLY)  
3. `shell_exec` - Safe shell commands (DANGEROUS, opt-in)

### 2. **Critical Failure: Web Search Broken**

**Issue**: `web_search` tool consistently returns `{"items": []}`

**Root Cause**: DuckDuckGo blocks automated requests with HTTP 302 redirects

**Evidence**:
```bash
# Current implementation returns:
curl -X POST "https://duckduckgo.com/html/" -d "q=test"
# Response: 302 Found (redirects to captcha/bot detection)

# Tool logs show:
web_search|1|425|{"items": []}  # Success but empty results
```

**Impact**: This is the **primary cause** of "I don't have enough information" responses because:
- LLM cannot access current web information
- Weather, news, and current events queries fail
- Research capabilities are severely limited

### 3. **Other Tool Status**

**`doc_search`**: ✅ Working correctly (RAG system)
- Requires uploaded documents to function
- Returns meaningful chunks from indexed content
- Limited by document availability

**`shell_exec`**: ✅ Working but disabled by default
- Requires `ALLOW_SHELL_EXEC=1` environment variable
- Safe allowlist prevents dangerous commands
- Not relevant to information retrieval failures

### 4. **Silent Failure Analysis**

**Why This Causes Silent LLM Failures:**

1. **Tool succeeds but returns empty** - No error logged
2. **LLM receives empty context** - Cannot provide informed response
3. **User sees generic response** - "I don't know" instead of specific error
4. **Debugging difficulty** - Tool execution appears successful

**Pattern Recognition**:
```
User asks: "What's the weather like?"
→ web_search tool called → returns {"items": []} 
→ LLM receives no web context
→ LLM responds: "I don't have enough information"
```

## Immediate Solutions

### **Solution 1: Fix DuckDuckGo Integration** (Recommended)

**Option A: Better User-Agent & Headers**
```python
# In packages/contextharbor/src/contextharbor/services/web_search.py
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://duckduckgo.com",
    "Referer": "https://duckduckgo.com/",
}
```

**Option B: Use DuckDuckGo Lite**
```python
# Alternative endpoint that's less likely to block
url = "https://lite.duckduckgo.com/lite/"
# Use GET request instead of POST
r = await http.get(url, params={"q": q}, headers=headers)
```

**Option C: Add Rate Limiting**
```python
# Add delay between requests
import time
await asyncio.sleep(2)  # 2-second delay
```

### **Solution 2: Alternative Search Provider** (Backup)

**Option A: Google Custom Search API**
```python
# Requires API key but more reliable
url = "https://www.googleapis.com/customsearch/v1"
params = {
    "key": os.getenv("GOOGLE_SEARCH_API_KEY"),
    "cx": os.getenv("GOOGLE_SEARCH_CX"), 
    "q": q
}
```

**Option B: Bing Search API**
```python
# Microsoft's search API
url = "https://api.bing.microsoft.com/v7.0/search"
headers = {"Ocp-Apim-Subscription-Key": os.getenv("BING_SEARCH_KEY")}
```

**Option C: Multiple Provider Fallback**
```python
providers = ["duckduckgo", "brave", "startpage"]
for provider in providers:
    try:
        results = await search_with_provider(provider, query)
        if results:
            return results
    except Exception:
        continue
return []
```

### **Solution 3: Better Error Handling** (Immediate)

**Detect Empty Results:**
```python
# In builtin.py web_search_handler
items = []
for p in result.get("pages", []):
    items.append({...})

# ADD THIS CHECK:
if not items:
    return {
        "items": [],
        "error": "Web search returned no results - possibly blocked or connectivity issue"
    }
```

**Improve Logging:**
```python
# Add more verbose logging for debugging
if len(r.text) < 1000:  # Suspiciously small response
    logger.warning(f"DuckDuckGo returned small response: {len(r.text)} chars")
    logger.debug(f"Response preview: {r.text[:500]}")
```

## Implementation Priority

### **High Priority (Immediate Fix)**
1. **Add empty result detection** in `web_search_handler`
2. **Improve error messages** to inform user of search failures
3. **Add rate limiting** to avoid further blocking
4. **Update User-Agent** to more realistic browser

### **Medium Priority (Next Release)**
1. **Implement alternative search providers** 
2. **Add search provider fallback system**
3. **Create search health monitoring**
4. **Add search result caching**

### **Low Priority (Future Enhancement)**
1. **API-based search integration** (Google/Bing)
2. **Search quality scoring**
3. **Advanced search filtering**
4. **Search analytics dashboard**

## Testing & Validation

### **Current State Tests**
```bash
# Test web search directly
 python -c "
 import asyncio
 from contextharbor.services.web_search import ddg_search
 import httpx

async def test():
    async with httpx.AsyncClient() as http:
        result = await ddg_search(http, 'test query', 5)
        print(f'Results: {len(result)}')

asyncio.run(test())
"
# Expected: 0 results (broken)
```

### **Post-Fix Validation**
```bash
# Same test should return 5+ results
# Tool logs should show: web_search|1|<duration>|{"items": [{"title": "...", ...}]}
```

### **Integration Testing**
```bash
# Test LLM with questions requiring web access
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "What is the current weather in London?"}]}'

# Should provide weather information instead of "I don't know"
```

## Monitoring & Maintenance

### **Search Health Check**
```python
# Add periodic health check
async def check_search_health():
    async with httpx.AsyncClient() as http:
        test_results = await ddg_search(http, "test", 1)
        return len(test_results) > 0

# Log health status daily
```

### **Tool Execution Monitoring**
```sql
-- Monitor tool success rates
SELECT 
    tool_name,
    COUNT(*) as total,
    SUM(ok) as successful,
    AVG(duration_ms) as avg_duration
FROM tool_runs 
WHERE ts > datetime('now', '-24 hours')
GROUP BY tool_name;
```

## Conclusion

The ContextHarbor tool-calling system is **well-designed and robust**, but the **web search component is completely broken** due to DuckDuckGo's anti-bot protection. This is the **primary cause** of user reports about the LLM not having enough information.

**Fixing web search should be the #1 priority** as it will immediately restore:
- Current event awareness
- Weather information  
- News and real-time data
- Research capabilities
- General knowledge beyond training data

The solutions range from **quick fixes** (better headers, error detection) to **comprehensive overhauls** (multiple providers, API integration). Implementing even the basic fixes should dramatically improve user experience.
