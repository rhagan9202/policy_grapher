# This repo is for the development of the policy_grapher project initial demonstration of feasibility and MVP demo.

# Overview

- the overall end goal of the program is the development of a knowledge/policy management system - Policy Concierge

## Required Capabilities

- Ingest policy documents and guidelines, extract policy points, metadata such as what entities the policy applies to, who is responsible for enforcing the policy, references to associated/referenced policy, etc.
- Construct a knowledge graph in Neo4j capturing the complex interactions and relationships between documents and policies
- Expose an api endpoint for users/agents to query the graph using Cypher
- Provides a lightweight UI that allows users to visualize and explore the graph similar to the functionality of Neo4j Bloom
- UI allows users to search for documents/policies and are shown the object and its related documents/lineage/metadata

## MVP scope and definition of done

- Can handle a Corpus of 20 documents
- Ingests documents from file system
- Processes PDF's, docx, xlsx and csv file types
- Spins up and works on docker containers
- Uses Neo4j latest container
- Can visualize and explore graph up to 300 nodes
- Corpus management through tables of ingested corpus documents allowing review of text and metadata.
- API calls allow successful queries and return proper payload.
- Users can search by document name or id

## Out of initial scope

- RAG functionality or LLM calls
- vector embeddings and vector stores

## Target stack

- python >3.14, pytest, fastAPI, pydantic, neo4j, uv, docker
- React, vite, vitest
