# Configuring the Analyst

The analyst reads its configuration from environment variables, which the
compose file takes from a `.env` file beside `docker-compose.yml`. This page
describes adding a provider for the briefs and using your own PostgreSQL
server. The [Settings Reference](#settings-reference) section describes every
setting that a compose deployment uses.

## Adding a Provider for the Briefs

The analyst derives the findings, and a verdict for every category, from the
archive itself. A provider writes the briefs and can raise a verdict, as the
[Introduction](index.md#deriving-the-verdicts) describes. To add a provider,
set `RADAR_ANALYST_AI_PROVIDER` and the provider's credential in the `.env`
file. Then recreate the analyst's container to apply the settings. The default
provider, `claude`, needs only a credential. Add the following line to the
`.env` file, and create the file if it does not exist:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

The following command recreates the analyst's container with the new setting:

```bash
docker compose up -d --wait
```

Existing assessments keep their findings and verdicts. To add briefs to an
existing assessment, open the assessment and select **Assess again**.

The
[examples/compose.env](https://github.com/pgEdge/radar-analyst/blob/main/examples/compose.env)
file is a commented template for the `.env` file. The
`RADAR_ANALYST_AI_PROVIDER` setting selects the provider and defaults to
`claude`. The following table describes the supported providers:

| Provider | Service | Credential | Default model |
|---|---|---|---|
| `claude` | [Anthropic](https://platform.claude.com/) | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |
| `gemini` | [Google AI Studio](https://aistudio.google.com/) | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | `gemini-3.7-flash` |
| `openai` | [OpenAI](https://platform.openai.com/), or an OpenAI-compatible server | `OPENAI_API_KEY` | `gpt-5.6-luna` |
| `local` | [Ollama](https://ollama.com/) | None | `gemma4:e4b` |

The `claude` and `gemini` providers always use the default model in the table.
The `OPENAI_MODEL` setting selects the model for `openai`, and
`RADAR_ANALYST_OLLAMA_MODEL` selects the model for `local`. Every provider
other than `claude` also needs `RADAR_ANALYST_AI_PROVIDER` set to the
provider's name. The following `.env` lines select Google AI Studio:

```bash
RADAR_ANALYST_AI_PROVIDER=gemini
GOOGLE_API_KEY=...
```

### Using an OpenAI-Compatible Server

The `openai` provider works with any server that implements the OpenAI chat
completions API. Such servers include [vLLM](https://docs.vllm.ai/),
[LM Studio](https://lmstudio.ai/),
[llama.cpp](https://github.com/ggml-org/llama.cpp),
[OpenRouter](https://openrouter.ai/), and [Groq](https://groq.com/). To use
such a server, set the server's address and model name in `.env`. Set
`OPENAI_API_KEY` even when the server ignores the key, because the
[OpenAI client library](https://github.com/openai/openai-python) requires a
key. The following `.env` file selects a server at `inference.example.com`:

```bash
RADAR_ANALYST_AI_PROVIDER=openai
OPENAI_BASE_URL=http://inference.example.com:8000/v1
OPENAI_API_KEY=unused
OPENAI_MODEL=Qwen/Qwen3-32B
```

Inside the analyst's container, `localhost` in `OPENAI_BASE_URL` refers to that
container rather than the machine that runs Docker. Use an address that the
analyst's container can reach.

### Using a Local Ollama Server

The `local` provider sends requests to an [Ollama](https://ollama.com/) server
that you run, at the address in `RADAR_ANALYST_OLLAMA_HOST`. The analyst then
writes the briefs without sending data to an outside service. The following
`.env` line selects the provider:

```bash
RADAR_ANALYST_AI_PROVIDER=local
```

The compose file sets `RADAR_ANALYST_OLLAMA_HOST` to
`http://host.docker.internal:11434`, which addresses an Ollama server on the
machine that runs Docker. The compose file maps the `host.docker.internal` name
itself. The name therefore resolves on both
[Docker Desktop](https://docs.docker.com/desktop/) and
[Docker Engine](https://docs.docker.com/engine/install/) for Linux. On Docker
Engine for Linux, the Ollama server must also listen on an address that
containers can reach. Ollama listens only on `127.0.0.1` by default, and the
`OLLAMA_HOST` environment variable of the Ollama server changes that address.
To use a different Ollama server, set `RADAR_ANALYST_OLLAMA_HOST` in `.env` to
an address that the analyst's container can reach.

The Ollama server must already have the model, because the analyst does not
download models. The following command downloads the default model on the
Ollama server:

```bash
ollama pull gemma4:e4b
```

The default model needs approximately 10 GB of GPU memory to run entirely on
the GPU. The model runs more slowly on a GPU with less memory.

## Using Your Own PostgreSQL Server

The analyst stores its assessments in PostgreSQL. The compose file includes a
database for this purpose, but the analyst can use an existing PostgreSQL
server instead. The compose file sets `RADAR_ANALYST_STATE_DB_URL` directly and
ignores any value in `.env`. To use your own server, edit the
`RADAR_ANALYST_STATE_DB_URL` entry under the `app` service in
`docker-compose.yml`. Set the entry to the connection URL of your database,
without a password:

```yaml
      RADAR_ANALYST_STATE_DB_URL: >-
        postgresql://radar_analyst@db.example.com/radar_analyst?sslmode=require
```

Then set `RADAR_ANALYST_DB_PASSWORD` in `.env` to the password of the role in
the URL. The compose file passes that variable to the analyst as the database
password, which needs no URL encoding. To stop running the bundled database,
also remove the `db` service from the compose file. Then remove the
`depends_on` entry that waits for the `db` service.

This database holds only the analyst's own state and is never the server under
assessment. Before you start the analyst, make sure that:

- the database uses the UTF8 encoding, which the analyst checks at startup.
- the role in the URL has the `CREATE` privilege on the database.

Under SQL_ASCII, PostgreSQL returns text as raw bytes, so the analyst refuses
to start rather than misread its own rows. With any other encoding, the analyst
logs a warning. Such an encoding may not represent all text in a radar archive
correctly. The analyst uses the privilege at startup to create the `radar`
schema for all of its tables.

## Settings Reference

Every setting in this section is optional, and an empty value counts as unset.
The following table describes the settings that the compose file reads from the
`.env` file:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_AI_PROVIDER` | `claude` | This setting selects the provider that writes the briefs: `claude`, `gemini`, `openai`, or `local`. Any other value stops the analyst at startup. |
| `ANTHROPIC_API_KEY` | Unset | This variable sets the credential that the `claude` provider uses. |
| `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Unset | Either variable sets the credential that the `gemini` provider uses. When you set both variables, the analyst uses `GOOGLE_API_KEY`. |
| `OPENAI_API_KEY` | Unset | This variable sets the credential that the `openai` provider uses. The OpenAI client library requires a key, even for a server that ignores the key. |
| `OPENAI_BASE_URL` | OpenAI's own endpoint | This variable sets the address of an OpenAI-compatible server. |
| `OPENAI_MODEL` | `gpt-5.6-luna` | This variable selects the model that the `openai` provider uses. A compatible server needs the name of a model that the server provides. |
| `RADAR_ANALYST_OLLAMA_HOST` | `http://host.docker.internal:11434` | This variable sets the address of the Ollama server for `local`. |
| `RADAR_ANALYST_OLLAMA_MODEL` | `gemma4:e4b` | This variable selects the model that the `local` provider uses. |
| `RADAR_ANALYST_ADMIN_TOKEN` | Generated | This variable sets the token that authorizes deletes. When the variable is unset, the analyst generates a token into `/data/admin-token` on first start. |
| `RADAR_ANALYST_DB_PASSWORD` | `radar_analyst` | This variable sets the bundled database's password. The database stores the password when it first starts with an empty `db` volume. The analyst connects with the same value, so a later change also needs `ALTER ROLE` in the database. |

The analyst also reads the following settings, which the compose file does not
pass through from `.env`. To change one of these settings, add the variable to
the `environment` section of the `app` service in `docker-compose.yml`. The
following table describes each of these additional settings:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_MAX_UPLOAD_BYTES` | `524288000` (500 MiB) | This variable sets the largest upload request that the analyst accepts, in bytes. The request also contains the form's framing, so the largest archive is slightly smaller. A value that is not a positive integer logs a warning, and the analyst uses the default. |
| `RADAR_ANALYST_OLLAMA_CONCURRENCY` | `3` | This variable sets the maximum number of requests that `local` sends to Ollama at once. A value that is not a positive integer logs a warning, and the analyst uses the default. |
| `RADAR_ANALYST_LOG_LEVEL` | `INFO` | This variable sets the log level, such as `DEBUG`, `INFO`, `WARNING`, or `ERROR`, in any letter case. An unknown level stops the analyst at startup. |

The compose file sets `RADAR_ANALYST_STATE_DB_URL` directly, as
[Using Your Own PostgreSQL Server](#using-your-own-postgresql-server)
describes. The [Developer Resources](developers.md) page describes the settings
that apply only outside a container.

## Next Steps

The following documents describe the next steps after the configuration:

- The [Using the Analyst](using.md) document describes how to assess a radar
  archive.
- The [Managing an Installation](managing.md) document describes the volumes,
  the logs, backups, and upgrades.
- The [Troubleshooting](troubleshooting.md) document describes the messages
  that a provider or a setting can cause.
