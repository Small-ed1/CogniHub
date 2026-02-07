# tests/test_agent_loop.py
from contextharbor.agents.ollama_tool_agent import ToolCallingAgent, AgentConfig, build_registry, OllamaClient

class FakeClient(OllamaClient):
    def __init__(self):
        super().__init__("http://fake")
        self.n = 0

    def chat(self, model, messages, tools=None, stream=False, options=None, think=False):
        self.n += 1
        # first response: ask for doc_search
        if self.n == 1:
            return {"message": {"role": "assistant", "content": "", "tool_calls": [
                {"type":"function","function":{"name":"doc_search","arguments":{"query":"hello","root":"./docs","top_k":5}}}
            ]}}
        # second response: final
        return {"message": {"role": "assistant", "content": "done", "tool_calls": []}}

def test_basic_loop():
    cfg = AgentConfig()
    agent = ToolCallingAgent(cfg, build_registry())
    agent.client = FakeClient()  # inject fake LLM

    out = agent.run("search docs for hello")
    assert "done" in out
