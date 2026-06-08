# industrial-flow

**industrial-flow** é uma ferramenta Python para extrair dados de historiadores industriais, como PI System / Osisoft, e publicar eventos de tags em sistemas de mensageria como Apache Kafka e Google Cloud Pub/Sub.

O objetivo é servir como ponte entre PIMS/OT e plataformas modernas de dados, incluindo data lakes, feature stores, pipelines de streaming, BigQuery, Spark, Flink, Dataflow e soluções de Machine Learning.

## Visão geral

```text
PI Server / Planta A ─┐
PI Server / Planta B ─┼── industrial-flow ── Kafka / PubSub / JSONL
PI Server / Planta C ─┘
```

A ferramenta suporta dois modos de implantação:

1. **Uma instância central multi-site**, quando todos os PI Servers são acessíveis pela mesma rede.
2. **Uma instância por planta/edge**, quando cada planta tem rede, DMZ, firewall ou requisitos operacionais próprios.

Em ambos os casos, o mesmo código e o mesmo modelo de configuração são usados.

## Principais recursos

- Suporte a várias plantas / vários PI Servers.
- Execução por uma planta específica ou por todas as plantas.
- Leitura paralela por partições de tags.
- Cache persistente de Point IDs do PI por planta e PI Server.
- Checkpoint independente por planta.
- Publisher plugável para Kafka, Google Pub/Sub, arquivo JSONL e console.
- Override de tópico Kafka, tópico Pub/Sub e arquivo de saída por planta.
- Decoder dedicado para `istat` negativo do PI 3 como Digital State.
- Resolução do texto do Digital State via PI API clássica usando `pipt_digstate()`.
- Cache persistente de Digital States por planta e PI Server, usando o `digital_code` negativo como chave.
- Modo simulador para desenvolvimento local sem PI Server.

## Modelo de evento

```json
{
  "source": "piapi",
  "server": "PI-SERVER-1",
  "site": "site-1",
  "tag": "tag-name-1",
  "timestamp": "2026-06-02T13:00:00Z",
  "value": 82.4,
  "quality": "GOOD",
  "point_id": 12345,
  "value_type": "numeric",
  "digital_code": null,
  "digital_set_id": null,
  "digital_state_id": null,
  "digital_state_name": null,
  "raw_istat": 0
}
```

Quando o PI retorna `istat` negativo, o evento fica assim:

```json
{
  "value": "Shutdown",
  "quality": "DIGITAL_STATE",
  "value_type": "digital",
  "digital_code": -131087,
  "digital_set_id": 2,
  "digital_state_id": 15,
  "digital_state_name": "Shutdown",
  "raw_istat": -131087
}
```

## Sobre `istat` negativo / digital state

O código implementa a lógica indicada no seu script original: em PI 3, um `istat` negativo deve ser interpretado como estado digital, não como inteiro comum.

Na PI API clássica, o próprio `istat` negativo é preservado como `digital_code` e usado diretamente na chamada:

```python
status = piapi.pipt_digstate(
    c_int(digital_code),
    state_buffer,
    c_int(buffer_size),
)
```

Quando `pipt_digstate()` retorna sucesso, o evento recebe o texto industrial do estado, por exemplo `Bad Input`, `Open`, `Closed`, `Shutdown` ou outro estado configurado no PI Server.

A implementação também mantém a decomposição bitwise como metadado auxiliar para troubleshooting:

```python
raw = abs(istat)
digital_set_id = (raw >> 16) & 0xFFFF
digital_state_id = raw & 0xFFFF
```

O evento publicado não trata o estado digital como uma medição numérica comum. Ele preserva `digital_code`, `digital_state_name`, `digital_set_id`, `digital_state_id` e `raw_istat`. Isso evita perder semântica industrial ao carregar os dados no Kafka, Pub/Sub, BigQuery ou em uma feature store.

## Estratégia de performance

Para milhares de tags, o processamento é feito em camadas:

```text
site
 ├── tags_file
 ├── partitions de tags
 ├── workers paralelos
 ├── cache de Point IDs por worker
 └── publicação em batch
```

Exemplo:

```text
20.000 tags
partition_size = 500
max_workers = 8

Resultado:
40 partições
8 workers paralelos
batches de publicação de 10.000 eventos
```

O backend `piapi` usa DLLs legadas do PI API. Por segurança, cada worker cria seu próprio reader e as chamadas de baixo nível são protegidas por lock dentro do reader. 

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

pip install -e .
```

Com Kafka:

```bash
pip install -e '.[kafka]'
```

Com Google Pub/Sub:

```bash
pip install -e '.[pubsub]'
```

Completo:

```bash
pip install -e '.[all]'
```

## Execução sem Instalação

Se você não quiser instalar o pacote no seu ambiente Python (evitando o `pip install -e .`), você pode instalar apenas as dependências do projeto e utilizar o script `run.py` fornecido na raiz do repositório:

```bash
# Instalar dependências básicas
pip install -r requirements.txt

# Instalar dependências extras opcionais (caso utilize Kafka ou Pub/Sub)
pip install confluent-kafka google-cloud-pubsub
```

Para rodar qualquer comando, basta executar utilizando `python run.py`:

```bash
python run.py --help
python run.py validate-config --config config/config.yaml
```

## Configuração multi-site

Arquivo principal:

```text
config/config.yaml
```

Exemplo:

```yaml
sites:
  - id: "site1"
    enabled: true
    pi:
      provider: "piapi"
      server: "PI-SERVER-1"
      username: "pidemo"
      password_env: "PI_SERVER_1_PASSWORD"
    tags_file: "config/tags/site1.txt"
    kafka_topic: "industrial-flow.site1.pi-tags"
    pubsub_topic_id: "industrial-flow-site1-pi-tags"
    file_output_path: "output/site1/events.jsonl"
    read:
      interval_seconds: 60
      window_seconds: 300
      tag_partition_size: 500
      max_workers: 8
      batch_size: 10000

  - id: "site2"
    enabled: true
    pi:
      provider: "piapi"
      server: "PI-SERVER-2"
      username: "pidemo"
      password_env: "PI_SERVER_2_PASSWORD"
    tags_file: "config/tags/site2.txt"
    kafka_topic: "industrial-flow.site2.pi-tags"

publisher:
  type: "kafka"
  kafka:
    bootstrap_servers: "localhost:9092"
    topic: "industrial-flow.pi-tags"
```

Os campos `kafka_topic`, `pubsub_topic_id` e `file_output_path` sobrescrevem o destino global somente para aquela planta.

## Comandos

> [!TIP]
> Caso esteja utilizando a **execução sem instalação**, substitua o comando `industrial-flow` por `python run.py` (ex: `python run.py validate-config ...`).

Validar configuração:

```bash
industrial-flow validate-config --config config/config.yaml
```

Executar histórico para todas as plantas habilitadas:

```bash
industrial-flow historical \
  --start "2026-06-01T00:00:00Z" \
  --end "2026-06-01T01:00:00Z" \
  --config config/config.yaml
```

Executar histórico para uma planta:

```bash
industrial-flow historical \
  --site site1 \
  --start "2026-06-01T00:00:00Z" \
  --end "2026-06-01T01:00:00Z" \
  --config config/config.yaml
```

Executar histórico para algumas plantas:

```bash
industrial-flow historical \
  --site site1,site2 \
  --start "2026-06-01T00:00:00Z" \
  --end "2026-06-01T01:00:00Z" \
  --config config/config.yaml
```

Executar uma janela incremental com checkpoint por planta:

```bash
industrial-flow once --site site1 --config config/config.yaml
python -m industrial_flow.cli once --site site1 --config config/config.yaml
```

Executar contínuo para todas as plantas:

```bash
industrial-flow realtime --config config/config.yaml
python -m industrial_flow.cli realtime --config config/config.yaml
```

Executar contínuo para uma planta:

```bash
industrial-flow realtime --site site1 --config config/config.yaml
```

## Kafka local para teste

```bash
docker compose -f docker-compose.kafka.yml up -d
```

Depois altere:

```yaml
publisher:
  type: "kafka"
```

## Google Pub/Sub

Configure autenticação do Google Cloud, por exemplo com `GOOGLE_APPLICATION_CREDENTIALS`, e ajuste:

```yaml
publisher:
  type: "pubsub"
  pubsub:
    project_id: "meu-projeto"
    topic_id: "industrial-flow-pi-tags"
```

Para múltiplas plantas, use `pubsub_topic_id` em cada site.

## Recomendações de tuning

Comece conservador:

```yaml
read:
  tag_partition_size: 250
  max_workers: 4
  batch_size: 5000
```

Depois aumente gradualmente:

```yaml
read:
  tag_partition_size: 500
  max_workers: 8
  batch_size: 10000
```

Para backfill histórico grande:

```yaml
read:
  window_seconds: 3600
  tag_partition_size: 1000
  max_workers: 8
  batch_size: 20000
```

Para near-real-time:

```yaml
read:
  window_seconds: 60
  interval_seconds: 10
  tag_partition_size: 250
  max_workers: 4
```

## Desenvolvimento

```bash
pip install -e '.[dev]'
pytest
ruff check .
```

## Evoluções imaginadas

- Criar uma interface gráfica
- Cache persistente de Point IDs em SQLite por site/servidor/tag.
- Métricas Prometheus.
- DLQ para eventos com erro.
- Schema Avro/Protobuf e Schema Registry.
- Deduplicação/idempotência no destino.

## Cache de Point IDs do PI

O `industrial-flow` mantém um cache persistente de `point_id` por planta e por PI Server. Isso evita executar `pipt_findpoint` para todas as tags em toda execução, reduzindo muito o overhead quando há milhares de tags.

Configuração:

```yaml
read:
  checkpoint_file: ".checkpoints/industrial-flow.json"
  point_cache_file: ".cache/industrial-flow-pointids.json"
  digital_state_cache_file: ".cache/industrial-flow-digital-states.json"
```

O cache é isolado por `site.id` e `pi.server`. Tags não encontradas não são persistidas no cache, permitindo que sejam resolvidas futuramente caso sejam criadas no PI Server.

## Cache de Digital States

Além do cache de Point IDs, o `industrial-flow` mantém um cache persistente de Digital States por `site.id` e `pi.server`.

Quando o PI retorna `istat < 0`, o decoder extrai:

```text
digital_set_id   = upper 16 bits
digital_state_id = lower 16 bits
```

Em seguida, a ferramenta consulta o cache de Digital States. Se houver uma resolução conhecida, o evento sai enriquecido com os nomes do conjunto e do estado. Se ainda não houver resolução, o evento preserva os IDs e marca a origem como `unresolved`, evitando transformar um estado industrial em um número sem contexto.

Arquivo de cache:

```yaml
read:
  digital_state_cache_file: ".cache/industrial-flow-digital-states.json"
```

Formato interno do cache:

```json
{
  "site1": {
    "pi-site1": {
      "2": {
        "15": {
          "digital_code": -131087,
          "digital_set_id": 2,
          "digital_state_id": 15,
          "digital_state_name": "Shutdown",
          "source": "cache"
        }
      }
    }
  }
}
```

No backend `piapi`, a resolução nominal fica isolada no método `_resolve_digital_state`, que usa a função da PI API clássica `pipt_digstate()`. Mesmo quando essa chamada retorna erro para um código específico, a ferramenta não perde a semântica essencial: `digital_code`, `digital_set_id`, `digital_state_id` e `raw_istat` continuam preservados no evento.
