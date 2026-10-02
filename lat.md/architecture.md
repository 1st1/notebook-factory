# Notebook Factory

A public notebook library with owner-only Jupyter editing, deployed as React and FastAPI Vercel Services.

## Services

The root service configuration routes API traffic to [[backend/main.py]] and other requests to [[frontend/src/main.tsx]]. The frontend embeds rendered notebooks and the live Jupyter editor in separate iframe modes.

## Persistence

[[backend/db.py]] stores notebook source, published source, metadata, and editor capabilities in Postgres on Vercel or SQLite locally. Draft saves do not change the public version; publishing copies the draft into the published version.

## Editing

[[backend/editor.py]] uses the Python Sandbox SDK to install JupyterLab and run its server. Random capability paths protect editor routes. The bridge in [[backend/assets/jupyter_bridge.js]] validates parent origin and awaits Jupyter's document save API.

Editor operations use an atomic database lease to serialize provisioning, saves, and closes. The browser saves drafts every thirty seconds and extends the sandbox lease. Closing saves before stopping. Public readers never receive sandbox capabilities.

## Authentication

[[backend/auth.py]] implements GitHub OAuth with signed, expiring state and session cookies. Every mutation checks the signed GitHub identity against 1st1 and validates the request Origin. Notebook HTML is served under a restrictive sandbox CSP.

## Authorization tests

[[backend/tests/test_app.py]] checks anonymous, non-owner, and cross-origin requests against all mutation endpoints, plus forged cookies and OAuth state.

## Persistence tests

[[backend/tests/test_app.py]] verifies editor reuse, stale tokens, private drafts, publication, restoration after closing, public rendering isolation, concurrent startup serialization, expired editor restoration, and failure cleanup.
