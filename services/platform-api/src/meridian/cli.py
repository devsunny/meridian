from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from .context import new_request_id

CONFIG_PATH = Path(os.getenv("MERIDIAN_CONFIG", Path.home() / ".meridian" / "config.json"))


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        CONFIG_PATH.chmod(0o600)


class Client:
    def __init__(self, url: str | None, token: str | None, as_json: bool = False) -> None:
        config = _load_config()
        self.url = (url or config.get("url") or os.getenv("MERIDIAN_URL") or "http://localhost:8000").rstrip("/")
        self.token = token or config.get("token") or os.getenv("MERIDIAN_TOKEN")
        self.as_json = as_json

    def _headers(self) -> dict[str, str]:
        headers = {"X-Request-ID": new_request_id(), "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.url}/api/v1{path}" if path.startswith("/") else f"{self.url}/{path}"
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            _fail(f"Cannot reach {self.url}: {exc.__class__.__name__}")
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("detail", payload)
            except ValueError:
                detail = response.text
            _fail(f"HTTP {response.status_code}: {detail}")
        if response.status_code == 204:
            return None
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)


def _fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _print(data: Any, as_json: bool, columns: list[str] | None = None) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict) and "results" in data:
        rows = data["results"]
    else:
        print(json.dumps(data, indent=2, default=str))
        return
    if not rows:
        print("(none)")
        return
    columns = columns or list(rows[0].keys())
    widths = {column: max(len(column), *(len(str(row.get(column, ""))) for row in rows)) for column in columns}
    print("  ".join(column.upper().ljust(widths[column]) for column in columns))
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(str(row.get(column, ""))[: widths[column]].ljust(widths[column]) for column in columns))


def _login(args: argparse.Namespace) -> None:
    config = _load_config()
    url = args.url or config.get("url") or "http://localhost:8000"
    password = args.password or getpass.getpass("Password: ")
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{url.rstrip('/')}/api/v1/auth/login",
            json={"email": args.email, "password": password},
            headers={"X-Request-ID": new_request_id()},
        )
    if response.status_code >= 400:
        _fail(response.json().get("detail", response.text))
    payload = response.json()
    _save_config({"url": url.rstrip("/"), "token": payload["access_token"], "email": args.email, "role": payload["user"]["role"]})
    print(f"Signed in as {args.email} ({payload['user']['role']}) at {url}")
    print(f"Token stored in {CONFIG_PATH}")


def _cmd_sources(client: Client, args: argparse.Namespace) -> None:
    if args.action == "list":
        _print(client.get("/connections"), client.as_json, ["id", "name", "type", "status", "last_test_ok"])
    elif args.action == "types":
        _print(client.get("/connectors"), client.as_json, ["type", "label", "category"])
    elif args.action == "create":
        config = json.loads(args.config) if args.config else {}
        payload = {
            "name": args.name,
            "type": args.type,
            "description": args.description or "",
            "config": config,
            "secret_ref": args.secret_ref,
        }
        _print(client.post("/connections", json=payload), client.as_json)
    elif args.action == "test":
        _print(client.post(f"/connections/{args.id}/test"), client.as_json)
    elif args.action == "discover":
        _print(client.post(f"/connections/{args.id}/discover"), client.as_json, ["id", "name", "kind", "size"])


def _cmd_ingestions(client: Client, args: argparse.Namespace) -> None:
    if args.action == "list":
        _print(client.get("/ingestions"), client.as_json, ["id", "name", "connection_id", "target_dataset", "status"])
    elif args.action == "run":
        _print(client.post(f"/ingestions/{args.id}/run", json={"force": args.force}), client.as_json)
    elif args.action == "runs":
        _print(client.get(f"/ingestions/{args.id}/runs"), client.as_json, ["id", "status", "created_at", "request_id"])


def _cmd_pipelines(client: Client, args: argparse.Namespace) -> None:
    if args.action == "list":
        _print(client.get("/pipelines"), client.as_json, ["id", "name", "current_version", "status", "owner"])
    elif args.action == "run":
        _print(client.post(f"/pipelines/{args.id}/run", json={"debug": args.debug}), client.as_json)
    elif args.action == "validate":
        _print(client.post(f"/pipelines/{args.id}/validate"), client.as_json)


def _cmd_runs(client: Client, args: argparse.Namespace) -> None:
    if args.action == "list":
        _print(client.get("/runs", params={"limit": args.limit}), client.as_json, ["id", "kind", "status", "trigger", "created_at"])
    elif args.action == "show":
        _print(client.get(f"/runs/{args.id}"), client.as_json)
    elif args.action == "log":
        last = 0
        seen = 0
        while True:
            payload = client.get(f"/runs/{args.id}/logs", params={"limit": 2000})
            entries = payload["entries"]
            for entry in entries[seen:] if not args.follow else entries:
                if args.follow and entry.get("timestamp") == last:
                    continue
                print(json.dumps(entry, default=str))
            if not args.follow:
                return
            seen = len(entries)
            run = client.get(f"/runs/{args.id}")
            if run["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                return
            time.sleep(2)
    elif args.action == "cancel":
        _print(client.post(f"/runs/{args.id}/cancel"), client.as_json)
    elif args.action == "resume":
        _print(client.post(f"/runs/{args.id}/resume", json={"task_id": args.task, "note": "cli"}), client.as_json)


def _cmd_catalog(client: Client, args: argparse.Namespace) -> None:
    if args.action == "list":
        _print(client.get("/datasets"), client.as_json, ["id", "name", "layer", "classification", "row_count", "owner"])
    elif args.action == "search":
        _print(client.get("/catalog/search", params={"q": args.query}), client.as_json, ["id", "name", "layer", "classification"])
    elif args.action == "preview":
        payload = client.get(f"/datasets/{args.id}/preview", params={"limit": args.limit})
        _print(payload["rows"], client.as_json)
    elif args.action == "lineage":
        _print(client.get(f"/datasets/{args.id}/lineage"), client.as_json)


def _cmd_ask(client: Client, args: argparse.Namespace) -> None:
    payload = client.post("/assist/ask", json={"question": args.question, "top_k": 6})
    if client.as_json:
        print(json.dumps(payload, indent=2))
        return
    print(payload["answer"])
    if payload["citations"]:
        print("\nCitations:")
        for citation in payload["citations"]:
            print(f"  [{citation['index']}] {citation['title']} p.{citation['page'] or '-'} ({citation['source_uri']})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="meridian", description="Meridian data platform CLI")
    parser.add_argument("--url", help="API URL (default from ~/.meridian/config.json)")
    parser.add_argument("--token", help="Bearer token")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Sign in and store a token")
    login.add_argument("--email", default="admin@meridian.local")
    login.add_argument("--password")
    login.set_defaults(func=lambda client, args: _login(args))

    status = sub.add_parser("status", help="Platform and tenant summary")
    status.set_defaults(func=lambda client, args: _print(client.get("/dashboard"), client.as_json))

    sources = sub.add_parser("sources", help="Manage source connections")
    sources_sub = sources.add_subparsers(dest="action", required=True)
    sources_sub.add_parser("list")
    sources_sub.add_parser("types")
    create = sources_sub.add_parser("create")
    create.add_argument("--name", required=True)
    create.add_argument("--type", required=True)
    create.add_argument("--config", help="JSON config")
    create.add_argument("--secret-ref")
    create.add_argument("--description")
    test = sources_sub.add_parser("test")
    test.add_argument("id")
    discover = sources_sub.add_parser("discover")
    discover.add_argument("id")
    sources.set_defaults(func=_cmd_sources)

    ingestions = sub.add_parser("ingestions", help="Manage ingestion definitions")
    ingestions_sub = ingestions.add_subparsers(dest="action", required=True)
    ingestions_sub.add_parser("list")
    run = ingestions_sub.add_parser("run")
    run.add_argument("id")
    run.add_argument("--force", action="store_true")
    runs = ingestions_sub.add_parser("runs")
    runs.add_argument("id")
    ingestions.set_defaults(func=_cmd_ingestions)

    pipelines = sub.add_parser("pipelines", help="Manage DAG workflows")
    pipelines_sub = pipelines.add_subparsers(dest="action", required=True)
    pipelines_sub.add_parser("list")
    run = pipelines_sub.add_parser("run")
    run.add_argument("id")
    run.add_argument("--debug", action="store_true")
    validate = pipelines_sub.add_parser("validate")
    validate.add_argument("id")
    pipelines.set_defaults(func=_cmd_pipelines)

    runs = sub.add_parser("runs", help="Inspect and control runs")
    runs_sub = runs.add_subparsers(dest="action", required=True)
    list_runs = runs_sub.add_parser("list")
    list_runs.add_argument("--limit", type=int, default=20)
    show = runs_sub.add_parser("show")
    show.add_argument("id")
    log = runs_sub.add_parser("log")
    log.add_argument("id")
    log.add_argument("--follow", action="store_true")
    cancel = runs_sub.add_parser("cancel")
    cancel.add_argument("id")
    resume = runs_sub.add_parser("resume")
    resume.add_argument("id")
    resume.add_argument("--task")
    runs.set_defaults(func=_cmd_runs)

    catalog = sub.add_parser("catalog", help="Browse governed datasets")
    catalog_sub = catalog.add_subparsers(dest="action", required=True)
    catalog_sub.add_parser("list")
    search = catalog_sub.add_parser("search")
    search.add_argument("query")
    preview = catalog_sub.add_parser("preview")
    preview.add_argument("id")
    preview.add_argument("--limit", type=int, default=20)
    lineage = catalog_sub.add_parser("lineage")
    lineage.add_argument("id")
    catalog.set_defaults(func=_cmd_catalog)

    ask = sub.add_parser("ask", help="Ask the governed RAG assistant")
    ask.add_argument("question")
    ask.set_defaults(func=_cmd_ask)

    schedules = sub.add_parser("schedules", help="Inspect schedules")
    schedules_sub = schedules.add_subparsers(dest="action", required=True)
    schedules_sub.add_parser("list")
    run_now = schedules_sub.add_parser("run-now")
    run_now.add_argument("id")
    schedules.set_defaults(
        func=lambda client, args: _print(
            client.post(f"/schedules/{args.id}/run-now") if args.action == "run-now" else client.get("/schedules"),
            client.as_json,
            ["id", "name", "cron", "enabled", "next_run_at"],
        )
    )

    terminal = sub.add_parser("terminal", help="Show the URL of the web terminal")
    terminal.set_defaults(
        func=lambda client, args: print(
            f"Open {client.url.replace(':8000', ':3000')}/terminal after signing in to the web console."
        )
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    raw = list(argv if argv is not None else sys.argv[1:])
    # Accept common flags before or after the subcommand, e.g. `meridian login --url ...`.
    extracted: dict[str, Any] = {"url": None, "token": None, "json": False}
    cleaned: list[str] = []
    index = 0
    while index < len(raw):
        item = raw[index]
        if item in {"--url", "--token"}:
            if index + 1 >= len(raw):
                parser.error(f"{item} requires a value")
            extracted[item[2:]] = raw[index + 1]
            index += 2
            continue
        if item.startswith("--url=") or item.startswith("--token="):
            key, value = item[2:].split("=", 1)
            extracted[key] = value
            index += 1
            continue
        if item == "--json":
            extracted["json"] = True
            index += 1
            continue
        cleaned.append(item)
        index += 1
    args = parser.parse_args(cleaned)
    args.url = extracted["url"] or args.url
    args.token = extracted["token"] or args.token
    args.json = bool(extracted["json"] or args.json)
    client = Client(args.url, args.token, args.json)
    args.func(client, args)


if __name__ == "__main__":
    main()
