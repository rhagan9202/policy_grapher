# DI-1 Specification — Policy Grapher

## Increment Scope
Development Increment 1 (DI-1): demonstrate end-to-end feasibility with a single structured CSV input, Neo4j graph storage, a full CRUD API, and a React graph UI.

---

## Input

### CSV Format
- **Columns**: `Document Name`, `References`, `Type` (exactly these three, in this order)
- **References field**: a Python-style stringified list, e.g. `"['Policy A', 'Policy B']"` — parsed via `ast.literal_eval`
- **Source**: file on the local filesystem, path supplied via API call; file is mounted into the backend container at `/data/`

---

## Graph Schema (Neo4j)

### Nodes
| Label | Properties | Constraints |
|---|---|---|
| `Document` | `name: str`, `type: str` | `name` is unique |

### Relationships
| Type | Direction | Meaning |
|---|---|---|
| `REFERENCES` | `(:Document)-[:REFERENCES]->(:Document)` | Document cites another document |

- Use `MERGE` on `name` for both nodes and relationships to ensure idempotent ingestion.

---

## Backend

### Stack
- Python ≥ 3.14, FastAPI, Pydantic v2, `neo4j` (official driver), `uv`, pytest, httpx

### Environment Variables
| Variable | Description |
|---|---|
| `NEO4J_URI` | Bolt URI, e.g. `bolt://neo4j:7687` |
| `NEO4J_USER` | Default `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password |

### API Endpoints

#### Ingest
| Method | Path | Description |
|---|---|---|
| `POST` | `/ingest` | Ingest a CSV file. Body: `{ "file_path": "/data/corpus.csv" }`. Returns `{ "nodes_created": int, "relationships_created": int }` |

#### Documents (CRUD)
| Method | Path | Description |
|---|---|---|
| `GET` | `/documents` | List all documents |
| `GET` | `/documents/{name}` | Get a single document and its direct references |
| `POST` | `/documents` | Create a document. Body: `DocumentIn` |
| `PUT` | `/documents/{name}` | Update `type` of a document. Body: `DocumentIn` |
| `DELETE` | `/documents/{name}` | Delete a document and all its relationships (`DETACH DELETE`) |

#### Graph & Query
| Method | Path | Description |
|---|---|---|
| `GET` | `/graph` | Return full graph: `{ "nodes": [...], "edges": [...] }` — used by the UI |
| `POST` | `/query` | Execute a raw Cypher string. Body: `{ "cypher": "MATCH ..." }`. Returns list of records |

### Pydantic Models
- `DocumentIn`: `name: str`, `type: str`
- `DocumentOut`: `name: str`, `type: str`, `references: list[str]`
- `GraphNode`: `id: str`, `label: str`, `type: str`
- `GraphEdge`: `source: str`, `target: str`
- `GraphOut`: `nodes: list[GraphNode]`, `edges: list[GraphEdge]`

### CORS
Allow all origins (no auth required for DI-1).

---

## Frontend

### Stack
- React, Vite, TypeScript, vitest, `react-force-graph` (2D), `react-router-dom`

### Pages / Views
| View | Route | Description |
|---|---|---|
| Graph Explorer | `/` | Force-directed graph of all nodes and edges via `GET /graph`. Node click shows name + type tooltip. |
| Document Table | `/documents` | Table of all documents from `GET /documents`. Client-side search/filter by document name. Each row shows name, type, and references list. |

### API Client
- Typed fetch wrappers in `src/api/client.ts` covering all backend endpoints.

---

## Deployment

### docker-compose Services
| Service | Image | Ports | Notes |
|---|---|---|---|
| `neo4j` | `neo4j:latest` | 7474, 7687 | Auth enabled via env vars |
| `backend` | Custom (uv-based) | 8000 | Mounts `./data:/data` |
| `frontend` | Custom (Node/Vite) | 5173 | Proxies `/api` to backend for DI-1 |

---

## Out of DI-1 Scope
- PDF, DOCX, XLSX ingestion
- Authentication or authorisation
- RAG, LLM calls, vector embeddings
- Production multi-stage Docker builds
- Corpus management beyond the document table
- Pagination (corpus ≤ 20 documents, graph ≤ 300 nodes for DI-1)
