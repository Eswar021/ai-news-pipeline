import os
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()


def make_llm(
    provider: str = "openai",
    model: str | None = None,
    temperature: float = 0.15,
    base_url: str | None = None,
):
    provider = provider.lower().strip()

    if provider == "openai":
        return ChatOpenAI(
            model=model or os.getenv("OPENAI_MODEL", "gpt-5-nano"),
            api_key=os.getenv("OPENAI_API_KEY_S_M_R"),  # type: ignore
            temperature=temperature,
        )

    if provider == "lmstudio":
        return ChatOpenAI(
            model=model or os.getenv("LMSTUDIO_MODEL", "qwen/qwen2.5-coder-14b"),
            api_key=os.getenv("LMSTUDIO_API_KEY", "lm-studio"),  # type: ignore
            base_url=base_url or os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
            temperature=temperature,
        )

    if provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            api_key=os.getenv("GOOGLE_API_KEY"),  # type: ignore
            temperature=temperature,
        )

    raise ValueError(f"Unknown provider: {provider}. Use 'openai', 'lmstudio', or 'gemini'.")


if __name__ == "__main__":
    llm = make_llm()
    
    print(f"LLM Provider: {llm.__class__.__name__}")
    print(f"Model: {getattr(llm, 'model_name', 'N/A')}")
    # print(llm.model_name) # type: ignore
    print(llm.invoke("Say hi in one word").content)
