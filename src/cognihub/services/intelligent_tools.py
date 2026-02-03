from __future__ import annotations

import httpx
import json
import re
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class QueryIntent:
    """Represents the parsed intent and characteristics of a user query."""
    
    def __init__(self, text: str):
        self.original = text.strip()
        self.normalized = self._normalize_query(text)
        self.requires_current_info = self._detect_time_sensitive_intent(text)
        self.intent_type = self._classify_intent_type(text)
        self.entities = self._extract_entities(text)
        
    def _normalize_query(self, text: str) -> str:
        """Clean and normalize the query for processing."""
        # Remove extra whitespace and normalize punctuation
        normalized = re.sub(r'\s+', ' ', text.lower().strip())
        # Expand common abbreviations
        abbreviations = {
            'tx': 'texas',
            'ca': 'california', 
            'ny': 'new york',
            'fl': 'florida',
        }
        words = normalized.split()
        for i, word in enumerate(words):
            if word in abbreviations:
                words[i] = abbreviations[word]
        return ' '.join(words)
    
    def _detect_time_sensitive_intent(self, text: str) -> bool:
        """Detect if query needs current/recent information."""
        time_sensitive_patterns = [
            r'\b(current|latest|now|today|right now|what\W+s\W+)',
            r'\b(weather|forecast|temperature|rain|snow|wind|sunny)',
            r'\b(news|breaking|happening|recent)',
            r'\b(this weekend|this week|this month)',
            r'\b(stock|price|market|crypto)',
        ]
        
        text_lower = text.lower()
        return any(re.search(pattern, text_lower) for pattern in time_sensitive_patterns)
    
    def _classify_intent_type(self, text: str) -> str:
        """Classify the type of intent."""
        text_lower = text.lower()
        
        if any(word in text_lower for word in ['weather', 'forecast', 'temperature', 'rain', 'snow', 'wind', 'sunny', 'cloudy']):
            return 'weather'
        elif any(word in text_lower for word in ['news', 'breaking', 'happening', 'recent', 'won', 'winner', 'champion', 'competition', 'contest', 'tournament', 'world']):
            return 'news'
        elif any(word in text_lower for word in ['time', 'date', 'now', 'current']):
            return 'time'
        elif any(word in text_lower for word in ['search', 'find', 'look for', 'what']):
            return 'search'
        else:
            return 'general'
    
    def _extract_entities(self, text: str) -> Dict[str, Any]:
        """Extract structured entities from the query."""
        entities = {}
        
        # Location extraction
        location_patterns = [
            r'(\w+\s+(?:tx|texas))\b',
            r'(\w+\s+(?:ca|california))\b', 
            r'(\w+\s+(?:ny|new york))\b',
            r'(\w+\s+(?:fl|florida))\b',
            r'(\w+,\s*\w+(?:\s+tx|texas)?)',
            r'(\w+(?:\s+tx|texas)?)',
        ]
        
        for pattern in location_patterns:
            match = re.search(pattern, text.lower())
            if match:
                entities['location'] = match.group(1).title()
                break
        
        # Date extraction
        date_patterns = [
            r'(\d{1,2}/\d{1,2}/\d{4})',
            r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s*\d{4}',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text.lower())
            if match:
                entities['date'] = match.group(1)
                break
        
        # Year extraction
        year_match = re.search(r'\b(20\d{2})\b', text)
        if year_match:
            entities['year'] = year_match.group(1)
        
        return entities


class ToolCallDecider:
    """Decides what tools should be called based on intent and context."""
    
    def __init__(self, max_cycles: int = 3):
        self.max_cycles = max_cycles
        self.current_cycle = 0
        
    def should_call_tools(self, intent: QueryIntent, context: List[Dict[str, Any]]) -> bool:
        """Determine if tools should be called for this query."""
        
        # Always use tools for time-sensitive queries
        if intent.requires_current_info:
            return True
            
        # Use tools if we don't have recent relevant information
        if self._has_recent_relevant_info(intent, context):
            return False
            
        # Default to using tools for better reliability
        return True
    
    def _has_recent_relevant_info(self, intent: QueryIntent, context: List[Dict[str, Any]]) -> bool:
        """Check if context contains recent relevant information."""
        # For news intents, we usually want fresh information
        if intent.intent_type == 'news':
            return False  # Always call tools for news queries to get fresh info
            
        # Look for recent tool results or relevant data
        for msg in reversed(context[-3:]):  # Check last 3 messages
            content = msg.get('content', '').lower()
            
            # If we recently searched for similar information
            if intent.intent_type == 'weather' and any(word in content for word in ['weather', 'temperature', 'forecast']):
                if intent.entities.get('location') and intent.entities['location'].lower() in content:
                    return True
            
            # If we recently got general information about the location
            if intent.entities.get('location') and intent.entities['location'].lower() in content:
                return True
                
        return False


class EvidenceSynthesizer:
    """Synthesizes and evaluates evidence from tool results."""
    
    def __init__(self):
        self.current_date = datetime.now(tz=ZoneInfo("America/Chicago")).strftime('%A, %B %d, %Y')
        
    def summarize_evidence(self, intent: QueryIntent, tool_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Summarize collected evidence into a coherent knowledge base."""
        
        evidence = {
            'query': intent.original,
            'intent_type': intent.intent_type,
            'current_date': self.current_date,
            'location': intent.entities.get('location'),
            'sources': [],
            'facts': [],
            'confidence': 'low'
        }
        
        # Process tool results by type
        for result in tool_results:
            if result.get('tool') == 'web_search':
                web_data = self._process_web_results(result.get('result', {}))
                evidence['sources'].extend(web_data['sources'])
                evidence['facts'].extend(web_data['facts'])
                
            elif result.get('tool') == 'doc_search':
                doc_data = self._process_doc_results(result.get('result', {}))
                evidence['sources'].extend(doc_data['sources'])
                evidence['facts'].extend(doc_data['facts'])
        
        # Assess confidence
        if evidence['sources']:
            evidence['confidence'] = 'high' if len(evidence['sources']) >= 3 else 'medium'
        
        return evidence
    
    def _process_web_results(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Process web search results into structured evidence."""
        
        processed: Dict[str, Any] = {'sources': [], 'facts': []}
        
        for item in result.get('items', []):
            source = {
                'type': 'web',
                'url': item.get('url', ''),
                'title': item.get('title', ''),
                'snippet': item.get('snippet', ''),
                'domain': self._extract_domain(item.get('url', ''))
            }
            processed['sources'].append(source)
            
            # Extract factual information
            text = f"{item.get('title', '')} {item.get('snippet', '')}"
            facts = self._extract_weather_facts(text)
            processed['facts'].extend(facts)
            
        return processed
    
    def _process_doc_results(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Process document search results into structured evidence."""
        
        processed: Dict[str, Any] = {'sources': [], 'facts': []}
        
        for chunk in result.get('chunks', []):
            source = {
                'type': 'document',
                'title': chunk.get('source', ''),
                'url': chunk.get('url', ''),
                'snippet': chunk.get('text', '')[:200],
                'score': chunk.get('score', 0.0)
            }
            processed['sources'].append(source)
            
            # Extract facts from document text
            facts = self._extract_weather_facts(chunk.get('text', ''))
            processed['facts'].extend(facts)
            
        return processed
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        if not url:
            return ''
        try:
            return url.split('/')[2] if '://' in url else url.split('/')[0]
        except:
            return url
    
    def _extract_weather_facts(self, text: str) -> List[str]:
        """Extract weather-related facts from text."""
        facts = []
        
        # Temperature patterns
        temp_patterns = [
            r'(\d+)[-°°f]\b',
            r'high of (\d+)°?f',
            r'low of (\d+)°?f',
        ]
        
        for pattern in temp_patterns:
            match = re.search(pattern, text.lower())
            if match:
                facts.append(f"Temperature: {match.group(1)}°F")
        
        # Condition patterns
        cond_patterns = [
            r'\b(sunny|cloudy|rainy|snowy|windy|clear|foggy|partly cloudy)\b',
            r'\b(high|low)\s+of\s+(\d+)°?f',
        ]
        
        for pattern in cond_patterns:
            match = re.search(pattern, text.lower())
            if match:
                if 'high' in match.group(1) or 'low' in match.group(1):
                    facts.append(f"Temperature: {match.group(2)}°F ({match.group(1)})")
                else:
                    facts.append(f"Conditions: {match.group(1).title()}")
        
        return facts
    
    def is_sufficient_for_answer(self, evidence: Dict[str, Any], intent: QueryIntent) -> bool:
        """Determine if we have enough evidence to answer the query."""
        
        # Must have at least some reliable sources
        if not evidence['sources']:
            return False
            
        # For weather queries, need current conditions
        if intent.intent_type == 'weather':
            has_temp = any('Temperature:' in fact for fact in evidence['facts'])
            has_conditions = any('Conditions:' in fact for fact in evidence['facts'])
            return has_temp or has_conditions
            
        # For news queries, need recent information
        if intent.intent_type == 'news':
            return len(evidence['sources']) >= 2
            
        # General queries - any factual info helps
        return len(evidence['facts']) > 0
    
    def format_final_answer(self, evidence: Dict[str, Any]) -> str:
        """Format the final answer with proper date and citations."""
        
        if not evidence['sources']:
            return (f"I don't have enough current information about "
                   f"{evidence['query']} from {evidence['current_date']}. "
                   f"You can search for more recent information online.")
        
        answer = []
        
        # Start with current date
        answer.append(f"Based on information from {evidence['current_date']}:")
        
        # Add key facts
        if evidence['facts']:
            answer.append("\nKey findings:")
            for fact in evidence['facts'][:5]:  # Limit to top 5 facts
                answer.append(f"• {fact}")
        
        # Add source citations
        if evidence['sources']:
            answer.append(f"\nSources:")
            for i, source in enumerate(evidence['sources'][:3]):  # Limit to top 3 sources
                answer.append(f"{i+1}. {source['title']}")
                if source.get('url'):
                    answer.append(f"   {source['url']}")
        
        return '\n'.join(answer)


class IntelligentToolLoop:
    """Main orchestrator for intelligent tool-calling workflow."""
    
    def __init__(self, max_cycles: int = 3):
        self.decider = ToolCallDecider(max_cycles)
        self.synthesizer = EvidenceSynthesizer()
        
    async def execute(
        self,
        *,
        http,
        ollama_url: str,
        model: str,
        messages: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None,
        keep_alive: Optional[str] = None,
        embed_model: str,
        tool_registry,
        tool_executor,
        kiwix_url: Optional[str] = None,
    ) -> str:
        """Execute the intelligent tool-calling loop."""
        
        # Stage 1: Decipher query
        user_message = next((m for m in reversed(messages) if m.get('role') == 'user'), {})
        user_text = user_message.get('content', '')
        intent = QueryIntent(user_text)
        
        logger.info(f"Query intent: {intent.intent_type}, requires_current_info: {intent.requires_current_info}")
        logger.info(f"Entities: {intent.entities}")
        
        # Stage 2: Build context
        system_prompt = self._build_context_prompt(intent, messages)
        working_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        
        # Stage 3: Tool-calling loop with native Ollama tool calling
        cycle_count = 0
        tool_results = []
        
        # Define tools for Ollama (use real schema format)
        tools = tool_registry.list_for_prompt()
        
        while cycle_count < self.decider.max_cycles:
            cycle_count += 1
            
            # Get LLM response with tools
            payload = {
                "model": model,
                "messages": working_messages,
                "stream": False,
                "tools": tools,
            }
            if options is not None:
                payload["options"] = options
            if keep_alive is not None:
                payload["keep_alive"] = keep_alive
            
            response = await http.post(f"{ollama_url}/api/chat", json=payload, timeout=30)
            response.raise_for_status()
            msg = response.json()["message"]
            content = msg.get("content", "").strip()
            
            # Extract and execute tool calls
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                tool_results.extend(await self._execute_tools(tool_calls, tool_executor, http, embed_model, kiwix_url))
                
                # Add tool result message and continue loop
                working_messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                })
            else:
                # No tool calls - check if we have answer
                if content.strip():
                    return content
            
            # Prepare for next cycle if needed
            if cycle_count < self.decider.max_cycles:
                insufficient_prompt = f"Still need more information. Current knowledge from {cycle_count} cycles is insufficient."
                working_messages.append({"role": "system", "content": insufficient_prompt})
        
        # Max cycles reached - give best effort answer
        final_evidence = self.synthesizer.summarize_evidence(intent, tool_results)
        return self.synthesizer.format_final_answer(final_evidence)
    
    def _build_context_prompt(self, intent: QueryIntent, messages: List[Dict[str, Any]]) -> str:
        """Build system prompt with current date and context."""
        current_date = datetime.now().strftime('%A, %B %d, %Y')  # e.g., "Friday, January 24, 2026"
        
        context_parts = [
            f"Current date: {current_date}",
            f"User query intent: {intent.intent_type}",
        ]
        
        if intent.entities:
            for key, value in intent.entities.items():
                context_parts.append(f"Detected {key}: {value}")
        
        return "Context: " + "; ".join(context_parts)
    
    async def _call_llm(self, *, http, ollama_url, model, messages, options, keep_alive):
        """Make LLM call."""
        from ..config import config
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options
        if keep_alive:
            payload["keep_alive"] = keep_alive
            
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(f"{ollama_url}/api/chat", json=payload, timeout=30)
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "")
    
    def _extract_tool_calls(self, llm_response: str) -> List[Dict[str, Any]]:
        """Extract tool calls from LLM response."""
        try:
            data = json.loads(llm_response)
            return data.get("tool_calls", [])
        except json.JSONDecodeError:
            return []
    
    async def _execute_tools(self, tool_calls, tool_executor, http, embed_model, kiwix_url):
        """Execute list of tool calls."""
        import asyncio
        from ..services.web_ingest import WebIngestQueue
        
        results = []
        for call in tool_calls:
            tool_name = call.get("name", "")
            args = call.get("arguments", {})
            
            try:
                result = await tool_executor.execute(
                    tool_name=tool_name,
                    args_json=args,
                    http=http,
                    ingest_queue=None,
                    embed_model=embed_model,
                    kiwix_url=kiwix_url,
                )
                results.append({
                    "tool": tool_name,
                    "result": result,
                    "ok": True
                })
            except Exception as e:
                results.append({
                    "tool": tool_name,
                    "result": {"error": str(e)},
                    "ok": False
                })
        
        return results
    
    def _format_tool_result(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        """Format tool result for inclusion in chat context."""
        return {
            "role": "tool",
            "content": json.dumps(tool_result.get("result", {}), ensure_ascii=False),
            "tool_call_id": tool_result.get("call_id", ""),
            "name": tool_result.get("tool", ""),
        }
