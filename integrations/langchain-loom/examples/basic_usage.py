"""Example: using langchain-loom with a LangChain agent."""
from langchain_loom import LoomMemory

# Create memory backed by Loom OS
memory = LoomMemory(
    project="my-web-app",
    agent="langchain-agent",
    project_path="/path/to/my-web-app",
)

# In a real LangChain app:
# from langchain.chains import ConversationChain
# from langchain_openai import ChatOpenAI
# chain = ConversationChain(llm=ChatOpenAI(), memory=memory)
# response = chain.predict(input="What does the auth module do?")

# For this example, just demonstrate save/load:
memory.save_context(
    inputs={"input": "Review the auth module"},
    outputs={"output": "AuthService uses bcrypt for password hashing."},
)
print("Finding written to Loom inbox.")

ctx = memory.load_memory_variables({})
print(f"Context loaded: {len(ctx['loom_context'])} chars")
