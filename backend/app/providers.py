from abc import ABC, abstractmethod
import logging, json
import hashlib, math, re, time
import httpx

MANUAL="Manual Review Required"
logger=logging.getLogger("questionnaire.embeddings");logger.setLevel(logging.INFO)
GROUNDING="Answer only using the retrieved context. Never invent facts. If evidence is insufficient, respond exactly 'Manual Review Required'. Return only a professional, concise, customer-ready answer written in plain prose sentences. Never use markdown or formatting syntax: no asterisks, bold markers, headers, bullet characters, pipes, or tables. Never mention internal documents, source names, chunk IDs, citations, retrieval, or the supplied context."

class BaseLLMProvider(ABC):
    @abstractmethod
    def generate_answer(self,question:str,context:list[dict],instructions:str="")->str: ...
    @abstractmethod
    def summarize(self,text:str)->str: ...
    @abstractmethod
    def extract_questions(self,text:str)->list[str]: ...
    @abstractmethod
    def classify_question(self,text:str)->str: ...
    @abstractmethod
    def chat(self,messages:list[dict],stream:bool=False): ...

class MockLLMProvider(BaseLLMProvider):
    def generate_answer(self,question,context,instructions=""):
        if not context:return MANUAL
        parts=[]
        for item in context:
            value=item["content"].strip().replace("\n"," ")
            if value and value not in parts:parts.append(value)
        merged=" ".join(parts)
        return merged[:700] if merged else MANUAL
    def summarize(self,text):return text[:500]
    def extract_questions(self,text):
        lines=[x.strip() for x in text.splitlines()]
        counts={}
        for x in lines:
            if x:counts[x]=counts.get(x,0)+1
        page_line=re.compile(r"^page \d+(?: of \d+)?$",re.I)
        question_shaped=lambda x:len(x)>5 and (x.endswith("?") or bool(re.match(r"^(describe|explain|provide|list|detail|confirm|state|outline|specify|do |does |is |are |what |how |where |when |who |can |which )",x,re.I)))
        found=[];current=None  # current=(text, explicitly Q-numbered)
        for line in lines:
            # Page headers/footers repeat verbatim across pages; wrapped continuations start lowercase and stay exempt.
            if not line or page_line.match(line) or (counts[line]>=2 and not line[:1].islower()):continue
            explicit=re.match(r"^q\s?\d{1,4}[.):]\s*(\S.*)",line,re.I);plain=re.match(r"^(?:\d{1,4}[.)]|[-*])\s*(\S.*)",line);marker=explicit or plain
            if marker:
                if current:found.append(current)
                current=(marker.group(1).strip(),bool(explicit))
            elif current and (current[0][-1:] not in ".?!" or line[:1].islower()):
                current=(f"{current[0]} {line}",current[1])  # rejoin lines the source document wrapped mid-sentence
        if current:found.append(current)
        # Explicit Q-numbers mark questions unambiguously; plain numbering keeps the shape test so numbered section headings are skipped.
        questions=[q for q,explicit in found if explicit or question_shaped(q)]
        if questions:return questions
        return [x for x in lines if question_shaped(x)]
    def classify_question(self,text):
        for category,words in {"Security":["encrypt","security","access"],"Compliance":["audit","iso","soc","compliance"],"Support":["support","response","sla"],"Legal":["legal","contract","privacy"],"Products":["product","feature"]}.items():
            if any(w in text.lower() for w in words):return category
        return "Company"
    def chat(self,messages,stream=False):return messages[-1].get("content","")[:700]

class OpenAICompatibleProvider(MockLLMProvider):
    def __init__(self,config,provider_name="OpenAI-Compatible"):
        self.config=config; self.name=provider_name
    def _url(self):
        base=(getattr(self.config,"ai_base_url",None) or getattr(self.config,"base_url",None) or "").rstrip("/")
        if self.name=="OpenRouter" and not base:base="https://openrouter.ai/api/v1"
        if self.name=="Openai" and not base:base="https://api.openai.com/v1"
        if self.name=="Ollama" and not base:base="http://localhost:11434/v1"
        if self.name=="Lm Studio" and not base:base="http://localhost:1234/v1"
        if self.name=="Ollama" and base and not base.endswith("/v1"):base+="/v1"
        path=getattr(self.config,"chat_endpoint_path",None) or "/chat/completions"
        return base+"/"+path.lstrip("/")
    def chat(self,messages,stream=False):
        if self._url()=="/chat/completions":raise RuntimeError(f"{self.name} requires an AI base URL")
        key=getattr(self.config,"ai_api_key",None) or getattr(self.config,"api_key",None);headers={"Content-Type":"application/json"}
        if key:headers["Authorization"]=f"Bearer {key}"
        headers.update(custom_headers(self.config))
        payload={"model":self.config.llm_model,"messages":messages,"temperature":self.config.temperature,"max_tokens":self.config.max_tokens,"top_p":self.config.top_p,"stream":stream}
        error=None
        for attempt in range(self.config.retry_count+1):
            try:
                response=httpx.post(self._url(),headers=headers,json=payload,timeout=self.config.timeout);response.raise_for_status()
                if stream:return response.iter_lines()
                body=response.json()
                if getattr(self.config,"openai_compatible_mode",True):content=body["choices"][0]["message"]["content"]
                else:content=body.get("response") or body.get("output") or body.get("text") or (body.get("choices") or [{}])[0].get("text") or (body.get("choices") or [{"message":{}}])[0].get("message",{}).get("content")
                # Providers occasionally return content: null (rate limiting, refusals); retry it like any other transient failure.
                if content is None or not str(content).strip():raise RuntimeError(f"{self.name} returned an empty response (model: {self.config.llm_model})")
                return content
            except Exception as exc:
                error=exc
                if attempt<self.config.retry_count:time.sleep(min(2**attempt,4))
        raise RuntimeError(f"{self.name} request failed: {error}")
    def generate_answer(self,question,context,instructions=""):
        if not context:return MANUAL
        evidence="\n\n".join(f"SOURCE: {x['document']}\n{x['content']}" for x in context)
        result=self.chat([{"role":"system","content":GROUNDING+"\n"+instructions},{"role":"user","content":f"Question: {question}\n\nRetrieved context:\n{evidence}"}])
        return (result or "").strip() or MANUAL
    def summarize(self,text):return self.chat([{"role":"system","content":"Summarize concisely."},{"role":"user","content":text}])
    def extract_questions(self,text):
        # Deterministic extraction keeps ingestion offline and consistent across providers.
        return MockLLMProvider().extract_questions(text)
    def classify_question(self,text):return MockLLMProvider().classify_question(text)

class OpenAIProvider(OpenAICompatibleProvider): pass
class AzureOpenAIProvider(OpenAICompatibleProvider): pass
class ClaudeProvider(OpenAICompatibleProvider): pass
class GeminiProvider(OpenAICompatibleProvider): pass
class OpenRouterProvider(OpenAICompatibleProvider): pass
class BedrockProvider(OpenAICompatibleProvider): pass
class OllamaProvider(OpenAICompatibleProvider): pass
class LMStudioProvider(OpenAICompatibleProvider): pass
class CustomEnterpriseLLMProvider(OpenAICompatibleProvider): pass

def get_llm(config):
    name=config.llm_provider.lower()
    if name=="mock":return MockLLMProvider()
    classes={"openai":OpenAIProvider,"azure_openai":AzureOpenAIProvider,"anthropic":ClaudeProvider,"gemini":GeminiProvider,"openrouter":OpenRouterProvider,"bedrock":BedrockProvider,"ollama":OllamaProvider,"lm_studio":LMStudioProvider,"openai_compatible":OpenAICompatibleProvider,"enterprise":CustomEnterpriseLLMProvider}
    if name not in classes:raise ValueError(f"Unknown LLM provider: {name}")
    labels={"openai":"Openai","azure_openai":"Azure OpenAI","anthropic":"Anthropic","gemini":"Gemini","openrouter":"OpenRouter","bedrock":"Bedrock","ollama":"Ollama","lm_studio":"Lm Studio","openai_compatible":"OpenAI-Compatible","enterprise":"Enterprise"}
    return classes[name](config,getattr(config,"provider_display_name",None) or labels[name])

class BaseEmbeddingProvider(ABC):
    @abstractmethod
    def embed_text(self,text:str)->list[float]: ...
    def embed_batch(self,texts):return [self.embed_text(x) for x in texts]
class MockEmbeddingProvider(BaseEmbeddingProvider):
    dimensions=128
    def embed_text(self,text):
        v=[0.0]*self.dimensions
        for token in re.findall(r"[a-z0-9]+",text.lower()):v[int(hashlib.sha256(token.encode()).hexdigest(),16)%self.dimensions]+=1
        n=math.sqrt(sum(x*x for x in v)) or 1
        return [x/n for x in v]
class APIEmbeddingProvider(BaseEmbeddingProvider):
    default_base=""
    def __init__(self,config):self.config=config
    def embed_batch(self,texts):
        base=(getattr(self.config,"embedding_base_url",None) or getattr(self.config,"base_url",None) or self.default_base).rstrip("/");key=getattr(self.config,"embedding_api_key",None) or getattr(self.config,"api_key",None);headers={}
        if key:headers["Authorization"]=f"Bearer {key}"
        headers.update(custom_headers(self.config));endpoint=base+"/"+(getattr(self.config,"embedding_endpoint_path",None) or "/embeddings").lstrip("/")
        if not base:raise RuntimeError("Embedding provider requires a base URL")
        try:
            logger.info("embedding_api_request provider=%s model=%s endpoint=%s inputs=%s",self.config.embedding_provider,self.config.embedding_model,endpoint,len(texts))
            r=httpx.post(endpoint,headers=headers,json={"model":self.config.embedding_model,"input":texts},timeout=self.config.timeout)
            if not r.is_success:raise RuntimeError(f"Embedding API HTTP {r.status_code}: {r.text[:1000]}")
            body=r.json();data=body.get("data")
            if not getattr(self.config,"openai_compatible_mode",True):data=data or body.get("embeddings") or body.get("vectors")
            if not isinstance(data,list):raise RuntimeError(f"Embedding API returned no data array: {str(body)[:1000]}")
            vectors=[x if isinstance(x,list) else x.get("embedding") or x.get("vector") for x in sorted(data,key=lambda x:x.get("index",0) if isinstance(x,dict) else 0)]
            if len(vectors)!=len(texts) or any(not isinstance(v,list) or not v for v in vectors):raise RuntimeError(f"Embedding API returned invalid vectors for {len(texts)} inputs")
            logger.info("embedding_api_response provider=%s model=%s vectors=%s dimension=%s",self.config.embedding_provider,self.config.embedding_model,len(vectors),len(vectors[0]));return vectors
        except httpx.RequestError as exc:raise RuntimeError(f"Embedding API request failed: {exc}") from exc
    def embed_text(self,text):return self.embed_batch([text])[0]
class OpenAIEmbeddingProvider(APIEmbeddingProvider):default_base="https://api.openai.com/v1"
class AzureEmbeddingProvider(APIEmbeddingProvider):pass
class OpenRouterEmbeddingProvider(APIEmbeddingProvider):default_base="https://openrouter.ai/api/v1"
class OllamaEmbeddingProvider(APIEmbeddingProvider):default_base="http://localhost:11434/v1"
class SentenceTransformerProvider(APIEmbeddingProvider):pass
class BGEProvider(APIEmbeddingProvider):pass
class E5Provider(APIEmbeddingProvider):pass
class CustomEmbeddingProvider(APIEmbeddingProvider):pass
def get_embeddings(config):
    if config is None:raise RuntimeError("Embedding configuration is required; refusing to fall back to mock")
    name=(config.embedding_provider or "").strip().lower()
    if name=="mock":return MockEmbeddingProvider()
    # "enterprise" and "custom" are the same OpenAI-compatible endpoint provider; both names are accepted so the
    # embedding choice mirrors the chat provider's naming.
    cls={"openai":OpenAIEmbeddingProvider,"azure_openai":AzureEmbeddingProvider,"openrouter":OpenRouterEmbeddingProvider,"ollama":OllamaEmbeddingProvider,"sentence_transformers":SentenceTransformerProvider,"bge":BGEProvider,"e5":E5Provider,"custom":CustomEmbeddingProvider,"enterprise":CustomEmbeddingProvider}.get(name)
    if not cls:raise ValueError(f"Unknown embedding provider: {name}")
    return cls(config)

def custom_headers(config):
    raw=getattr(config,"custom_headers",None)
    if not raw:return {}
    try:
        value=json.loads(raw) if isinstance(raw,str) else raw
    except json.JSONDecodeError as exc:raise RuntimeError(f"Custom headers must be valid JSON: {exc}") from exc
    if not isinstance(value,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in value.items()):raise RuntimeError("Custom headers must be a JSON object containing string values")
    return value
