# SI Chatbot - Microservico de IA

Microservico em FastAPI para atendimento inteligente do CRM da SI - Solucoes Imobiliarias.

Ele pode responder usando a API da OpenAI quando `OPENAI_API_KEY` estiver configurada no `.env`.
Caso a chave nao exista, o servico continua funcionando com respostas locais baseadas em regras para leads, follow-up, funil e imoveis.

## Tecnologias

- Python 3.12+
- FastAPI
- Uvicorn
- HTTPX
- Pydantic Settings
- OpenAI Chat Completions API

## Estrutura principal

```text
.
|-- main.py            # Aplicacao FastAPI e regras do chatbot
|-- requirements.txt   # Dependencias Python
|-- .env.example       # Exemplo de variaveis de ambiente
|-- .env               # Variaveis locais reais, nao versionar
|-- .gitignore         # Arquivos ignorados pelo Git
`-- Dockerfile         # Build da imagem Docker
```

## Passo a passo para rodar localmente

### 1. Entrar na pasta do projeto

```powershell
cd C:\Projetos\ai-service
```

### 2. Criar ambiente virtual

```powershell
py -m venv .venv
```

### 3. Ativar ambiente virtual

No PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear scripts, execute uma vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Depois tente ativar novamente:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4. Instalar dependencias

```powershell
py -m pip install -r requirements.txt
```

### 5. Configurar variaveis de ambiente

Crie um arquivo `.env` baseado no `.env.example`.

Exemplo:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
```

Para usar a OpenAI, preencha:

```env
OPENAI_API_KEY=sua_chave_aqui
OPENAI_MODEL=gpt-4o-mini
```

Se `OPENAI_API_KEY` ficar vazio, o projeto ainda roda normalmente usando o modo local:

```json
{
  "provider": "local-rules"
}
```

Quando a chave estiver configurada corretamente, o retorno usa:

```json
{
  "provider": "openai"
}
```

### 6. Rodar o projeto

Com o ambiente virtual ativo, rode:

```powershell
py -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

O servico ficara disponivel em:

```text
http://localhost:8000
```

## Testar se esta online

Abra no navegador:

```text
http://localhost:8000/health
```

Ou teste pelo PowerShell:

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:8000/health
```

Resposta esperada:

```json
{
  "status": "ok"
}
```

## Endpoints

### `GET /health`

Verifica se o microservico esta online.

Resposta:

```json
{
  "status": "ok"
}
```

### `POST /chat`

Envia mensagens para o assistente.

Payload:

```json
{
  "userId": "uuid-do-usuario",
  "messages": [
    {
      "role": "user",
      "content": "Quais leads devo priorizar hoje?"
    }
  ],
  "context": "Resumo da tela atual do CRM"
}
```

Resposta:

```json
{
  "reply": "Texto gerado pelo assistente",
  "suggestions": [
    "Quais leads devo priorizar hoje?",
    "Crie uma mensagem de WhatsApp para follow-up.",
    "Como organizar meu funil de vendas?"
  ],
  "provider": "openai"
}
```

## Como enviar dados do CRM para a IA

O microservico recebe dados do CRM pelo campo `context` do endpoint `POST /chat`.
Esse campo deve ser montado pelo backend do CRM antes de chamar este servico.
No projeto SI, esse contexto e um JSON em string com dados reais do usuario autenticado.

Fluxo recomendado:

```text
Frontend CRM
  -> envia pergunta do usuario para o backend do CRM
Backend CRM
  -> busca dados relevantes no banco
  -> monta crm e matchedCrm no campo context
  -> chama POST /chat neste microservico
AI Service
  -> responde usando a pergunta + contexto do CRM
Frontend CRM
  -> exibe a resposta no chat
```

Formato recomendado do `context`:

```json
{
  "generatedAt": "2026-06-14T12:00:00.000Z",
  "instructions": "Use somente os dados deste contexto do CRM para responder.",
  "extraContext": "{...contexto da tela enviado pelo frontend...}",
  "matchedCrm": {
    "instructions": [
      "Use estes candidatos como recorte prioritario da conversa atual."
    ],
    "searchTerms": ["gervasio", "candeias"],
    "leads": [
      {
        "id": "lead-id",
        "contactName": "Gervasio",
        "company": "Apartamento Candeias",
        "value": 450000,
        "notes": "Cliente pediu retorno sobre visita.",
        "nextFollowUp": "2026-06-15T14:00:00.000Z",
        "status": {
          "id": "status-id",
          "name": "Visita agendada",
          "order": 3
        },
        "imovel": {
          "id": "imovel-id",
          "title": "Apartamento Candeias",
          "propertyType": "Apartamento",
          "city": "Candeias",
          "state": "BA",
          "price": 450000
        }
      }
    ],
    "imoveis": []
  },
  "crm": {
    "totals": {
      "statuses": 4,
      "leads": 20,
      "upcomingContacts": 3,
      "imoveis": 12
    },
    "statuses": [],
    "recentLeads": [],
    "upcomingContacts": [],
    "imoveis": [],
    "unavailableData": ["tarefas", "historico dedicado de interacoes"]
  }
}
```

`matchedCrm` e o recorte mais importante para perguntas especificas. Ele e montado pelo backend usando as ultimas mensagens do usuario e deve priorizar leads que combinem cliente + imovel. Exemplo:

```text
Usuario: quero saber quais passos tomar com cliente gervasio
Usuario: imovel apartamento candeias
```

Nesse caso, o backend deve tentar colocar o lead correto em `matchedCrm.leads[0]`.
Quando isso acontecer, o microservico instrui a OpenAI a responder sobre esse lead sem pedir nova confirmacao.

O que enviar em `crm` depende da tela ou acao do usuario:

| Tela ou recurso | Dados recomendados |
| --- | --- |
| Lista de leads | Nome, status, origem, interesse, valor estimado, ultimo contato e proximo contato. |
| Detalhe do lead | Dados do lead, status, observacoes, proximo follow-up e imovel relacionado. |
| Imovel | Dados do imovel, valor, localizacao resumida, caracteristicas e leads interessados. |
| Dashboard | Quantidade por status, tarefas vencidas, proximos contatos e oportunidades de maior valor. |
| Kanban/funil | Cards visiveis, status atual, tempo parado na etapa e proxima acao registrada. |

Evite enviar o banco inteiro para a IA. Envie somente os dados necessarios para responder a pergunta atual.
Tambem evite dados sensiveis desnecessarios, como CPF, documentos, endereco completo e informacoes financeiras detalhadas.

## Exemplo de teste do chat via PowerShell

```powershell
$body = @{
  userId = "usuario-teste"
  messages = @(
    @{
      role = "user"
      content = "Crie uma mensagem de WhatsApp para follow-up."
    }
  )
  context = "Lead: Maria, interesse em apartamento, proximo contato hoje."
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri http://localhost:8000/chat `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

## Rodar com Docker

Build da imagem:

```powershell
docker build -t si-ai-service .
```

Rodar o container:

```powershell
docker run --rm -p 8000:8000 --env-file .env si-ai-service
```

Depois acesse:

```text
http://localhost:8000/health
```

## Variaveis de ambiente

| Variavel | Obrigatoria | Padrao | Descricao |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Nao | vazio | Chave da API da OpenAI. Sem ela, usa respostas locais. |
| `OPENAI_MODEL` | Nao | `gpt-4o-mini` | Modelo usado nas respostas via OpenAI. |

## Observacoes importantes

- O arquivo `.env` nao deve ser enviado para o Git.
- O arquivo `.env.example` deve ser mantido no projeto como referencia.
- Antes de rodar o projeto, instale as dependencias com `py -m pip install -r requirements.txt`.
- O comando recomendado para iniciar em desenvolvimento e `py -m uvicorn main:app --reload --host 0.0.0.0 --port 8000`.
- Sem `OPENAI_API_KEY`, o servico nao chama a OpenAI e usa respostas locais.
