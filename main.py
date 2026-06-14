import json
import re
from typing import Literal

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    userId: str
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    context: str | None = Field(default=None, max_length=20000)


class ChatResponse(BaseModel):
    reply: str
    suggestions: list[str]
    provider: str


settings = Settings()
app = FastAPI(title="SI Chatbot", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


SYSTEM_PROMPT = """
Voce e o assistente da SI - Solucoes Imobiliarias, integrado a um CRM de leads.
Responda em portugues do Brasil, com orientacao pratica para corretores e gestores.
Ajude a priorizar leads, sugerir follow-ups, organizar proximas acoes e interpretar
informacoes de imoveis e pipeline. Seja objetivo e nao invente dados ausentes.
Quando o contexto tiver matchedCrm, use esse recorte primeiro para resolver cliente,
lead e imovel citados na conversa. Se matchedCrm trouxer um unico lead compativel,
responda sobre ele sem pedir nova confirmacao.
""".strip()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    if settings.openai_api_key:
        reply = await chat_with_openai(payload)
        return ChatResponse(reply=reply, suggestions=default_suggestions(), provider="openai")

    return ChatResponse(
        reply=build_local_reply(payload),
        suggestions=default_suggestions(),
        provider="local-rules",
    )


async def chat_with_openai(payload: ChatRequest) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if payload.context:
        messages.append(
            {
                "role": "system",
                "content": f"Contexto disponivel no CRM:\n{payload.context}",
            }
        )

    messages.extend(message.model_dump() for message in payload.messages)

    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.openai_model,
                "messages": messages,
                "temperature": 0.35,
                "max_tokens": 500,
            },
        )
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"].strip()


def build_local_reply(payload: ChatRequest) -> str:
    last_message = payload.messages[-1].content.strip()
    text = last_message.lower()
    context = payload.context or ""
    matched_lead = get_first_matched_lead(context)

    if matched_lead:
        return build_matched_lead_reply(matched_lead)

    if has_any(text, ["priorizar", "prioridade", "quais leads", "hoje"]):
        return (
            "Para priorizar hoje, comece pelos leads com proximo contato vencendo ou ja vencido, "
            "valor mais alto e status mais perto de fechamento. Depois revise quem tem telefone "
            "e observacoes completas, porque esses contatos tendem a destravar mais rapido.\n\n"
            f"{summarize_context(context)}"
        )

    if has_any(text, ["mensagem", "whatsapp", "follow", "retorno", "contato"]):
        return (
            "Sugestao de abordagem: 'Ola, tudo bem? Passei para saber se o imovel ainda faz "
            "sentido para voce e se posso te ajudar com alguma informacao: valores, visita ou "
            "opcoes parecidas. Qual melhor horario para falarmos hoje?'\n\n"
            "Se o lead ja demonstrou urgencia, ofereca dois horarios especificos para visita."
        )

    if has_any(text, ["imovel", "apartamento", "casa", "valor", "preco"]):
        return (
            "Ao falar do imovel, conecte tres pontos: necessidade do cliente, diferencial do "
            "imovel e proxima acao. Exemplo: perfil familiar combina com quartos/area; investidor "
            "valoriza liquidez, localizacao e margem de negociacao."
        )

    if has_any(text, ["status", "kanban", "funil", "pipeline"]):
        return (
            "Use o Kanban como rotina diaria: novos leads precisam de primeiro contato rapido, "
            "leads em negociacao precisam de uma proxima acao registrada, e leads parados devem "
            "receber tentativa final ou mudanca de status para manter o funil limpo."
        )

    return (
        "Posso ajudar a analisar leads, sugerir proximo contato, montar mensagens para clientes "
        "e organizar prioridades do funil imobiliario. Me diga qual lead, status ou objetivo voce "
        "quer trabalhar agora."
    )


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def summarize_context(context: str) -> str:
    if not context:
        return "Se quiser uma recomendacao mais precisa, envie o nome do lead, status, valor e data de proximo contato."

    lead_count = len(re.findall(r"\bLead:", context, flags=re.IGNORECASE))
    if lead_count:
        return f"Pelo contexto recebido, encontrei {lead_count} lead(s) para considerar na analise."

    return "Use os dados do CRM como apoio: status atual, valor estimado, origem e proximo follow-up."


def parse_context(context: str) -> dict:
    try:
        parsed = json.loads(context)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def get_first_matched_lead(context: str) -> dict | None:
    parsed = parse_context(context)
    matched = parsed.get("matchedCrm")
    if not isinstance(matched, dict):
        return None

    leads = matched.get("leads")
    if not isinstance(leads, list) or not leads:
        return None

    first = leads[0]
    return first if isinstance(first, dict) else None


def build_matched_lead_reply(lead: dict) -> str:
    status = lead.get("status") if isinstance(lead.get("status"), dict) else {}
    imovel = lead.get("imovel") if isinstance(lead.get("imovel"), dict) else {}
    contact_name = lead.get("contactName") or "cliente"
    status_name = status.get("name") or "sem status cadastrado"
    imovel_title = imovel.get("title") or lead.get("company") or "imovel nao informado"
    next_follow_up = lead.get("nextFollowUp") or "nao cadastrado"
    notes = lead.get("notes") or "sem observacoes cadastradas"
    value = lead.get("value") or imovel.get("price") or "nao cadastrado"

    return (
        f"Para o cliente {contact_name}, relacionado ao imovel {imovel_title}, "
        f"o proximo passo deve considerar o status atual: {status_name}.\n\n"
        f"Dados do CRM:\n"
        f"- Status: {status_name}\n"
        f"- Valor: {value}\n"
        f"- Proximo contato: {next_follow_up}\n"
        f"- Observacoes: {notes}\n\n"
        "Acao recomendada: entre em contato com o cliente usando o contexto do imovel, "
        "confirme se o interesse continua ativo e registre uma proxima acao objetiva no CRM "
        "(visita, proposta, envio de detalhes ou follow-up com data definida)."
    )


def default_suggestions() -> list[str]:
    return [
        "Quais leads devo priorizar hoje?",
        "Crie uma mensagem de WhatsApp para follow-up.",
        "Como organizar meu funil de vendas?",
    ]
