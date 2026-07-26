"""Framework adapters. Each is optional and imports its framework lazily, so the core
stays dependency-free — `import agent_seal` must never require LangChain to be installed.
"""
