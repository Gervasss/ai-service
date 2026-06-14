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
Você é o assistente da SI - Soluções Imobiliárias, integrado a um CRM de leads.
Responda em português do Brasil, com orientação prática para corretores e gestores.
Ajude a priorizar leads, sugerir follow-ups, organizar próximas ações e interpretar
informações de imóveis e pipeline. Seja objetivo e não invente dados ausentes.
Quando o contexto tiver matchedCrm, use esse recorte primeiro para resolver cliente,
lead e imóvel citados na conversa. Se matchedCrm trouxer um único lead compatível,
responda sobre ele sem pedir nova confirmação.
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
                "content": f"Contexto disponível no CRM:\n{payload.context}",
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
            "Para priorizar hoje, comece pelos leads com próximo contato vencendo ou já vencido, "
            "valor mais alto e status mais perto de fechamento. Depois revise quem tem telefone "
            "e observações completas, porque esses contatos tendem a destravar mais rápido.\n\n"
            f"{summarize_context(context)}"
        )

    if has_any(text, ["mensagem", "whatsapp", "follow", "retorno", "contato"]):
        return (
            "Sugestão de abordagem: 'Olá, tudo bem? Passei para saber se o imóvel ainda faz "
            "sentido para você e se posso te ajudar com alguma informação: valores, visita ou "
            "opções parecidas. Qual melhor horário para falarmos hoje?'\n\n"
            "Se o lead já demonstrou urgência, ofereça dois horários específicos para visita."
        )

    if has_any(text, ["imovel", "apartamento", "casa", "valor", "preco"]):
        return (
            "Ao falar do imóvel, conecte três pontos: necessidade do cliente, diferencial do "
            "imóvel e próxima ação. Exemplo: perfil familiar combina com quartos/área; investidor "
            "valoriza liquidez, localização e margem de negociação."
        )

    if has_any(text, ["status", "kanban", "funil", "pipeline"]):
        return (
            "Use o Kanban como rotina diária: novos leads precisam de primeiro contato rápido, "
            "leads em negociação precisam de uma próxima ação registrada, e leads parados devem "
            "receber tentativa final ou mudança de status para manter o funil limpo."
        )

    return (
        "Posso ajudar a analisar leads, sugerir próximo contato, montar mensagens para clientes "
        "e organizar prioridades do funil imobiliário. Me diga qual lead, status ou objetivo você "
        "quer trabalhar agora."
    )


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def summarize_context(context: str) -> str:
    if not context:
        return "Se quiser uma recomendação mais precisa, envie o nome do lead, status, valor e data de próximo contato."

    lead_count = len(re.findall(r"\bLead:", context, flags=re.IGNORECASE))
    if lead_count:
        return f"Pelo contexto recebido, encontrei {lead_count} lead(s) para considerar na análise."

    return "Use os dados do CRM como apoio: status atual, valor estimado, origem e próximo follow-up."


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
    imovel_title = imovel.get("title") or lead.get("company") or "imóvel não informado"
    next_follow_up = lead.get("nextFollowUp") or "não cadastrado"
    notes = lead.get("notes") or "sem observações cadastradas"
    value = lead.get("value") or imovel.get("price") or "não cadastrado"

    return (
        f"Para o cliente {contact_name}, relacionado ao imóvel {imovel_title}, "
        f"o próximo passo deve considerar o status atual: {status_name}.\n\n"
        f"Dados do CRM:\n"
        f"- Status: {status_name}\n"
        f"- Valor: {value}\n"
        f"- Próximo contato: {next_follow_up}\n"
        f"- Observações: {notes}\n\n"
        "Ação recomendada: entre em contato com o cliente usando o contexto do imóvel, "
        "confirme se o interesse continua ativo e registre uma próxima ação objetiva no CRM "
        "(visita, proposta, envio de detalhes ou follow-up com data definida)."
    )


def default_suggestions() -> list[str]:
    return [
        "Quais leads devo priorizar hoje?",
        "Crie uma mensagem de WhatsApp para follow-up.",
        "Como organizar meu funil de vendas?",
    ]
